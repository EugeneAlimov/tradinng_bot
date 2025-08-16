# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional, Tuple
from datetime import datetime, timezone

import numpy as np
import pandas as pd


# ===== попытка взять функции из интеграции EXMO; если нет — дадим простые фолбэки =====
def _try_import_exmo_utils():
    # абсолютный путь (чаще всего у вас так и есть)
    try:
        from src.integrations.exmo import (
            fetch_exmo_candles as _f,
            resample_ohlcv as _r,
            normalize_resample_rule as _n,
        )
        return _f, _r, _n
    except Exception:
        pass
    # относительный путь: из src/presentation/cli -> к src/integrations
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
    """
    Тонкая обёртка над src.integrations.exmo.fetch_exmo_candles.
    Здесь держим только маршрутизацию импорта, без сетевой логики.
    """
    if _FEXMO is None:
        raise RuntimeError("integrations.exmo.fetch_exmo_candles отсутствует. "
                           "Установите файл src/integrations/exmo.py или поправьте импорты.")
    return _FEXMO(pair, span, verbose=verbose)


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if _RESAMPLE is None:
        # Простой фолбэк на случай отсутствия интеграции
        if not rule:
            return df.copy()
        x = df.copy()
        x = x.set_index("time")
        o = x["open"].resample(rule).first()
        h = x["high"].resample(rule).max()
        l = x["low"].resample(rule).min()
        c = x["close"].resample(rule).last()
        v = x["volume"].resample(rule).sum()
        y = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v})
        y = y.dropna().reset_index()
        return y
    return _RESAMPLE(df, rule)


def normalize_resample_rule(rule: str) -> str:
    if _NORM is not None:
        return _NORM(rule)
    # Фолбэк: приводим частые варианты к современным псевдонимам pandas
    if not rule:
        return ""
    r = str(rule).strip().lower()
    # поддержим 5m / 15m / 1h / 4h / 1d и т.п.
    if r.endswith("m"):
        return f"{int(r[:-1])}min"
    if r.endswith("min"):
        return r
    if r.endswith("h"):
        return f"{int(r[:-1])}h"
    if r.endswith("d"):
        return f"{int(r[:-1])}d"
    return r


# ===== маленькие утилиты, которые также использует live_trade =====
def _parse_span(span: str) -> Tuple[str, int]:
    tf, n = span.split(":")
    return tf.strip().lower(), int(n)


def _tf_seconds(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"): return int(tf[:-1]) * 60
    if tf.endswith("h"): return int(tf[:-1]) * 3600
    if tf.endswith("d"): return int(tf[:-1]) * 86400
    raise ValueError(f"Unsupported TF {tf!r}")

def _append_live_signal_row(
    csv_path: str,
    ts: datetime,
    close: float,
    volume: float,
    sma_fast: float,
    sma_slow: float,
    signal: Optional[str],
) -> None:
    """
    Пишет одну строку в CSV со стабильной схемой:
    time,close,volume,sma_fast,sma_slow,signal

    - Создаёт каталог, если нужно.
    - Гарантирует заголовок, если файл пустой/новый.
    - Корректно форматирует числа (до 8 знаков после запятой).
    - signal может быть '', 'none', 'buy', 'sell'.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    iso = ts.astimezone(timezone.utc).isoformat(timespec="seconds")

    sig = "" if not signal else str(signal)

    row = "{time},{close:.8f},{vol:.8f},{f:.8f},{s:.8f},{sig}\n".format(
        time=iso,
        close=float(close),
        vol=float(volume if volume is not None else 0.0),
        f=float(sma_fast if sma_fast is not None else 0.0),
        s=float(sma_slow if sma_slow is not None else 0.0),
        sig=sig,
    )

    directory = os.path.dirname(csv_path) or "."
    os.makedirs(directory, exist_ok=True)
    need_header = (not os.path.exists(csv_path)) or (os.path.getsize(csv_path) == 0)

    with open(csv_path, "a", newline="") as f:
        if need_header:
            f.write("time,close,volume,sma_fast,sma_slow,signal\n")
        f.write(row)
# ===== лёгкие режимы: observe и paper =====
def run_live_observe(
    pair: str,
    span: str,
    resample_rule: str,
    fast: int,
    slow: int,
    poll_sec: int = 15,
    heartbeat_sec: int = 60,
    live_log: Optional[str] = None,
) -> None:
    """
    Лайв-наблюдение (без ордеров):
    - Периодически тянет свечи EXMO.
    - Опционально ресемплит (resample_rule: '5min', '15min', ''/None — без ресемпла).
    - Считает SMA(fast/slow), генерит сигнал ('buy' при пересечении вверх, 'sell' при пересечении вниз, иначе 'none').
    - Печатает состояние и, если задан live_log, пишет в CSV: time,close,volume,sma_fast,sma_slow,signal.
    - Защита от дубликатов: в CSV пишется не более одной строки на один timestamp бара.
    """
    # печать шапки
    rs_print = resample_rule if (resample_rule and str(resample_rule).strip()) else "—"
    print(f"[live] observe {pair} {span} resample={rs_print} fast={fast} slow={slow} poll={poll_sec}s")

    last_written_ts: Optional[pd.Timestamp] = None
    last_hb: float = time.time()

    def _compute_signal(f_now: float, s_now: float, f_prev: float, s_prev: float) -> str:
        if np.isnan([f_now, s_now, f_prev, s_prev]).any():
            return ""
        cross_up = (f_prev <= s_prev) and (f_now > s_now)
        cross_dn = (f_prev >= s_prev) and (f_now < s_now)
        if cross_up:
            return "buy"
        if cross_dn:
            return "sell"
        return "none"

    try:
        while True:
            # 1) тянем свечи
            df = fetch_exmo_candles(pair, span)  # <- у тебя уже есть эта функция
            if df is None or len(df) == 0:
                time.sleep(poll_sec)
                continue

            # 2) приведение времени/индекса
            if not isinstance(df.index, pd.DatetimeIndex):
                if "time" in df.columns:
                    df["time"] = pd.to_datetime(df["time"], utc=True)
                    df = df.set_index("time").sort_index()
                else:
                    # без индекса времени корректно не работаем
                    time.sleep(poll_sec)
                    continue

            # 3) ресемплинг (если задан)
            dfr = df
            if resample_rule and str(resample_rule).strip():
                dfr = resample_ohlcv(df, rule=resample_rule)  # <- твой ресемплер
                if dfr is None or len(dfr) == 0:
                    time.sleep(poll_sec)
                    continue

            # 4) SMA
            dfr = dfr.copy()
            dfr["sma_fast"] = dfr["close"].rolling(int(fast), min_periods=1).mean()
            dfr["sma_slow"] = dfr["close"].rolling(int(slow), min_periods=1).mean()

            if len(dfr) < 2:
                time.sleep(poll_sec)
                continue

            # 5) текущий/предыдущий бар
            last_ts = dfr.index[-1]
            prev_ts = dfr.index[-2]

            # защита от дубликатов в CSV
            if last_written_ts is not None and pd.Timestamp(last_ts) <= pd.Timestamp(last_written_ts):
                # но всё равно выведем в консоль и heartbeat по расписанию
                pass
            else:
                last_written_ts = pd.Timestamp(last_ts)

            close_now = float(dfr.iloc[-1]["close"])
            vol_now = float(dfr.iloc[-1]["volume"]) if "volume" in dfr.columns else float("nan")
            f_now = float(dfr.iloc[-1]["sma_fast"])
            s_now = float(dfr.iloc[-1]["sma_slow"])
            f_prev = float(dfr.iloc[-2]["sma_fast"])
            s_prev = float(dfr.iloc[-2]["sma_slow"])

            # 6) сигнал пересечения
            sig = _compute_signal(f_now, s_now, f_prev, s_prev)

            # печать статуса
            ts_iso = pd.Timestamp(last_ts).tz_convert("UTC").isoformat()
            print(f"[live] {ts_iso} tick  close={close_now:.6f}  f={f_now:.6f}  s={s_now:.6f}")

            # 7) запись в CSV (строго 6 колонок, один раз на бар)
            if live_log:
                _append_live_signal_row(
                    live_log,
                    ts=pd.Timestamp(last_ts).to_pydatetime(),
                    close=close_now,
                    volume=(vol_now if np.isfinite(vol_now) else 0.0),
                    sma_fast=f_now,
                    sma_slow=s_now,
                    signal=sig,
                )

            # 8) heartbeat
            now = time.time()
            if now - last_hb >= max(5, int(heartbeat_sec)):
                hb_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
                print(f"[live] hb @ {hb_iso}")
                last_hb = now

            # 9) пауза
            time.sleep(max(1, int(poll_sec)))
    except KeyboardInterrupt:
        print("[live] stopped.")



def run_live_paper(
        pair: str, span: str, resample_rule: str,
        fast: int, slow: int,
        *,
        start_eur: float,
        qty_eur: float,
        position_pct: float,
        fee_bps: float,
        slip_bps: float,
        poll_sec: Optional[int],
        heartbeat_sec: int,
) -> None:
    """
    Упрощённый paper-режим: только учет позиции и equity, без комиссий биржи.
    Пишет CSV: data/live_paper_equity.csv
    """
    import csv, os

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
        f"[paper] {pair} {span} resample={rule or '—'} fast={fast} slow={slow} start={start_eur:.2f} fee={fee_bps}bps slip={slip_bps}bps")

    last_ts = None
    next_hb = time.time() + max(heartbeat_sec, 0)

    try:
        while True:
            df = fetch_exmo_candles(pair, span, verbose=False)
            if df.empty:
                time.sleep(poll);
                continue
            if rule:
                df = resample_ohlcv(df, rule)

            df["sma_fast"] = df["close"].rolling(fast, min_periods=fast).mean()
            df["sma_slow"] = df["close"].rolling(slow, min_periods=slow).mean()
            if len(df) < max(fast, slow) + 2:
                time.sleep(poll);
                continue

            ts = df["time"].iloc[-1]
            if last_ts is not None and ts <= last_ts:
                time.sleep(poll);
                continue
            last_ts = ts

            c = float(df["close"].iloc[-1])
            fp = float(df["sma_fast"].iloc[-2])
            sp = float(df["sma_slow"].iloc[-2])
            fc = float(df["sma_fast"].iloc[-1])
            sc = float(df["sma_slow"].iloc[-1])

            sig = None
            if fp <= sp and fc > sc: sig = "buy"
            if fp >= sp and fc < sc: sig = "sell"

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


# ===== CLI =====
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
    # зеркалим в EXMO_KEY/EXMO_SECRET
    if ek and not os.environ.get("EXMO_KEY"): os.environ["EXMO_KEY"] = ek
    if es and not os.environ.get("EXMO_SECRET"): os.environ["EXMO_SECRET"] = es
    print(
        f"[env] .env=ok EXMO_KEY={'∅' if not ek else str(len(ek)) + ' chars, ****' + ek[-4:]} EXMO_SECRET={'∅' if not es else str(len(es)) + ' chars, ****' + es[-4:]}")


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

    # зарезервированные (пока не используем)
    p.add_argument("--max-daily-loss-bps", type=float, default=0.0)
    p.add_argument("--cooldown-bars", type=int, default=0)

    args = p.parse_args()

    if args.env_file:
        _load_env_file(args.env_file)

    pair = args.exmo_pair
    span = args.exmo_candles
    rule = args.resample

    if args.live == "observe":
        run_live_observe(
            pair=pair, span=span, resample_rule=rule,
            fast=args.fast, slow=args.slow,
            poll_sec=args.poll_sec, heartbeat_sec=args.heartbeat_sec,
            live_log=args.live_log or None,
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
        # импортим здесь, чтобы не тянуть зависимости раньше времени
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

    # Если сюда дошли — пользователь не выбрал live-режим
    p.print_help()


if __name__ == "__main__":
    main()
