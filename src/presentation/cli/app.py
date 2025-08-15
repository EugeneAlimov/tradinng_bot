#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — консольный лончер бота/бэктеста под EXMO с безопасными режимами.

Фичи:
- Режимы: --live disabled|observe|trade (по умолчанию observe: сигналы без заявок)
- Синхронизация балансов/ордеров/позиций на старте (плейсхолдеры под ваш API)
- Маркировка «своих» clientOrderId префиксом BOT_
- Риск‑гвард: дневной лимит убытка в б.п. и «кулдаун» N баров после сделки
- Бэктест SMA(fast/slow) с fee/slippage, выгрузка trades.csv / equity.csv / report.json
- Построение графиков OHLC+объём и equity (png)
- Отладочный EXMO‑трейс по переменной окружения EXMO_DEBUG=1

Зависимости: pandas, numpy, matplotlib, requests
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

# =========================
# 1) Режимы, маркировка, sync
# =========================

class LiveMode(str, Enum):
    DISABLED = "disabled"   # не подключаться к бирже
    OBSERVE  = "observe"    # считать сигналы, но НЕ слать ордера
    TRADE    = "trade"      # слать ордера

def should_place_orders(mode: "LiveMode") -> bool:
    return mode == LiveMode.TRADE

BOT_TAG_PREFIX = "BOT_"

def make_client_order_id(strategy_name: str, salt: str) -> str:
    return f"{BOT_TAG_PREFIX}{strategy_name}_{salt}"

def is_our_order(order: Dict[str, Any]) -> bool:
    cid = order.get("clientOrderId") or order.get("client_order_id") or ""
    return isinstance(cid, str) and cid.startswith(BOT_TAG_PREFIX)

def sync_exchange_state(api) -> Tuple[Dict[str, float], List[Dict[str, Any]], Dict[str, float]]:
    """
    Унифицированный «снимок» биржи на старте.
    Ожидаемые методы api (кастомизируйте под свой клиент):
      - get_balances() -> {"EUR": 812.3, "DOGE": 5234.0, ...}
      - get_open_orders() -> [ {...}, ... ] (желательно с clientOrderId)
      - get_positions() -> {"DOGE": 5234.0, ...} (если нет — будет собран из балансов)
    """
    try:
        balances = api.get_balances()
    except Exception:
        balances = {}
    try:
        open_orders = api.get_open_orders() or []
        for o in open_orders:
            o["ours"] = is_our_order(o)
    except Exception:
        open_orders = []
    try:
        positions = api.get_positions()
    except Exception:
        # Если это спот — позиции = остатки в базовых активах
        positions = {k: v for k, v in balances.items() if k not in ("EUR", "USD", "USDT", "USDC")}
    return balances, open_orders, positions


class OrderManager:
    """Учитывает «чужие» лимитки пользователя и уважает режим observe."""
    def __init__(self, api):
        self.api = api

    def filter_available_balance(self, balances: Dict[str, float], open_orders: List[Dict[str, Any]],
                                 quote: str, base: str) -> Tuple[float, float]:
        reserved_quote = 0.0
        reserved_base  = 0.0
        for o in open_orders:
            if is_our_order(o):
                continue
            symbol = o.get("symbol") or ""
            if symbol in (f"{base}_{quote}", f"{base}/{quote}"):
                side = (o.get("side") or "").lower()
                if side == "buy":
                    reserved_quote += float(o.get("amount_quote") or o.get("quote_amount") or 0.0)
                elif side == "sell":
                    reserved_base  += float(o.get("amount_base") or o.get("base_amount")
                                            or o.get("quantity") or 0.0)
        free_quote = max(0.0, float(balances.get(quote, 0.0)) - reserved_quote)
        free_base  = max(0.0, float(balances.get(base, 0.0))  - reserved_base)
        return free_quote, free_base

    def place_if_allowed(self, mode_should_trade: bool, **order_kwargs) -> Dict[str, Any]:
        if not mode_should_trade:
            return {"status": "skipped", "reason": "observe mode"}
        try:
            return self.api.place_order(**order_kwargs)
        except Exception as e:
            return {"status": "error", "error": str(e), "kwargs": order_kwargs}


# =========================
# 2) Риск‑гвард
# =========================

@dataclasses.dataclass
class RiskLimits:
    max_daily_loss_bps: float = 0.0
    cooldown_bars: int = 0

class RiskGuard:
    def __init__(self, limits: RiskLimits):
        self.limits = limits
        self._day_start: Optional[datetime] = None
        self._day_start_equity: Optional[float] = None
        self._last_trade_bar_index: Optional[int] = None
        self.paused_reason: Optional[str] = None

    def on_new_day(self, equity: float, now: datetime):
        if (self._day_start is None) or (now.date() != self._day_start.date()):
            self._day_start = now
            self._day_start_equity = equity
            self.paused_reason = None

    def notify_trade(self, bar_index: int):
        self._last_trade_bar_index = bar_index

    def _check_cooldown(self, bar_index: int) -> Optional[str]:
        n = self.limits.cooldown_bars
        if not n: return None
        if self._last_trade_bar_index is None: return None
        if bar_index - self._last_trade_bar_index < n:
            return f"cooldown {bar_index - self._last_trade_bar_index}/{n} bars"
        return None

    def _check_daily_loss(self, equity: float) -> Optional[str]:
        limit = self.limits.max_daily_loss_bps
        if not limit or self._day_start_equity is None: return None
        change_bps = (equity - self._day_start_equity) / self._day_start_equity * 1e4
        if change_bps <= -abs(limit):
            return f"daily loss hit ({change_bps:.1f} ≤ -{abs(limit):.1f} bps)"
        return None

    def can_trade(self, bar_index: int, equity: float) -> Tuple[bool, Optional[str]]:
        r = self._check_daily_loss(equity)
        if r:
            self.paused_reason = r
            return False, r
        r = self._check_cooldown(bar_index)
        if r:
            return False, r
        return True, None


# =========================
# 3) Утилиты EXMO и загрузка свечей
# =========================

EXMO_DEBUG = os.environ.get("EXMO_DEBUG", "0") not in ("0", "", "false", "False", "no", "NO")

def exmo_get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if EXMO_DEBUG:
        print(f"[EXMO] → GET {url} params= {params}", flush=True)
    t0 = time.time()
    r = requests.get(url, params=params, timeout=20)
    dt = (time.time() - t0) * 1000
    if EXMO_DEBUG:
        print(f"[EXMO] ← {r.status_code} in {dt:.0f}ms", flush=True)
    r.raise_for_status()
    return r.json()

def parse_span(span: str) -> Tuple[int, int]:
    """'1m:600' -> (resolution_min=1, limit=600)"""
    res, count = span.split(":")
    unit = res[-1].lower()
    val = int(res[:-1])
    if unit == "m":
        res_min = val
    elif unit == "h":
        res_min = val * 60
    elif unit == "d":
        res_min = val * 60 * 24
    else:
        raise ValueError("resolution must end with m/h/d")
    return res_min, int(count)

def fetch_exmo_candles(symbol: str, span: str) -> pd.DataFrame:
    """
    Загружает свечи с EXMO /v1.1/candles_history
    symbol: 'DOGE_EUR'
    span: '1m:600', '5m:2000' (резолюция берём из span)
    """
    res_min, limit = parse_span(span)
    # EXMO принимает resolution как минуты (int). Ограничим «окно» по времени.
    now = int(time.time())
    total_sec = res_min * 60 * limit
    ts_from = now - total_sec
    url = "https://api.exmo.com/v1.1/candles_history"
    data = exmo_get(url, {"symbol": symbol, "resolution": res_min, "from": ts_from, "to": now})

    candles = data.get("candles") or data.get("data") or []
    if not candles:
        raise RuntimeError(f"no candles returned for {symbol} {span}")

    # EXMO формат: [{'t': 1710000000, 'o':..., 'h':..., 'l':..., 'c':..., 'v':...}, ...]
    df = pd.DataFrame(candles)[["t", "o", "h", "l", "c", "v"]]
    df = df.rename(columns={"t": "time", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    return df

def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if not rule:
        return df.copy()
    df = df.set_index("time")
    o = df["open"].resample(rule).first()
    h = df["high"].resample(rule).max()
    l = df["low"].resample(rule).min()
    c = df["close"].resample(rule).last()
    v = df["volume"].resample(rule).sum()
    out = pd.concat([o, h, l, c, v], axis=1).dropna()
    out.reset_index(inplace=True)
    return out


# =========================
# 4) Простенький бэктест SMA
# =========================

def run_backtest_sma(df: pd.DataFrame, fast: int, slow: int,
                     start_eur: float, qty_eur: float,
                     fee_bps: float, slip_bps: float) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Один актив, один лот на сигнал. Покупка на пересечении вверх, продажа на пересечении вниз.
    Торгуем «на следующий бар» по цене open*(1±slip_bps/1e4). Комиссия fee_bps взимается на каждом трейде.
    Возвращает (trades_df, equity_df, report).
    """
    df = df.copy()
    df["sma_fast"] = df["close"].rolling(fast).mean()
    df["sma_slow"] = df["close"].rolling(slow).mean()
    df["signal"] = np.where(df["sma_fast"] > df["sma_slow"], 1, 0)
    df["xover"] = df["signal"].diff().fillna(0)  # +1 — золотой крест; -1 — мертвый

    cash = start_eur
    qty_base = 0.0
    trades: List[Dict[str, Any]] = []
    equity_rows: List[Dict[str, Any]] = []

    def price_with_slip(p: float, side: str) -> float:
        slip = slip_bps / 1e4
        return p * (1 + slip) if side == "buy" else p * (1 - slip)

    for i in range(1, len(df)):
        t = df.iloc[i]["time"]
        o = float(df.iloc[i]["open"])
        mid = o  # исполняем по open следующего бара
        equity = cash + qty_base * float(df.iloc[i]["close"])
        equity_rows.append({"time": t, "equity": equity})

        # сигналы
        xover = int(df.iloc[i]["xover"])
        if xover > 0 and qty_base <= 0.0:
            # BUY
            px = price_with_slip(mid, "buy")
            amount_eur = min(qty_eur, cash)  # не уходим в минус
            if amount_eur >= 1e-9 and px > 0:
                qty = amount_eur / px
                fee = amount_eur * (fee_bps / 1e4)
                cash -= (amount_eur + fee)
                qty_base += qty
                trades.append({
                    "time": t.isoformat(),
                    "side": "buy",
                    "price": px,
                    "qty_base": qty,
                    "amount_quote": amount_eur,
                    "fee_quote": fee,
                    "pnl_quote": 0.0,
                })

        elif xover < 0 and qty_base > 0.0:
            # SELL — разгружаем весь объём
            px = price_with_slip(mid, "sell")
            amount_eur = qty_base * px
            fee = amount_eur * (fee_bps / 1e4)
            cash += (amount_eur - fee)
            trades.append({
                "time": t.isoformat(),
                    "side": "sell",
                    "price": px,
                    "qty_base": qty_base,
                    "amount_quote": amount_eur,
                    "fee_quote": fee,
                    "pnl_quote": 0.0,
            })
            qty_base = 0.0

    # Закрытая PnL по сделкам
    pnl = 0.0
    for tr in trades:
        # подсчёт простым спариванием buy->sell батчами
        if tr["side"] == "sell":
            # найдём последнюю несведённую покупку
            # (для простоты считаем, что всегда продаём всё, что купили одной порцией)
            # pnl = выручка - затраты (без двойного учёта fee)
            # т.к. мы сохраняем fee отдельно, оставим pnl в 0,
            # а итог посчитаем через equity.
            pass

    # финальная equity
    if len(equity_rows) == 0:
        # нет баров для расчёта — создадим один
        equity_rows.append({"time": df.iloc[-1]["time"], "equity": cash + qty_base * df.iloc[-1]["close"]})

    equity_df = pd.DataFrame(equity_rows)
    end_equity = float(equity_df["equity"].iloc[-1])
    start_equity = float(equity_df["equity"].iloc[0])
    total_pnl = end_equity - start_equity

    # метрики (минимальный набор)
    ret = equity_df["equity"].pct_change().fillna(0.0)
    if ret.std() > 0:
        sharpe = (ret.mean() / ret.std()) * math.sqrt(365*24*12)  # условно для 5‑мин баров (~12 в час)
    else:
        sharpe = 0.0
    # max drawdown
    cummax = equity_df["equity"].cummax()
    dd = (equity_df["equity"] / cummax - 1.0).min()
    max_dd = abs(float(dd))
    wins = 0
    losses = 0
    # грубая оценка win_rate по росту/падению equity между сделками
    if len(trades) >= 2:
        # по парам (buy,sell)
        # (оставим как 0/1 если мало сделок)
        pass

    trades_df = pd.DataFrame(trades)
    report = {
        "stats": {
            "cash": round(cash, 6),
            "equity": round(end_equity, 6),
        },
        "metrics": {
            "start": round(start_equity, 6),
            "end": round(end_equity, 6),
            "total_pnl": round(total_pnl, 6),
            "trades": float(len(trades)),
            "win_rate": float(100.0 * (wins / max(1, wins + losses))),
            "profit_factor": float(0.0),   # можно рассчитать при наличии pnl по сделкам
            "max_drawdown": float(max_dd),
            "sharpe": float(sharpe),
            "cagr": float(0.0),            # для интрадей пока опустим
        }
    }
    return trades_df, equity_df, report


# =========================
# 5) Визуализация
# =========================

def plot_ohlc_with_volume(df: pd.DataFrame, out_path: str, title: str):
    if df.empty:
        return
    # Фигура: верх — свечи, низ — объём
    fig = plt.figure(figsize=(20, 6))
    gs = fig.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.05)
    ax = fig.add_subplot(gs[0, 0])
    axv = fig.add_subplot(gs[1, 0], sharex=ax)

    ax.set_title(title, fontsize=22, pad=10)
    times = mdates.date2num(pd.to_datetime(df["time"]).dt.tz_convert("UTC"))
    for i in range(len(df)):
        t = times[i]
        o, h, l, c, v = df.iloc[i][["open", "high", "low", "close", "volume"]]
        color = "green" if c >= o else "red"
        # свеча
        ax.vlines(t, l, h, color=color, linewidth=1)
        ax.add_patch(Rectangle((t - 0.0015, min(o, c)),
                               0.003, abs(c - o) if abs(c - o) > 1e-9 else 0.0002,
                               edgecolor=color, facecolor="white", linewidth=1))
        # объём
        axv.bar(t, v, width=0.003, align="center", edgecolor="none", alpha=0.6, color="green")

    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_ylabel("price")
    axv.set_ylabel("vol")
    axv.grid(True, linestyle=":", alpha=0.4)
    axv.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M\n%Y-%b-%d", tz=timezone.utc))
    plt.setp(ax.get_xticklabels(), visible=False)
    fig.autofmt_xdate()
    plt.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)

def plot_equity(equity_df: pd.DataFrame, out_path: str, title: str = "Backtest Equity Curve (EUR)"):
    if equity_df.empty:
        return
    fig = plt.figure(figsize=(20, 5))
    ax = fig.add_subplot(111)
    ax.plot(equity_df["time"], equity_df["equity"])
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_title(title, fontsize=22, pad=10)
    ax.set_ylabel("equity")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M\n%Y-%b-%d", tz=timezone.utc))
    fig.autofmt_xdate()
    plt.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)


# =========================
# 6) CLI
# =========================

def main():
    parser = argparse.ArgumentParser(description="EXMO SMA bot / backtester")
    parser.add_argument("--exmo-pair", default="DOGE_EUR", help="e.g. DOGE_EUR")
    parser.add_argument("--exmo-candles", default="1m:600", help="e.g. 1m:600")
    parser.add_argument("--resample", default="", help="e.g. 5m, 15m (pandas rule)")
    parser.add_argument("--backtest", action="store_true", help="run offline backtest")
    parser.add_argument("--fast", type=int, default=10)
    parser.add_argument("--slow", type=int, default=30)
    parser.add_argument("--fee-bps", type=float, default=10.0)
    parser.add_argument("--slip-bps", type=float, default=2.0)
    parser.add_argument("--start-eur", type=float, default=1000.0)
    parser.add_argument("--qty-eur", type=float, default=200.0)

    # сохранение
    parser.add_argument("--save-trades", default="", help="CSV path")
    parser.add_argument("--save-equity", default="", help="CSV path")
    parser.add_argument("--save-report", default="", help="JSON path")
    parser.add_argument("--exmo-plot", default="", help="OHLC chart png")
    parser.add_argument("--plot-equity", default="", help="Equity png")

    # безопасные режимы и риск‑лимиты
    parser.add_argument("--live", choices=["disabled", "observe", "trade"], default="observe")
    parser.add_argument("--max-daily-loss-bps", type=float, default=0.0)
    parser.add_argument("--cooldown-bars", type=int, default=0)

    args = parser.parse_args()
    live_mode = LiveMode(args.live)

    # 1) Загрузка свечей
    df = fetch_exmo_candles(args.exmo_pair, args.exmo_candles)
    if args.resample:
        df = resample_ohlcv(df, args.resample)

    # 2) Бэктест (по умолчанию — да, раз пользователь так запускает)
    trades_df = pd.DataFrame()
    equity_df = pd.DataFrame()
    report = {}
    if args.backtest:
        trades_df, equity_df, report = run_backtest_sma(
            df, fast=args.fast, slow=args.slow,
            start_eur=args.start_eur, qty_eur=args.qty_eur,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps
        )

        # Отчёт в консоль
        metrics = report.get("metrics", {})
        print(f"[bt] equity={metrics.get('end', 0):.6f}  trades={int(metrics.get('trades', 0))} "
              f"win_rate={metrics.get('win_rate', 0):.2f}%  pf={metrics.get('profit_factor', 0):.2f}  "
              f"dd={metrics.get('max_drawdown', 0)*100:.2f}%  sharpe={metrics.get('sharpe', 0):.2f}")

    # 3) Графики
    if args.exmo_plot:
        first = df["time"].iloc[0].isoformat()
        last  = df["time"].iloc[-1].isoformat()
        print(f"[plot] OHLC: points={len(df)}  first={first}  last={last}")
        plot_ohlc_with_volume(df, args.exmo_plot, f"EXMO candles {args.exmo_pair} {args.resample or args.exmo_candles}")
        print(f"→ Chart saved to: {args.exmo_plot}")

    if args.plot_equity and not equity_df.empty:
        plot_equity(equity_df, args.plot_equity)
        print(f"→ Equity chart saved to: {args.plot_equity}")

    # 4) Сохранения
    if args.save_trades and not trades_df.empty:
        os.makedirs(os.path.dirname(args.save_trades), exist_ok=True)
        trades_df.to_csv(args.save_trades, index=False)
        print(f"→ Trades CSV saved to: {args.save_trades}")

    if args.save_equity and not equity_df.empty:
        os.makedirs(os.path.dirname(args.save_equity), exist_ok=True)
        equity_df.to_csv(args.save_equity, index=False)
        print(f"→ Equity CSV saved to: {args.save_equity}")

    if args.save_report and report:
        os.makedirs(os.path.dirname(args.save_report), exist_ok=True)
        with open(args.save_report, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"→ Report JSON saved to: {args.save_report}")

    # 5) Заглушка «лайв» (observe/trade)
    # Здесь можно подключить ваш реальный api-клиент EXMO/биржи и использовать RiskGuard + OrderManager
    if live_mode != LiveMode.DISABLED and not args.backtest:
        print(f"[live] mode={live_mode}. Для реальной торговли подключите api-клиент и цикл обработки баров/сигналов.")

    # Итог
    if args.backtest:
        print(f"EXMO candles[{args.exmo_pair}] rows={len(df)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        if EXMO_DEBUG:
            import traceback
            traceback.print_exc()
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
