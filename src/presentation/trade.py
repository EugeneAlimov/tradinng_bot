# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import time
from typing import Optional, Tuple

import pandas as pd

try:
    from ..integrations.exmo import fetch_exmo_candles, resample_ohlcv, normalize_resample_rule
    from ..integrations.exmo_private import ExmoPrivate
except Exception:
    from src.integrations.exmo import fetch_exmo_candles, resample_ohlcv, normalize_resample_rule
    from src.integrations.exmo_private import ExmoPrivate


def _parse_span(span: str) -> Tuple[str, int]:
    tf, n = span.split(":")
    return tf.strip().lower(), int(n)


def _tf_seconds(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"): return int(tf[:-1]) * 60
    if tf.endswith("h"): return int(tf[:-1]) * 3600
    if tf.endswith("d"): return int(tf[:-1]) * 86400
    raise ValueError(f"Unsupported TF {tf!r}")


def _round_price(p: float, tick: float) -> float:
    if tick and tick > 0:
        return round(round(p / tick) * tick, 10)
    return p


def _round_qty(q: float, step: float) -> float:
    if step and step > 0:
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


def _fmt2(x: float) -> str: return f"{x:.6f}"


def run_live_trade(
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
        heartbeat_sec: int = 60,
        max_daily_loss_bps: float = 0.0,
        cooldown_bars: int = 0,
        confirm_live_trade: bool = False,
        align_on_state: bool = False,
        enter_on_start: bool = False,
        client_id_prefix: str = "sma",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
) -> None:
    """
    Реальная торговля (на свой страх и риск). Параметры риска/объёмов — как в paper.
    Исполнение: лимитный ордер по цене close*(1±slip_bps). Если за ~3 сек не исполнен, отменяем.
    """
    if not confirm_live_trade:
        raise SystemExit("Refused to run: add --confirm-live-trade to enable real trading.")

    key = api_key or os.environ.get("EXMO_KEY") or ""
    sec = api_secret or os.environ.get("EXMO_SECRET") or ""
    if not key or not sec:
        raise SystemExit("EXMO_KEY/EXMO_SECRET are required (env or CLI).")

    exmo = ExmoPrivate(key, sec)

    tf, _ = _parse_span(span)
    tf_sec = _tf_seconds(tf)
    poll = int(poll_sec or max(5, tf_sec // 2))
    rule = normalize_resample_rule(resample_rule) if resample_rule else ""

    # известные ограничения/допуски приходят снаружи (price_tick/qty_step/min_quote)
    pos_qty = 0.0
    cash_eur = start_eur  # для внутренней метрики; реальные балансы можно читать из user_info()
    last_bar_ts: Optional[pd.Timestamp] = None
    first_bar_seen = False
    next_heartbeat = time.time() + max(heartbeat_sec, 0)

    print(f"[trade] {pair} {span} resample={rule or '—'} fast={fast} slow={slow} fee={fee_bps}bps slip={slip_bps}bps")

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

            # дневной риск: ориентируемся на paper-эквити (грубая оценка)
            equity = cash_eur + pos_qty * price
            # смена дня
            # (упрощённо: на практике лучше хранить day_start_equity с датой в файле)
            if df["time"].iloc[-2].date() != ts.date():
                day_start_equity = equity
            else:
                day_start_equity = cash_eur + pos_qty * float(df["close"].iloc[-2])
            if max_daily_loss_bps > 0:
                pl_bps = (equity / max(day_start_equity, 1e-9) - 1.0) * 1e4
                if pl_bps <= -abs(max_daily_loss_bps) and pos_qty > 0:
                    # аварийный выход по рынку (лимитом со слиппеджем вниз)
                    lim = _round_price(price * (1.0 - slip_bps / 1e4), price_tick)
                    q = _round_qty(pos_qty, qty_step)
                    if q > 0:
                        oid = _place_limit(exmo, pair, side="sell", price=lim, qty_or_quote=q,
                                           buy_uses_quote=False, client_id_prefix=client_id_prefix)
                        _await_and_cleanup(exmo, oid)
                        pos_qty = 0.0
                        print(f"[trade] {ts.isoformat()} FLAT by daily loss, oid={oid}")
                    cooldown = max(1, int(cooldown_bars))
                    for _ in range(cooldown):
                        # пропускаем сделки на N баров
                        _hb(ts, equity, pos_qty, heartbeat_sec, next_heartbeat)
                        time.sleep(poll)
                    continue

            sig = _signal(f_prev, s_prev, f_cur, s_cur)
            note = ""

            # выравнивание по состоянию (по желанию)
            if sig is None and ((enter_on_start and not first_bar_seen) or align_on_state):
                if pos_qty == 0 and pd.notna(f_cur) and pd.notna(s_cur) and f_cur > s_cur:
                    sig, note = "buy", "align"
                elif pos_qty > 0 and pd.notna(f_cur) and pd.notna(s_cur) and f_cur < s_cur:
                    sig, note = "sell", "align"
            first_bar_seen = True

            if sig == "buy":
                # при BUY в EXMO quantity трактуется как КОТИРУЕМАЯ сумма (EUR) — см. примеры.
                eur_to_use = qty_eur if qty_eur > 0 else (equity * max(0.0, position_pct) / 100.0)
                if eur_to_use < max(min_quote, 0.0):
                    _hb(ts, equity, pos_qty, heartbeat_sec, next_heartbeat);
                    time.sleep(poll);
                    continue
                lim = _round_price(price * (1.0 + slip_bps / 1e4), price_tick)
                # проверим по шагу: реальное количество монет ~ eur_to_use/lim
                qty_base = _round_qty(eur_to_use / max(lim, 1e-9), qty_step)
                if qty_base <= 0:
                    _hb(ts, equity, pos_qty, heartbeat_sec, next_heartbeat);
                    time.sleep(poll);
                    continue
                # отправляем BUY: quantity = сумма в EUR (округлим вниз до цента)
                eur_to_send = max(min_quote, eur_to_use)
                eur_to_send = float(f"{eur_to_send:.2f}")
                oid = _place_limit(exmo, pair, side="buy", price=lim, qty_or_quote=eur_to_send,
                                   buy_uses_quote=True, client_id_prefix=client_id_prefix)
                filled = _await_and_cleanup(exmo, oid)
                if filled:
                    pos_qty += qty_base  # грубая оценка позиции (точно узнаем из user_trades/order_trades при желании)
                    cash_eur -= eur_to_send
                    print(
                        f"[trade] {ts.isoformat()} BUY {qty_base:.6f} @ {lim:.6f} oid={oid} {note and '[' + note + ']' or ''}")

            elif sig == "sell" and pos_qty > 0:
                lim = _round_price(price * (1.0 - slip_bps / 1e4), price_tick)
                qty = _round_qty(pos_qty, qty_step)
                if qty <= 0:
                    _hb(ts, equity, pos_qty, heartbeat_sec, next_heartbeat);
                    time.sleep(poll);
                    continue
                oid = _place_limit(exmo, pair, side="sell", price=lim, qty_or_quote=qty,
                                   buy_uses_quote=False, client_id_prefix=client_id_prefix)
                filled = _await_and_cleanup(exmo, oid)
                if filled:
                    pos_qty = 0.0
                    cash_eur += qty * lim
                    print(
                        f"[trade] {ts.isoformat()} SELL {qty:.6f} @ {lim:.6f} oid={oid} {note and '[' + note + ']' or ''}")

            equity = cash_eur + pos_qty * price
            _hb(ts, equity, pos_qty, heartbeat_sec, next_heartbeat)
            time.sleep(poll)

    except KeyboardInterrupt:
        print("\n[trade] stopped.")


def _place_limit(
        exmo: ExmoPrivate,
        pair: str,
        side: str,
        price: float,
        qty_or_quote: float,
        *,
        buy_uses_quote: bool,
        client_id_prefix: str,
) -> str:
    # client_id для трассировки
    cid = f"{client_id_prefix}-{int(time.time())}"
    price_s = f"{price:.10f}".rstrip("0").rstrip(".")
    qty_s = f"{qty_or_quote:.10f}".rstrip("0").rstrip(".")
    resp = exmo.order_create(pair=pair, quantity=qty_s, price=price_s, side=side, client_id=cid)
    # Ожидается order_id (строка)
    oid = str(resp.get("order_id") or resp.get("order_id_str") or "")
    if not oid:
        raise RuntimeError(f"order_create failed: {resp}")
    return oid


def _await_and_cleanup(exmo: ExmoPrivate, order_id: str, wait_sec: float = 3.0) -> bool:
    """
    Дешёвый FOK: ждём немного, если ордер висит — отменяем.
    Возвращает True, если предполагаем, что ордер исполнился (не висит в open_orders).
    """
    t0 = time.time()
    while time.time() - t0 < wait_sec:
        time.sleep(0.5)
        oo = exmo.user_open_orders()
        for pair, orders in (oo.items() if isinstance(oo, dict) else []):
            if any(str(o.get("order_id")) == order_id for o in (orders or [])):
                break
        else:
            return True  # не нашли в открытых — считаем исполненным
    try:
        exmo.order_cancel(order_id)
    except Exception:
        pass
    return False


def _hb(ts: pd.Timestamp, equity: float, pos_qty: float, heartbeat_sec: int, next_heartbeat: float) -> None:
    if heartbeat_sec > 0 and time.time() >= next_heartbeat:
        print(f"[trade] {ts.isoformat()} tick equity={equity:.2f} pos={pos_qty:.6f}")
