# -*- coding: utf-8 -*-
from __future__ import annotations
import csv, os, time
from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd

try:
    # пакетный запуск
    from ..integrations.exmo import fetch_exmo_candles, resample_ohlcv, normalize_resample_rule
except Exception:
    # запуск из корня
    from src.integrations.exmo import fetch_exmo_candles, resample_ohlcv, normalize_resample_rule


@dataclass
class BrokerState:
    cash_eur: float
    pos_qty: float = 0.0  # количество монет
    last_equity: float = 0.0  # для удобства логирования
    day_start_equity: float = 0.0
    cooldown_left: int = 0  # бары до конца «перерыва» после max daily loss


def _parse_span(span: str) -> Tuple[str, int]:
    tf, n = span.split(":")
    return tf.strip().lower(), int(n)


def _tf_seconds(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"): return int(tf[:-1]) * 60
    if tf.endswith("h"): return int(tf[:-1]) * 3600
    if tf.endswith("d"): return int(tf[:-1]) * 86400
    raise ValueError(f"Unsupported TF {tf!r}")


def _append_csv(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header_exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not header_exists:
            w.writeheader()
        w.writerow(row)


def _round_price(p: float, tick: float) -> float:
    if tick and tick > 0:
        return round(round(p / tick) * tick, 10)
    return p


def _round_qty(q: float, step: float) -> float:
    if step and step > 0:
        # округление вниз, чтобы не нарушить шаг
        return max(0.0, (int(q / step)) * step)
    return q


def _signal(f_prev: float, s_prev: float, f_cur: float, s_cur: float) -> Optional[str]:
    if pd.isna(f_prev) or pd.isna(s_prev) or pd.isna(f_cur) or pd.isna(s_cur):
        return None
    if f_prev <= s_prev and f_cur > s_cur:
        return "buy"
    if f_prev >= s_prev and f_cur < s_cur:
        return "sell"
    return None


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
        price_tick: float,
        qty_step: float,
        min_quote: float,
        poll_sec: Optional[int] = None,
        trades_csv: str = "data/live_paper_trades.csv",
        equity_csv: str = "data/live_paper_equity.csv",
        heartbeat_sec: int = 60,
        max_daily_loss_bps: float = 0.0,
        cooldown_bars: int = 0,
        align_on_state: bool = False,  # ← НОВОЕ
        enter_on_start: bool = False,  # ← НОВОЕ
) -> None:
    tf, _ = _parse_span(span)
    tf_sec = _tf_seconds(tf)
    poll = int(poll_sec or max(5, tf_sec // 2))
    rule = normalize_resample_rule(resample_rule) if resample_rule else ""

    st = BrokerState(cash_eur=start_eur, last_equity=start_eur, day_start_equity=start_eur)
    next_heartbeat = time.time() + max(heartbeat_sec, 0)
    last_bar_ts: Optional[pd.Timestamp] = None
    first_bar_seen = False

    print(f"[paper] {pair} {span} resample={rule or '—'} fast={fast} slow={slow} "
          f"start={start_eur:.2f} fee={fee_bps}bps slip={slip_bps}bps")

    try:
        while True:
            df = fetch_exmo_candles(pair, span, verbose=False)
            if df.empty:
                time.sleep(poll);
                continue
            if rule:
                df = resample_ohlcv(df, rule)

            # SMA
            df["sma_fast"] = df["close"].rolling(fast, min_periods=fast).mean()
            df["sma_slow"] = df["close"].rolling(slow, min_periods=slow).mean()
            if len(df) < max(fast, slow) + 2:
                time.sleep(poll);
                continue

            bar = df.iloc[-1]
            ts: pd.Timestamp = bar["time"]
            if last_bar_ts is not None and ts <= last_bar_ts:
                time.sleep(poll);
                continue
            last_bar_ts = ts

            price = float(bar["close"])
            f_prev, s_prev = df["sma_fast"].iloc[-2], df["sma_slow"].iloc[-2]
            f_cur, s_cur = df["sma_fast"].iloc[-1], df["sma_slow"].iloc[-1]

            # equity
            equity = st.cash_eur + st.pos_qty * price
            st.last_equity = equity
            if df["time"].iloc[-2].date() != ts.date():
                st.day_start_equity = equity  # новый день

            # дневной стоп
            if max_daily_loss_bps > 0 and st.cooldown_left == 0:
                day_pl_bps = (equity / max(st.day_start_equity, 1e-9) - 1.0) * 1e4
                if day_pl_bps <= -abs(max_daily_loss_bps):
                    if st.pos_qty != 0.0:
                        fill = _round_price(price * (1.0 - slip_bps / 1e4), price_tick)
                        revenue = st.pos_qty * fill
                        fee = revenue * (fee_bps / 1e4)
                        st.cash_eur += revenue - fee
                        _append_csv(trades_csv, {
                            "time": ts.isoformat(), "side": "FLAT", "price": fill,
                            "qty": -st.pos_qty, "fee": fee, "note": "max_daily_loss"
                        })
                        st.pos_qty = 0.0
                        equity = st.cash_eur
                        st.last_equity = equity
                    st.cooldown_left = max(1, int(cooldown_bars))
                    print(f"[paper] {ts.isoformat()} MAX_DAILY_LOSS -> flat, cooldown={st.cooldown_left}")
                    _append_csv(equity_csv, {"time": ts.isoformat(), "equity": equity})
                    time.sleep(poll);
                    continue

            if st.cooldown_left > 0:
                st.cooldown_left -= 1
                _append_csv(equity_csv, {"time": ts.isoformat(), "equity": equity})
                if heartbeat_sec > 0 and time.time() >= next_heartbeat:
                    print(f"[paper] {ts.isoformat()} tick equity={equity:.2f} pos={st.pos_qty:.6f}")
                    next_heartbeat = time.time() + heartbeat_sec
                time.sleep(poll);
                continue

            # базовый сигнал — кросс
            sig = _signal(f_prev, s_prev, f_cur, s_cur)
            note = ""

            # НОВОЕ: выравнивание по состоянию
            if sig is None:
                if (enter_on_start and not first_bar_seen) or align_on_state:
                    if st.pos_qty == 0 and pd.notna(f_cur) and pd.notna(s_cur) and f_cur > s_cur:
                        sig, note = "buy", "align"
                    elif st.pos_qty > 0 and pd.notna(f_cur) and pd.notna(s_cur) and f_cur < s_cur:
                        sig, note = "sell", "align"

            first_bar_seen = True

            # исполнение сигнала
            if sig is not None:
                eur_to_use = qty_eur if qty_eur > 0 else (equity * max(0.0, position_pct) / 100.0)
                if sig == "buy":
                    if eur_to_use < max(min_quote, 0.0):
                        _append_csv(equity_csv, {"time": ts.isoformat(), "equity": equity})
                        time.sleep(poll);
                        continue
                    fill = _round_price(price * (1.0 + slip_bps / 1e4), price_tick)
                    qty = eur_to_use / max(fill, 1e-9)
                    qty = _round_qty(qty, qty_step)
                    if qty <= 0:
                        _append_csv(equity_csv, {"time": ts.isoformat(), "equity": equity})
                        time.sleep(poll);
                        continue
                    cost = qty * fill
                    fee = cost * (fee_bps / 1e4)
                    if cost + fee > st.cash_eur:
                        qty = _round_qty((st.cash_eur / (fill * (1.0 + fee_bps / 1e4))), qty_step)
                        cost = qty * fill
                        fee = cost * (fee_bps / 1e4)
                        if qty <= 0:
                            _append_csv(equity_csv, {"time": ts.isoformat(), "equity": equity})
                            time.sleep(poll);
                            continue
                    st.cash_eur -= (cost + fee)
                    st.pos_qty += qty
                    _append_csv(trades_csv, {
                        "time": ts.isoformat(), "side": "BUY", "price": fill,
                        "qty": qty, "fee": fee, "note": note
                    })
                    print(
                        f"[paper] {ts.isoformat()} BUY  qty={qty:.6f} @ {fill:.6f} fee={fee:.4f} {('[' + note + ']') if note else ''}")

                elif sig == "sell" and st.pos_qty > 0:
                    qty = st.pos_qty
                    fill = _round_price(price * (1.0 - slip_bps / 1e4), price_tick)
                    revenue = qty * fill
                    fee = revenue * (fee_bps / 1e4)
                    st.cash_eur += revenue - fee
                    st.pos_qty = 0.0
                    _append_csv(trades_csv, {
                        "time": ts.isoformat(), "side": "SELL", "price": fill,
                        "qty": qty, "fee": fee, "note": note
                    })
                    print(
                        f"[paper] {ts.isoformat()} SELL qty={qty:.6f} @ {fill:.6f} fee={fee:.4f} {('[' + note + ']') if note else ''}")

                equity = st.cash_eur + st.pos_qty * price
                st.last_equity = equity

            # лог equity и heartbeat
            _append_csv(equity_csv, {"time": ts.isoformat(), "equity": equity})
            if heartbeat_sec > 0 and time.time() >= next_heartbeat:
                print(f"[paper] {ts.isoformat()} tick equity={equity:.2f} pos={st.pos_qty:.6f}")
                next_heartbeat = time.time() + heartbeat_sec

            time.sleep(poll)

    except KeyboardInterrupt:
        print("\n[paper] stopped.")
