# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import time
from typing import Tuple, Optional

import pandas as pd


# ===== интеграции EXMO: аккуратные обёртки и фолбэки =====
def _try_import_exmo_utils():
    """
    Пытаемся импортировать из src.integrations.exmo. Если модуль отсутствует,
    часть логики заменяем простыми фолбэками (ресемплинг).
    """
    try:
        from src.integrations.exmo import (
            fetch_exmo_candles as _f,
            resample_ohlcv as _r,
            normalize_resample_rule as _n,
        )
        return _f, _r, _n
    except Exception:
        pass
    try:
        from ...integrations.exmo import (
            fetch_exmo_candles as _f,
            resample_ohlcv as _r,
            normalize_resample_rule as _n,
        )
        return _f, _r, _n
    except Exception:
        return None, None, None


_FEXMO, _RESAMPLE, _NORM = _try_import_exmo_utils()


def fetch_exmo_candles(pair: str, span: str, verbose: bool = False) -> pd.DataFrame:
    if _FEXMO is None:
        raise RuntimeError(
            "integrations.exmo.fetch_exmo_candles отсутствует. "
            "Добавьте src/integrations/exmo.py или поправьте импорты."
        )
    return _FEXMO(pair, span, verbose=verbose)


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if not rule:
        return df.copy()
    if _RESAMPLE is not None:
        return _RESAMPLE(df, rule)
    # Фолбэк-ресемплер
    x = df.copy()
    if "time" in x.columns:
        x["time"] = pd.to_datetime(x["time"], utc=True, errors="coerce")
        x = x.set_index("time")
    if not isinstance(x.index, pd.DatetimeIndex):
        raise ValueError("DataFrame должен содержать DatetimeIndex или колонку 'time'.")
    o = x["open"].resample(rule).first()
    h = x["high"].resample(rule).max()
    l = x["low"].resample(rule).min()
    c = x["close"].resample(rule).last()
    v = x["volume"].resample(rule).sum() if "volume" in x.columns else None
    y = {"open": o, "high": h, "low": l, "close": c}
    if v is not None:
        y["volume"] = v
    out = pd.DataFrame(y).dropna()
    out = out.reset_index()
    return out


def normalize_resample_rule(rule: str) -> str:
    if _NORM is not None:
        return _NORM(rule)
    if not rule:
        return ""
    r = str(rule).strip().lower()
    if r.endswith("m"):
        return f"{int(r[:-1])}min"
    if r.endswith("min"):
        return r
    if r.endswith("h"):
        return f"{int(r[:-1])}h"
    if r.endswith("d"):
        return f"{int(r[:-1])}d"
    return r


# ===== утилиты времени/TF =====
def _parse_span(span: str) -> Tuple[str, int]:
    tf, n = span.split(":")
    return tf.strip().lower(), int(n)


def _tf_seconds(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    if tf.endswith("h"):
        return int(tf[:-1]) * 3600
    if tf.endswith("d"):
        return int(tf[:-1]) * 86400
    raise ValueError(f"Unsupported TF {tf!r}")


# ===== paper-режим (оставляем тут; не зависит от приватного API) =====
def run_live_paper(
        pair: str,
        span: str,
        resample_rule: str,
        fast: int,
        slow: int,
        *,
        start_eur: float,
        qty_eur: float,
        position_pct: float,
        fee_bps: float,
        slip_bps: float,
        poll_sec: Optional[int],
        heartbeat_sec: int,
) -> None:
    import csv

    tf, _ = _parse_span(span)
    tf_sec = _tf_seconds(tf)
    poll = int(poll_sec or max(5, tf_sec // 2))
    rule = normalize_resample_rule(resample_rule) if resample_rule else ""

    equity_csv = "data/live_paper_equity.csv"
    os.makedirs("data", exist_ok=True)

    def _append_csv(path: str, row: dict) -> None:
        write_header = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if write_header:
                w.writeheader()
            w.writerow(row)

    pos_qty = 0.0
    cash_eur = float(start_eur)
    avg_price = 0.0

    print(
        f"[paper] {pair} {span} resample={rule or '—'} fast={fast} slow={slow} start={start_eur:.2f} fee={fee_bps}bps slip={slip_bps}bps"
    )

    last_ts = None
    next_hb = time.time() + max(heartbeat_sec, 0)

    try:
        while True:
            df = fetch_exmo_candles(pair, span, verbose=False)
            if df.empty:
                time.sleep(poll)
                continue
            if rule:
                df = resample_ohlcv(df, rule)

            df["sma_fast"] = df["close"].rolling(fast, min_periods=fast).mean()
            df["sma_slow"] = df["close"].rolling(slow, min_periods=slow).mean()
            if len(df) < max(fast, slow) + 2:
                time.sleep(poll)
                continue

            ts = df["time"].iloc[-1]
            if last_ts is not None and ts <= last_ts:
                time.sleep(poll)
                continue
            last_ts = ts

            c = float(df["close"].iloc[-1])
            fp = float(df["sma_fast"].iloc[-2])
            sp = float(df["sma_slow"].iloc[-2])
            fc = float(df["sma_fast"].iloc[-1])
            sc = float(df["sma_slow"].iloc[-1])

            sig = None
            if fp <= sp and fc > sc:
                sig = "buy"
            if fp >= sp and fc < sc:
                sig = "sell"

            if sig == "buy":
                equity_now = cash_eur + pos_qty * c
                use = qty_eur if qty_eur > 0 else (equity_now * max(0.0, position_pct) / 100.0)
                if use > 0:
                    buy_qty = use / c
                    avg_price = (pos_qty * avg_price + buy_qty * c) / max(pos_qty + buy_qty, 1e-9)
                    pos_qty += buy_qty
                    cash_eur -= buy_qty * c

            elif sig == "sell" and pos_qty > 0:
                sell_qty = pos_qty
                cash_eur += sell_qty * c
                pos_qty = 0.0
                avg_price = 0.0

            equity = cash_eur + pos_qty * c
            print(f"[paper] {ts.isoformat()} tick equity={equity:.2f} pos={pos_qty:.6f}")
            _append_csv(equity_csv, {"time": ts.isoformat(), "equity": equity})

            if heartbeat_sec > 0 and time.time() >= next_hb:
                print(f"[paper] {ts.isoformat()} hb equity={equity:.2f} pos={pos_qty:.6f}")
                next_hb = time.time() + heartbeat_sec

            time.sleep(poll)
    except KeyboardInterrupt:
        print("[paper] stopped.")


# ===== загрузка .env =====
def _load_env_file(path: str) -> None:
    if not path:
        return
    if not os.path.exists(path):
        print(f"[env] warning: file not found: {path}")
        return
    loaded = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            os.environ[k.strip()] = v
            loaded[k.strip()] = v
    ek = os.environ.get("EXMO_API_KEY") or os.environ.get("EXMO_KEY") or ""
    es = os.environ.get("EXMO_API_SECRET") or os.environ.get("EXMO_SECRET") or ""
    if ek and not os.environ.get("EXMO_KEY"):
        os.environ["EXMO_KEY"] = ek
    if es and not os.environ.get("EXMO_SECRET"):
        os.environ["EXMO_SECRET"] = es
    print(
        f"[env] .env=ok EXMO_KEY={'∅' if not ek else str(len(ek)) + ' chars, ****' + ek[-4:]} EXMO_SECRET={'∅' if not es else str(len(es)) + ' chars, ****' + es[-4:]}"
    )


# ===== CLI =====
def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--env-file", default="", help=".env с EXMO_KEY/EXMO_SECRET (или EXMO_API_KEY/EXMO_API_SECRET).")
    p.add_argument("--exmo-pair", default="DOGE_EUR")
    p.add_argument("--exmo-candles", default="1m:600", help="TF:count, напр. 1m:600")
    p.add_argument("--resample", default="", help="пример: 5m / 15m / 1h")
    p.add_argument("--fast", type=int, default=6)
    p.add_argument("--slow", type=int, default=25)

    # общие риск/объём параметры
    p.add_argument("--start-eur", type=float, default=1000.0)
    p.add_argument("--qty-eur", type=float, default=0.0)
    p.add_argument("--position-pct", type=float, default=0.0)
    p.add_argument("--fee-bps", type=float, default=10.0)
    p.add_argument("--slip-bps", type=float, default=2.0)
    p.add_argument("--price-tick", type=float, default=0.0)
    p.add_argument("--qty-step", type=float, default=0.0)
    p.add_argument("--min-quote", type=float, default=0.0)

    # live режимы
    p.add_argument("--live", choices=["observe", "paper", "trade"], default="")
    p.add_argument("--poll-sec", type=int, default=15)
    p.add_argument("--heartbeat-sec", type=int, default=60)
    p.add_argument("--live-log", default="", help="CSV для observe-логов (опционально)")
    p.add_argument(
        "--closed-only-log", action="store_true",
        help="Log/print only CLOSED bars in live observe (no intra-bar updates).")
    p.add_argument("--hysteresis-bps", type=float, default=0.0,
                   help="Минимальная разница между SMA-fast и SMA-slow в б.п. цены для генерации сигнала (0 = без фильтра).")

    # поведение live-trade
    p.add_argument("--confirm-live-trade", action="store_true")
    p.add_argument("--align-on-state", action="store_true")
    p.add_argument("--enter-on-start", action="store_true")
    p.add_argument("--fok-wait-sec", type=float, default=3.0)
    p.add_argument("--reprice-attempts", type=int, default=0)
    p.add_argument("--reprice-step-bps", type=float, default=5.0)
    p.add_argument("--aggr-limit", action="store_true",
                   help="Peg limit to best ask/bid (uses order_book) for immediate fills.")
    p.add_argument("--aggr-ticks", type=int, default=1)
    p.add_argument("--force-entry", choices=["", "buy", "sell"], default="",
                   help="Одноразовый вход/выход поверх сигналов (для теста связи).")

    # зарезервированные (пока не используем в логике, но оставляем в сигнатуре trade)
    p.add_argument("--max-daily-loss-bps", type=float, default=0.0)
    p.add_argument("--cooldown-bars", type=int, default=0)

    args = p.parse_args()

    if args.env_file:
        _load_env_file(args.env_file)

    pair = args.exmo_pair
    span = args.exmo_candles
    rule = args.resample

    if args.live == "observe":
        from ..live import run_live_observe
        run_live_observe(
            pair=pair, span=span, resample_rule=rule,
            fast=args.fast, slow=args.slow,
            poll_sec=args.poll_sec, heartbeat_sec=args.heartbeat_sec,
            live_log=args.live_log or None,
            hysteresis_bps=args.hysteresis_bps,
        )
        return

    if args.live == "paper":
        run_live_paper(
            pair=pair, span=span, resample_rule=rule,
            fast=args.fast, slow=args.slow,
            start_eur=args.start_eur, qty_eur=args.qty_eur, position_pct=args.position_pct,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps,
            poll_sec=args.poll_sec, heartbeat_sec=args.heartbeat_sec,
        )
        return

    if args.live == "trade":
        from ..live_trade import run_live_trade
        run_live_trade(
            pair=pair, span=span, resample_rule=rule,
            fast=args.fast, slow=args.slow,
            start_eur=args.start_eur, qty_eur=args.qty_eur, position_pct=args.position_pct,
            fee_bps=args.fee_bps, slip_bps=args.slip_bps,
            price_tick=args.price_tick, qty_step=args.qty_step, min_quote=args.min_quote,
            poll_sec=args.poll_sec, heartbeat_sec=args.heartbeat_sec,
            max_daily_loss_bps=args.max_daily_loss_bps, cooldown_bars=args.cooldown_bars,
            confirm_live_trade=args.confirm_live_trade,
            align_on_state=args.align_on_state, enter_on_start=args.enter_on_start,
            fok_wait_sec=args.fok_wait_sec,
            reprice_attempts=args.reprice_attempts, reprice_step_bps=args.reprice_step_bps,
            aggr_limit=args.aggr_limit, aggr_ticks=args.aggr_ticks,
            force_entry=args.force_entry,
        )
        return

    p.print_help()


if __name__ == "__main__":
    main()
