# src/presentation/cli/app.py
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import math
from collections import defaultdict
import matplotlib.dates as mdates

from src.config.settings import get_settings
from src.core.domain.models import TradingPair
from src.infrastructure.market.random_walk import RandomWalkMarket
from src.infrastructure.exchange.paper_exchange import PaperExchange
from src.infrastructure.storage.files import FileStorage
from src.infrastructure.notify.log import LogNotifier
from src.application.engine.trade_engine import TradeEngine

# Стратегии
from src.domain.strategy.sma_crossover import SmaCrossover, SmaCfg
from src.domain.strategy.mean_reversion import MeanReversion

# Доменные сервисы
from src.domain.risk.risk_service import RiskService
from src.domain.portfolio.position_service import PositionService

# EXMO API (без ExmoCredentials — делаем универсальный конструктор)
from src.infrastructure.exchange.exmo_api import ExmoApi


# ──────────────────────────────────────────────────────────────────────────────
# Утилиты времени/ТФ
# ──────────────────────────────────────────────────────────────────────────────
def _parse_time_hint(s: Optional[str]) -> Optional[int]:
    """Возвращает epoch-секунды для: '1717351410', '2025-08-09T14:00', '24h'/'7d'/'90m'."""
    if not s:
        return None
    s = s.strip()
    # относительные
    try:
        if s.endswith(("h", "m", "d")):
            n = int(s[:-1])
            now = datetime.now(timezone.utc)
            if s.endswith("h"):
                return int((now - timedelta(hours=n)).timestamp())
            if s.endswith("m"):
                return int((now - timedelta(minutes=n)).timestamp())
            if s.endswith("d"):
                return int((now - timedelta(days=n)).timestamp())
    except Exception:
        pass
    # epoch
    try:
        return int(s)
    except Exception:
        pass
    # ISO
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _split_tf_limit(arg: str) -> Tuple[str, int]:
    """Разбирает 'TF:LIMIT' → ('1m', 200)."""
    tf, _, lim = (arg or "").partition(":")
    if not tf or not lim:
        raise SystemExit("Неверный формат. Пример: --exmo-candles 1m:200")
    try:
        lim_i = int(lim)
    except Exception:
        raise SystemExit("LIMIT должен быть целым числом")
    if lim_i <= 0:
        raise SystemExit("LIMIT должен быть > 0")
    return tf.strip(), lim_i


def _tf_to_minutes(tf: str | int) -> int:
    """'1m'/'1h'/'1d'/int → минуты (минимум 1)."""
    if isinstance(tf, int):
        return max(1, tf)
    s = str(tf).strip().lower()
    if s.endswith("m"):
        return max(1, int(s[:-1] or "1"))
    if s.endswith("h"):
        return max(1, int(s[:-1] or "1") * 60)
    if s.endswith("d"):
        return max(1, int(s[:-1] or "1") * 60 * 24)
    try:
        return max(1, int(s))
    except Exception:
        return 1


def _tf_to_seconds(tf: str) -> int:
    s = str(tf).lower().strip()
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("d"):
        return int(s[:-1]) * 86400
    # число в секундах
    return int(s)


# ──────────────────────────────────────────────────────────────────────────────
# Нормализация рядов / ресемплинг / сейвёр
# ──────────────────────────────────────────────────────────────────────────────
def _norm_row_any(r: Dict[str, Any]) -> Dict[str, float | int]:
    """
    Принимает любой формат свечи:
      {'t':ms,'o','h','l','c','v'}  или  {'ts':sec,'open','high','low','close','volume'}
    Возвращает нормализованный dict:
      {'ts':sec,'o':float,'h':float,'l':float,'c':float,'v':float}
    """
    ts = int(r.get("ts") or r.get("t") or 0)
    if ts > 10_000_000_000:  # миллисекунды → секунды
        ts //= 1000
    o = r.get("o", r.get("open"))
    h = r.get("h", r.get("high"))
    l = r.get("l", r.get("low"))
    c = r.get("c", r.get("close"))
    v = r.get("v", r.get("volume", 0.0))
    return {"ts": ts, "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v)}


def _resample_ohlcv(rows: List[Dict[str, Any]], out_tf: str) -> List[Dict[str, Any]]:
    """Ресемплинг OHLCV до большего ТФ: из 1m → 5m/15m/1h."""
    if not rows:
        return []
    step = _tf_to_seconds(out_tf)
    buckets: Dict[int, Dict[str, Any]] = {}
    for r0 in rows:
        r = _norm_row_any(r0)
        key = (int(r["ts"]) // step) * step
        b = buckets.get(key)
        if not b:
            buckets[key] = {"ts": key, "open": r["o"], "high": r["h"], "low": r["l"], "close": r["c"], "volume": r["v"]}
        else:
            b["high"] = max(b["high"], r["h"])
            b["low"] = min(b["low"], r["l"])
            b["close"] = r["c"]
            b["volume"] = float(b["volume"]) + float(r["v"])
    return [buckets[k] for k in sorted(buckets)]


def _maybe_save_csv(rows: List[Dict[str, Any]], path: Optional[str]) -> None:
    if not path or not rows:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("ts,open,high,low,close,volume\n")
        for r in rows:
            n = _norm_row_any(r)
            f.write(f"{int(n['ts'])},{n['o']},{n['h']},{n['l']},{n['c']},{n['v']}\n")
    print(f"→ CSV saved to: {path}")


# ──────────────────────────────────────────────────────────────────────────────
# Плоттер (OHLC c фоллбеком + объём + маркеры)
# ──────────────────────────────────────────────────────────────────────────────
def _maybe_plot(rows, title, out_path, markers=None, show_vol=True):
    """
    rows: [{'t'| 'ts', 'o'|'open','h'|'high','l'|'low','c'|'close','v'|'volume'} ...]
    markers: [{'ts':sec, 'price':float, 'kind': 'buy'|'sell'|'stop'|'take'}]
    """
    if not out_path or not rows:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        from matplotlib.lines import Line2D
        from statistics import median

        # --- to parsed tuples ---
        def to_dt(ts_sec):  # UTC
            return datetime.fromtimestamp(float(ts_sec), tz=timezone.utc)

        parsed = []
        for r in rows:
            n = _norm_row_any(r)
            parsed.append((n["ts"], n["o"], n["h"], n["l"], n["c"], n["v"]))
        parsed.sort(key=lambda x: x[0])

        # макет
        if show_vol:
            fig, (ax, axv) = plt.subplots(2, 1, sharex=True, figsize=(14, 4.2),
                                          gridspec_kw={"height_ratios": [4, 1]}, constrained_layout=True)
        else:
            fig, ax = plt.subplots(1, 1, figsize=(14, 3.4), constrained_layout=True)
            axv = None

        xs = [mdates.date2num(to_dt(ts)) for (ts, *_ ) in parsed]
        deltas = [xs[i+1] - xs[i] for i in range(len(xs)-1)]
        base_step = (1.0/(24*60)) if not deltas else median(deltas)
        min_w, max_w = 0.20*base_step, 1.50*base_step

        lows  = [l for (_,_,_,l,_,_) in parsed]
        highs = [h for (_,_,h,_,_,_) in parsed]
        y_lo, y_hi = min(lows), max(highs)
        pad = max((y_hi - y_lo)*0.05, 1e-6)

        # grid & x-axis
        ax.grid(True, which="major", linestyle="--", alpha=0.2)
        locator = mdates.AutoDateLocator(minticks=3, maxticks=9)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

        # есть ли полноценный OHLC?
        have_ohlc = all(
            (o is not None and h is not None and l is not None and c is not None)
            for (_, o, h, l, c, _) in parsed
        )

        if have_ohlc:
            for i, (ts, o, h, l, c, v) in enumerate(parsed):
                x = xs[i]
                prev_step = deltas[i-1] if i > 0 else base_step
                next_step = deltas[i] if i < len(xs)-1 else base_step
                w = min(max(0.8 * min(prev_step, next_step), min_w), max_w)
                color = "#2ca02c" if c >= o else "#d62728"
                if h != l:
                    ax.add_line(Line2D([x, x], [l, h], linewidth=1, color=color))
                body_h = abs(c - o)
                if body_h < 1e-12 and h == l:
                    ax.hlines(c, x - w*0.3, x + w*0.3, linewidth=1.6, color=color)
                else:
                    y0 = min(o, c)
                    ax.add_patch(Rectangle((x - w/2, y0), w, max(body_h, 1e-12),
                                           edgecolor=color, facecolor="none", linewidth=1))
            print(f"[plot] OHLC: points={len(parsed)}  first={to_dt(parsed[0][0]).isoformat()}  last={to_dt(parsed[-1][0]).isoformat()}")
        else:
            xs_dt = [to_dt(ts) for (ts, *_ ) in parsed]
            closes = [c for (*_, c, __) in parsed]
            ax.plot(xs_dt, closes, linewidth=1.8)
            y_lo, y_hi = min(closes), max(closes)
            pad = max((y_hi - y_lo) * 0.05, 1e-6)
            ax.set_ylim(y_lo - pad, y_hi + pad)
            print(f"[plot] CLOSE: points={len(xs_dt)}  first={xs_dt[0].isoformat()}  last={xs_dt[-1].isoformat()}")

        ax.set_ylim(y_lo - pad, y_hi + pad)
        ax.set_title(f"EXMO candles {title}")
        ax.set_ylabel("price")

        # markers
        if markers:
            for m in markers:
                ts = int(m["ts"]); px = float(m["price"])
                x = mdates.date2num(to_dt(ts))
                kind = m.get("kind", "")
                if kind == "buy":
                    ax.plot([x], [px], "^", ms=7, mfc="#2ca02c", mec="none", alpha=0.9)
                elif kind == "sell":
                    ax.plot([x], [px], "v", ms=7, mfc="#d62728", mec="none", alpha=0.9)
                elif kind == "stop":
                    ax.plot([x], [px], "x", ms=8, mew=2, color="#d62728", alpha=0.9)
                elif kind == "take":
                    ax.plot([x], [px], "o", ms=6, mfc="none", mec="#2ca02c", mew=1.5, alpha=0.9)

        # volume
        if axv:
            axv.grid(True, which="major", linestyle="--", alpha=0.1)
            axv.set_ylabel("vol")
            axv.bar([to_dt(ts) for (ts, *_ ) in parsed], [v for (*_, v) in parsed],
                    width=0.8*base_step, align="center", alpha=0.35, color="#2ca02c", edgecolor="none")
            axv.xaxis.set_major_locator(locator)
            axv.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
            axv.set_xlabel("time (UTC)")

        import matplotlib.pyplot as plt  # re-import for mypy
        plt.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"→ Chart saved to: {out_path}")
    except Exception as e:
        print(f"⚠️  Не удалось построить график: {e!r}")


# ──────────────────────────────────────────────────────────────────────────────
# EXMO candles_history (fallback нормализация)
# ──────────────────────────────────────────────────────────────────────────────
def _candles_via_history(api: Any, pair: str, tf: str, limit: int) -> List[Dict[str, Any]]:
    """Фоллбэк: строим нормализованные свечи через candles_history."""
    res_min = _tf_to_minutes(tf)
    now = int(time.time())
    frm = now - res_min * 60 * limit
    data = api.candles_history(symbol=pair, resolution=res_min, ts_from=frm, ts_to=now)
    raw = data.get("candles", []) if isinstance(data, dict) else []
    out: List[Dict[str, Any]] = []
    for r in raw:
        try:
            ts = int(int(r.get("t", 0)) // 1000)
            out.append({
                "ts": ts,
                "open": str(r["o"]),
                "high": str(r["h"]),
                "low": str(r["l"]),
                "close": str(r["c"]),
                "volume": str(r.get("v", "")),
            })
        except Exception:
            continue
    return out


def _make_exmo_api() -> ExmoApi:
    """Универсально создаём клиент, независимо от версии конструктора."""
    api_key = os.getenv("EXMO_API_KEY", "")
    api_secret = os.getenv("EXMO_API_SECRET", "")
    # Вариант 1: ExmoApi(api_key=..., api_secret=..., allow_trading=...)
    try:
        return ExmoApi(api_key=api_key, api_secret=api_secret, allow_trading=False)  # type: ignore
    except TypeError:
        pass
    # Вариант 2: ExmoApi(ExmoCredentials(...), allow_trading=...)
    try:
        from src.infrastructure.exchange.exmo_api import ExmoCredentials  # type: ignore
        return ExmoApi(ExmoCredentials(api_key=api_key, api_secret=api_secret), allow_trading=False)  # type: ignore
    except Exception:
        # Фоллбэк — попробуем последний вариант без allow_trading
        try:
            return ExmoApi(api_key=api_key, api_secret=api_secret)  # type: ignore
        except Exception:
            return ExmoApi()  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# Примитивный БТ движок (SMA cross) + сервисные функции для отчётов
# ──────────────────────────────────────────────────────────────────────────────
class _SMA:
    def __init__(self, n: int):
        from collections import deque
        self.n = n
        self.q = deque()
        self.s = 0.0

    def push(self, x: float) -> Optional[float]:
        self.q.append(x); self.s += x
        if len(self.q) > self.n:
            self.s -= self.q.popleft()
        if len(self.q) == self.n:
            return self.s / self.n
        return None


class _SmaCross:
    def __init__(self, fast: int, slow: int):
        assert fast < slow, "fast < slow"
        self.fast = _SMA(fast)
        self.slow = _SMA(slow)
        self.state = None  # 'up'|'down'|None
        self.in_pos = False

    def on_price(self, px: float) -> Optional[str]:
        f = self.fast.push(px)
        s = self.slow.push(px)
        if f is None or s is None:
            return None
        if (not self.in_pos) and f >= s and self.state != "up":
            self.in_pos = True
            self.state = "up"
            return "buy"
        if self.in_pos and f < s and self.state != "down":
            self.in_pos = False
            self.state = "down"
            return "sell"
        return None


def _backtest_sma(
    rows: List[Dict[str, Any]],
    fast: int, slow: int,
    fee_bps: float, slip_bps: float,
    sl_bps: float, tp_bps: float,
    start_eur: float, risk_f: float, qty_eur: float
) -> Tuple[List[Dict[str, Any]], Dict[str, float], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Возвращает (markers, stats, trades, equity_curve).
    trades: [{'ts_in','px_in','budget_eur','qty','ts_out','px_out','kind_out','pnl_eur','ret_bps'}]
    equity_curve: [{'ts','equity','cash','qty','price'}]
    """
    if not rows:
        return [], {}, [], []

    strat = _SmaCross(fast, slow)
    FEE = fee_bps / 1e4
    SLIP = slip_bps / 1e4

    markers: List[Dict[str, Any]] = []
    trades: List[Dict[str, Any]] = []
    equity_curve: List[Dict[str, Any]] = []

    cash = float(start_eur)
    qty = 0.0
    entry_px = None
    entry_ts = None
    entry_budget = 0.0

    def _equity(c_price: float) -> float:
        return cash + qty * c_price

    def _apply_sell(ts: int, px: float, kind: str):
        nonlocal cash, qty, entry_px, entry_ts, entry_budget
        px_exec = px * (1 - SLIP)
        amount = qty * px_exec
        fee = amount * FEE
        cash += (amount - fee)
        pnl_eur = (amount - fee) - entry_budget
        ret_bps = (pnl_eur / entry_budget * 1e4) if entry_budget > 0 else 0.0
        trades.append({
            "ts_in": int(entry_ts), "px_in": float(entry_px), "budget_eur": float(entry_budget), "qty": float(qty),
            "ts_out": int(ts), "px_out": float(px_exec), "kind_out": kind,
            "pnl_eur": float(pnl_eur), "ret_bps": float(ret_bps),
        })
        markers.append({"ts": ts, "price": px_exec, "kind": kind})
        qty = 0.0
        entry_px = None
        entry_ts = None
        entry_budget = 0.0
        strat.in_pos = False

    for r in rows:
        n = _norm_row_any(r)
        ts, c, h, l = n["ts"], n["c"], n["h"], n["l"]

        # SL/TP
        if qty > 0.0 and entry_px is not None:
            if tp_bps > 0 and h >= entry_px * (1 + tp_bps / 1e4):
                _apply_sell(ts, entry_px * (1 + tp_bps / 1e4), "take")
            elif sl_bps > 0 and l <= entry_px * (1 - sl_bps / 1e4):
                _apply_sell(ts, entry_px * (1 - sl_bps / 1e4), "stop")

        sig = strat.on_price(c)
        if sig == "buy" and qty == 0.0:
            px = c * (1 + SLIP)
            budget = qty_eur if risk_f <= 0 else cash * risk_f
            if budget > 0 and cash >= budget:
                fee = budget * FEE
                got = (budget - fee) / px
                qty += got
                cash -= budget
                entry_px = px
                entry_ts = ts
                entry_budget = budget
                markers.append({"ts": ts, "price": px, "kind": "buy"})
        elif sig == "sell" and qty > 0.0:
            _apply_sell(ts, c, "sell")

        equity_curve.append({"ts": int(ts), "equity": _equity(c), "cash": cash, "qty": qty, "price": c})

    equity = equity_curve[-1]["equity"] if equity_curve else start_eur
    stats = {"cash": round(cash, 6), "equity": round(equity, 6)}
    return markers, stats, trades, equity_curve


def _bt_metrics(trades: List[Dict[str, Any]], equity: List[Dict[str, Any]]) -> Dict[str, float]:
    if not equity:
        return {}
    start = equity[0]["equity"]; end = equity[-1]["equity"]
    secs = max(1, int(equity[-1]["ts"]) - int(equity[0]["ts"]))
    sec_year = 365 * 24 * 3600
    cagr = (end / start) ** (sec_year / secs) - 1 if secs > 0 and start > 0 else 0.0

    # баровые доходности для Sharpe
    rets = []
    for i in range(1, len(equity)):
        e0, e1 = equity[i-1]["equity"], equity[i]["equity"]
        if e0 > 0:
            rets.append((e1 - e0) / e0)
    import statistics
    if len(rets) >= 2:
        # оценка периода по медиане расстояний между барами
        dts = [equity[i]["ts"] - equity[i-1]["ts"] for i in range(1, len(equity))]
        bar_sec = max(1, int(statistics.median(dts)))
        periods_per_year = sec_year / bar_sec
        sharpe = (statistics.mean(rets) / (statistics.pstdev(rets) or 1e-12)) * math.sqrt(periods_per_year)
    else:
        sharpe = 0.0

    # max drawdown
    peak = equity[0]["equity"]
    max_dd = 0.0
    for p in equity:
        val = p["equity"]
        peak = max(peak, val)
        dd = (val - peak) / (peak or 1.0)
        max_dd = min(max_dd, dd)
    max_dd_pct = abs(max_dd)

    # по сделкам
    n = len(trades)
    wins = [t for t in trades if t["pnl_eur"] > 0]
    losses = [t for t in trades if t["pnl_eur"] < 0]
    win_rate = (len(wins) / n) if n else 0.0
    sum_win = sum(t["pnl_eur"] for t in wins)
    sum_loss = abs(sum(t["pnl_eur"] for t in losses))
    profit_factor = (sum_win / sum_loss) if sum_loss > 0 else float("inf") if sum_win > 0 else 0.0
    total_pnl = (end - start)

    return {
        "start": float(start), "end": float(end), "total_pnl": float(total_pnl),
        "trades": float(n), "win_rate": float(win_rate),
        "profit_factor": float(profit_factor), "max_drawdown": float(max_dd_pct),
        "sharpe": float(sharpe), "cagr": float(cagr),
    }


def _save_trades_csv(trades: List[Dict[str, Any]], path: Optional[str]) -> None:
    if not path or not trades:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("ts_in,px_in,budget_eur,qty,ts_out,px_out,kind_out,pnl_eur,ret_bps\n")
        for t in trades:
            f.write(f"{t['ts_in']},{t['px_in']},{t['budget_eur']},{t['qty']},{t['ts_out']},{t['px_out']},{t['kind_out']},{t['pnl_eur']},{t['ret_bps']}\n")
    print(f"→ Trades CSV saved to: {path}")


def _save_equity_csv(eq: List[Dict[str, Any]], path: Optional[str]) -> None:
    if not path or not eq:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("ts,equity,cash,qty,price\n")
        for p in eq:
            f.write(f"{p['ts']},{p['equity']},{p['cash']},{p['qty']},{p['price']}\n")
    print(f"→ Equity CSV saved to: {path}")


def _plot_equity(eq: List[Dict[str, Any]], out_path: Optional[str]) -> None:
    if not out_path or not eq:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        xs = [datetime.fromtimestamp(int(p["ts"]), tz=timezone.utc) for p in eq]
        ys = [p["equity"] for p in eq]
        fig, ax = plt.subplots(1, 1, figsize=(12, 3.2), constrained_layout=True)
        ax.plot(xs, ys, linewidth=1.6)
        ax.set_title("Backtest Equity Curve (EUR)")
        ax.set_xlabel("time (UTC)")
        ax.set_ylabel("equity")
        ax.grid(True, linestyle="--", alpha=0.25)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=9))
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
        plt.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"→ Equity chart saved to: {out_path}")
    except Exception as e:
        print(f"⚠️  Не удалось построить график equity: {e!r}")


def _run_backtest_sma(rows: List[Dict[str, Any]], fast: int, slow: int, args, save: bool = False) -> Dict[str, Any]:
    """Обёртка: прогон SMA, расчёт метрик, опц. сохранения файлов. Подходит для оптимизации."""
    markers, stats, trades, eq = _backtest_sma(
        rows, fast, slow,
        fee_bps=float(args.fee_bps), slip_bps=float(args.slip_bps),
        sl_bps=float(args.sl_bps), tp_bps=float(args.tp_bps),
        start_eur=float(args.start_eur), risk_f=float(args.risk_f), qty_eur=float(args.qty_eur),
    )
    metrics = _bt_metrics(trades, eq)

    if save:
        _save_trades_csv(trades, args.save_trades)
        _save_equity_csv(eq, args.save_equity)
        _plot_equity(eq, args.plot_equity)
        if args.save_report:
            os.makedirs(os.path.dirname(args.save_report) or ".", exist_ok=True)
            with open(args.save_report, "w", encoding="utf-8") as f:
                json.dump({"stats": stats, "metrics": metrics}, f, ensure_ascii=False, indent=2)
            print(f"→ Report JSON saved to: {args.save_report}")

    return {"markers": markers, "metrics": metrics, "stats": stats}


def _metric_value(metrics: Dict[str, float], name: str) -> float:
    if name == "sharpe":
        return metrics.get("sharpe", 0.0)
    if name == "pnl":
        return metrics.get("end", 0.0) - metrics.get("start", 0.0)
    if name == "pf":
        return metrics.get("profit_factor", 0.0)
    if name == "dd":
        return -metrics.get("max_drawdown", 0.0)  # меньше — лучше
    if name == "winrate":
        return metrics.get("win_rate", 0.0)
    return 0.0


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="exmo-bot", description="EXMO bot and tools")

    # ===== Старые/базовые аргументы (совместимость) =====
    p.add_argument("--mode", choices=["paper", "live", "hybrid", "legacy"], default="paper")
    p.add_argument("--validate", action="store_true")
    p.add_argument("--exmo-debug", action="store_true")
    p.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    p.add_argument("--pair", default=None)
    p.add_argument("--resolution", type=int, default=1)
    p.add_argument("--from-ts", type=int, default=0)
    p.add_argument("--to-ts", type=int, default=0)

    # ===== Paper-рынок =====
    p.add_argument("--symbol", default=None)
    p.add_argument("--ticks", type=int, default=1)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--start-price", type=str, default="0.1")
    p.add_argument("--drift-bps", type=float, default=0.0)
    p.add_argument("--vol-bps", type=float, default=20.0)
    p.add_argument("--rw-seed", type=int, default=None)
    p.add_argument("--tick-seconds", type=int, default=1)
    p.add_argument("--strategy", choices=["sma", "mr"], default="sma")
    p.add_argument("--tf", default="1m")
    p.add_argument("--fast", type=int, default=10)
    p.add_argument("--slow", type=int, default=30)
    p.add_argument("--min-gap-bps", type=str, default="2")

    # ===== EXMO probe (новые флаги) =====
    ex = p.add_argument_group("EXMO probe (read-only)")
    ex.add_argument("--exmo-pair", type=str, default=None)
    ex.add_argument("--exmo-candles", type=str, default=None, metavar="TF:LIMIT")
    ex.add_argument("--exmo-kline", type=str, default=None, metavar="TF:LIMIT")
    ex.add_argument("--exmo-ohlcv", type=str, default=None, metavar="TF:LIMIT")
    ex.add_argument("--exmo-save-csv", type=str, default=None)
    ex.add_argument("--exmo-plot", type=str, default=None)

    ex.add_argument("--exmo-balances", action="store_true")
    ex.add_argument("--exmo-open-orders", action="store_true")
    ex.add_argument("--exmo-trades", type=int, default=0, metavar="LIMIT")
    ex.add_argument("--exmo-order-book", type=int, default=0, metavar="LIMIT")
    ex.add_argument("--exmo-ticker", action="store_true")
    ex.add_argument("--exmo-ticker-pair", type=str, default=None)

    ex.add_argument("--exmo-user-trades", type=int, default=0, metavar="LIMIT")
    ex.add_argument("--exmo-user-pair", type=str, default=None)
    ex.add_argument("--exmo-since", type=str, default=None)
    ex.add_argument("--exmo-until", type=str, default=None)
    ex.add_argument("--dump-json", type=str, default=None)

    ex.add_argument("--exmo-pnl", action="store_true")
    ex.add_argument("--exmo-user-limit", type=int, default=500)
    ex.add_argument("--exmo-pnl-from", type=str, default=None)
    ex.add_argument("--exmo-pnl-save-csv", type=str, default=None)
    ex.add_argument("--exmo-pnl-plot", type=str, default=None)

    # Ресемплинг/бэктест/отчёты
    ex.add_argument("--resample", type=str, default=None, help="Ресемплинг TF, напр. 5m/15m/1h")
    ex.add_argument("--backtest", action="store_true", help="Запустить бэктест SMA на загруженных свечах")
    ex.add_argument("--fee-bps", type=float, default=10.0)
    ex.add_argument("--slip-bps", type=float, default=0.0)
    ex.add_argument("--sl-bps", type=float, default=0.0)
    ex.add_argument("--tp-bps", type=float, default=0.0)
    ex.add_argument("--start-eur", type=float, default=1000.0)
    ex.add_argument("--risk-f", type=float, default=0.0, help="Доля капитала на сделку (если >0, qty-eur игнорим)")
    ex.add_argument("--qty-eur", type=float, default=0.0, help="Фикс. размер позиции в EUR (если risk-f==0)")
    ex.add_argument("--save-trades", type=str, default=None)
    ex.add_argument("--save-equity", type=str, default=None)
    ex.add_argument("--plot-equity", type=str, default=None)
    ex.add_argument("--save-report", type=str, default=None)

    # Грид-оптимизация SMA
    ex.add_argument("--optimize-sma", type=str, default=None,
                    help='Грид, напр.: "fast=5:60:5,slow=20:240:10"')
    ex.add_argument("--opt-metric", type=str, default="sharpe",
                    choices=["sharpe", "pnl", "pf", "dd", "winrate"])
    ex.add_argument("--opt-top", type=int, default=10)
    ex.add_argument("--opt-plot", type=str, default=None, help="PNG теплокарта fast×slow")

    # Walk-forward
    ex.add_argument("--walkforward", type=int, default=0,
                    help="Кол-во разбиений ряда для WF. 0=выкл")

    return p


# ──────────────────────────────────────────────────────────────────────────────
# Paper-режим
# ──────────────────────────────────────────────────────────────────────────────
def _build_paper_components(args):
    settings = get_settings()
    symbol = args.symbol or settings.default_pair or "DOGE_EUR"
    try:
        base, quote = symbol.split("_", 1)
    except ValueError:
        raise SystemExit("Некорректный --symbol, ожидается BASE_QUOTE, например DOGE_EUR")

    pair = TradingPair(base=base, quote=quote)
    notifier = LogNotifier()
    storage = FileStorage(path=settings.storage_path)

    market = RandomWalkMarket(
        start_price=args.start_price,
        drift_bps=args.drift_bps,
        vol_bps=args.vol_bps,
        seed=args.rw_seede if hasattr(args, "rw_seede") else args.rw_seed,
        tick_seconds=args.tick_seconds,
    )

    ex = PaperExchange.with_quote_funds(
        market=market,
        quote_asset=quote,
        amount=10000,
        spread_bps=10,
        slippage_bps=5,
    )

    if args.strategy == "sma":
        strat = SmaCrossover(cfg=SmaCfg(timeframe=args.tf, fast=args.fast, slow=args.slow, min_gap_bps=args.min_gap_bps))
        candles_tf = args.tf
        lookback = max(args.fast, args.slow) + 2
    else:
        strat = MeanReversion()
        candles_tf = "1m"
        lookback = 60

    risk = RiskService(get_settings().risk)
    positions = PositionService(storage=storage)

    engine = TradeEngine(
        market=market,
        exchange=ex,
        storage=storage,
        notifier=notifier,
        strategy=strat,
        positions=positions,
        risk=risk,
        candles_timeframe=candles_tf,
        candles_lookback=lookback,
    )
    return pair, engine, market, ex


# ──────────────────────────────────────────────────────────────────────────────
# EXMO probe
# ──────────────────────────────────────────────────────────────────────────────
def _run_exmo_probe(args) -> int:
    api = _make_exmo_api()

    # выбор пары
    pair_general = (args.exmo_pair or args.pair or args.symbol or "DOGE_EUR").strip()
    pair_user = (args.exmo_user_pair or pair_general).strip()

    result: Dict[str, Any] = {"pair": pair_general}

    # временные фильтры
    since_ts = _parse_time_hint(args.exmo_since)
    until_ts = _parse_time_hint(args.exmo_until)

    def _filter_time(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if since_ts is None and until_ts is None:
            return rows
        out = []
        for r in rows:
            ts = int(r.get("ts") or r.get("t") or r.get("date") or 0)
            if ts > 10_000_000_000:
                ts //= 1000
            if since_ts is not None and ts < since_ts:
                continue
            if until_ts is not None and ts > until_ts:
                continue
            out.append(r)
        return out

    # базовые публичные
    if args.exmo_ticker:
        result["ticker"] = api.ticker()
    if args.exmo_ticker_pair:
        result["ticker_pair"] = api.ticker_pair(args.exmo_ticker_pair)

    if args.exmo_order_book:
        result["order_book"] = api.order_book(pair_general, limit=int(args.exmo_order_book))

    if args.exmo_trades:
        result["trades"] = api.trades(pair_general, limit=int(args.exmo_trades))

    # свечи/kline/ohlcv (нормализованные dict → CSV/PNG)
    def _candles_like(flag_value: Optional[str], name: str):
        if not flag_value:
            return
        tf, lim = _split_tf_limit(flag_value)

        if name == "ohlcv" and hasattr(api, "ohlcv"):
            rows = api.ohlcv(pair=pair_general, timeframe=tf, limit=lim)  # список списков — оставим как есть
            result[name] = rows
            return

        if hasattr(api, "candles"):
            rows = api.candles(pair=pair_general, timeframe=tf, limit=lim)  # список dict
        else:
            rows = _candles_via_history(api, pair_general, tf, lim)

        rows = _filter_time(rows)

        # --- ресемплинг, если просили ---
        tf_label = tf
        if args.resample:
            rows = _resample_ohlcv(rows, args.resample)
            tf_label = args.resample

        # --- бэктест SMA (маркеры/сделки/метрики) ---
        plot_markers = None
        if args.backtest:
            bt = _run_backtest_sma(rows, int(args.fast), int(args.slow), args, save=True)
            m = bt["metrics"]
            print(f"[bt] equity={bt['stats'].get('equity')}  trades={int(m.get('trades',0))} "
                  f"win_rate={m.get('win_rate',0):.2%}  pf={m.get('profit_factor',0):.2f}  "
                  f"dd={m.get('max_drawdown',0):.2%}  sharpe={m.get('sharpe',0):.2f}")
            plot_markers = bt.get("markers")

        result[name] = rows
        _maybe_save_csv(rows, args.exmo_save_csv if name != "ohlcv" else None)
        _maybe_plot(rows, f"{pair_general} {tf_label}", args.exmo_plot if name != "ohlcv" else None,
                    markers=plot_markers, show_vol=True)

    _candles_like(args.exmo_candles, "candles")
    _candles_like(args.exmo_kline, "kline")
    _candles_like(args.exmo_ohlcv, "ohlcv")

    # Если просили оптимизацию / WF — используем последнюю загруженную сводку свечей
    base_rows = result.get("candles") or result.get("kline")
    if base_rows:
        # нормализуем ключи (на случай "o/h/l/c/v"):
        norm = []
        for r in base_rows:
            norm.append({
                "ts": int(r.get("ts") or r.get("t") or 0) if int(r.get("ts") or r.get("t") or 0) < 10_000_000_000 else int(r.get("ts") or r.get("t"))//1000,
                "open": float(r.get("open", r.get("o"))),
                "high": float(r.get("high", r.get("h"))),
                "low":  float(r.get("low",  r.get("l"))),
                "close":float(r.get("close", r.get("c"))),
                "volume":float(r.get("volume", r.get("v", 0.0))),
            })
        norm.sort(key=lambda x: x["ts"])
        rows_rs = _resample_ohlcv(norm, args.resample) if args.resample else norm

        # ── Грид-оптимизация SMA
        if args.optimize_sma:
            (fmin, fmax, fstep), (smin, smax, sstep) = _parse_grid(args.optimize_sma)
            best = []
            heat = {}

            for fast in range(fmin, fmax + 1, fstep):
                for slow in range(smin, smax + 1, sstep):
                    if fast >= slow:
                        continue
                    st = _run_backtest_sma(rows_rs, fast, slow, args, save=False)
                    score = _metric_value(st["metrics"], args.opt_metric)
                    best.append((score, fast, slow, st))
                    heat[(fast, slow)] = score

            best.sort(reverse=True, key=lambda x: x[0])
            top = best[:max(1, args.opt_top)]

            print("[opt] top by", args.opt_metric)
            for i, (score, f, s, st) in enumerate(top, 1):
                m = st["metrics"]
                print(f"  {i:>2}. fast={f:>3} slow={s:>3}  score={score:.4f}  "
                      f"pnl={m['end']-m['start']:.4f}  sharpe={m.get('sharpe',0):.2f}  dd={m.get('max_drawdown',0):.3%}")

            # JSON отчёт для оптимизации
            if args.save_report:
                out = {
                    "grid": {"fast": [fmin, fmax, fstep], "slow": [smin, smax, sstep]},
                    "metric": args.opt_metric,
                    "top": [{
                        "fast": f, "slow": s, "score": sc, "metrics": st["metrics"]
                    } for (sc, f, s, st) in top]
                }
                os.makedirs(os.path.dirname(args.save_report) or ".", exist_ok=True)
                with open(args.save_report, "w", encoding="utf-8") as f:
                    json.dump(out, f, ensure_ascii=False, indent=2)
                print(f"→ Report JSON saved to: {args.save_report}")

            # теплокарта
            if args.opt_plot:
                try:
                    import matplotlib
                    matplotlib.use("Agg")
                    import matplotlib.pyplot as plt
                    import numpy as np
                    fvals = list(range(fmin, fmax + 1, fstep))
                    svals = list(range(smin, smax + 1, sstep))
                    Z = np.full((len(fvals), len(svals)), np.nan)
                    for i, fv in enumerate(fvals):
                        for j, sv in enumerate(svals):
                            if (fv, sv) in heat:
                                Z[i, j] = heat[(fv, sv)]
                    fig, ax = plt.subplots(1, 1, figsize=(10, 4))
                    im = ax.imshow(Z, aspect="auto", origin="lower",
                                   extent=[smin, smax, fmin, fmax])
                    ax.set_xlabel("slow"); ax.set_ylabel("fast")
                    ax.set_title(f"Optimization heatmap ({args.opt_metric})")
                    fig.colorbar(im, ax=ax)
                    plt.tight_layout(); plt.savefig(args.opt_plot, dpi=150); plt.close(fig)
                    print(f"→ Opt heatmap saved to: {args.opt_plot}")
                except Exception as e:
                    print(f"⚠️  Не удалось построить теплокарту: {e!r}")

            # Если одновременно дали --exmo-plot — дорисуем бары с лучшими маркерами
            if args.exmo_plot and top:
                _, f_best, s_best, st = top[0]
                _maybe_plot(rows_rs, f"{pair_general} {args.resample or ''}".strip(),
                            args.exmo_plot, markers=st.get("markers", []), show_vol=True)

        # ── Walk-Forward поверх оптимизации
        if args.walkforward and args.optimize_sma:
            k = max(2, int(args.walkforward))
            n = len(rows_rs); seg = n // k
            wf_rows = [rows_rs[i * seg:(i + 1) * seg] for i in range(k - 1)] + [rows_rs[(k - 1) * seg:]]
            wf_out = []
            (fmin, fmax, fstep), (smin, smax, sstep) = _parse_grid(args.optimize_sma)
            for idx, chunk in enumerate(wf_rows, 1):
                if len(chunk) < 40:
                    continue
                mid = len(chunk) // 2
                train, test = chunk[:mid], chunk[mid:]
                best = None; best_score = -1e9
                for fast in range(fmin, fmax + 1, fstep):
                    for slow in range(smin, smax + 1, sstep):
                        if fast >= slow:
                            continue
                        st_tr = _run_backtest_sma(train, fast, slow, args, save=False)
                        sc = _metric_value(st_tr["metrics"], args.opt_metric)
                        if sc > best_score:
                            best_score, best = sc, (fast, slow)
                fast, slow = best
                st_te = _run_backtest_sma(test, fast, slow, args, save=False)
                wf_out.append({"seg": idx, "fast": fast, "slow": slow, "metrics": st_te["metrics"]})

            print("[wf] segments:", len(wf_out))
            for w in wf_out:
                m = w["metrics"]
                print(f"  seg={w['seg']}  fast={w['fast']} slow={w['slow']}  "
                      f"pnl={m['end']-m['start']:.4f} sharpe={m.get('sharpe',0):.2f} dd={m.get('max_drawdown',0):.3%}")

            if args.save_report:
                with open(args.save_report, "w", encoding="utf-8") as f:
                    json.dump({"walkforward": wf_out}, f, ensure_ascii=False, indent=2)
                print(f"→ Report JSON saved to: {args.save_report}")

    # приватка
    if args.exmo_balances:
        result["balances"] = api.user_balances()

    if args.exmo_open_orders:
        result["open_orders"] = api.user_open_orders(pair_user)

    if args.exmo_user_trades:
        result["user_trades"] = api.user_trades(pair_user, limit=int(args.exmo_user_trades))

    # PnL — подготовим входные данные (расчёт можешь делать своим модулем)
    if args.exmo_pnl:
        trades = result.get("user_trades") or api.user_trades(pair_user, limit=int(args.exmo_user_limit))
        result["pnl_source_trades"] = len(trades or [])

    # дамп результата
    if args.dump_json:
        os.makedirs(os.path.dirname(args.dump_json) or ".", exist_ok=True)
        with open(args.dump_json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"→ JSON saved to: {args.dump_json}")

    # краткий вывод
    if "candles" in result:
        print(f"EXMO candles[{pair_general}] rows={len(result['candles'])}")
    if "balances" in result:
        print("EXMO balances loaded")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Точка входа
# ──────────────────────────────────────────────────────────────────────────────
def run_cli() -> None:
    # логи: по умолчанию INFO, сторонние либы — WARNING
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for noisy in ["matplotlib", "PIL", "urllib3", "fontTools", "requests"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    args = _build_parser().parse_args()

    # Включаем подробный дебаг только для нашего EXMO-клиента при флаге/переменной
    if os.getenv("EXMO_DEBUG") or "--exmo-debug" in os.sys.argv:
        logging.getLogger("src.infrastructure.exchange.exmo_api").setLevel(logging.DEBUG)

    # Ветка EXMO probe (новые флаги)
    if any([
        args.exmo_candles, args.exmo_kline, args.exmo_ohlcv, args.exmo_balances,
        args.exmo_open_orders, args.exmo_trades, args.exmo_order_book,
        args.exmo_ticker, args.exmo_ticker_pair, args.exmo_user_trades, args.exmo_pnl
    ]) or args.backtest or args.optimize_sma or args.walkforward:
        raise SystemExit(_run_exmo_probe(args))

    # Совместимость со «старым» режимом запроса свечей по from/to
    if args.pair and args.from_ts and args.to_ts:
        api = _make_exmo_api()
        res = args.resolution or 1
        data = api.candles_history(
            symbol=args.pair,
            resolution=int(res),
            ts_from=int(args.from_ts),
            ts_to=int(args.to_ts),
        )
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return

    # Иначе — paper-режим (симуляция)
    if args.mode != "paper":
        raise SystemExit("Пока доступен только --mode paper")

    if args.validate:
        s = get_settings()
        print("✅ Validation OK")
        print(f"  Default pair: {s.default_pair}")
        return

    pair, engine, market, ex = _build_paper_components(args)

    ticks = max(1, int(args.ticks))
    interval = max(0.0, float(args.interval))
    try:
        for i in range(ticks):
            market.tick(1)
            engine.run_tick(pair)

            if (i + 1) % 5 == 0 or i == ticks - 1:
                snap = ex.snapshot()
                print(f"[tick {i+1}/{ticks}] balances={snap['balances']} last_fills={len(snap['fills'])}")

            if i != ticks - 1 and interval > 0:
                time.sleep(interval)
    except KeyboardInterrupt:
        print("\n⏹️  Остановлено пользователем")
