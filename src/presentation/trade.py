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
    Реальная торговля с безопасным «префлайтом» и диагностикой:
      1) Печатаем user_info и pair_settings (price_tick/qty_step/min_quote),
      2) Для ЛИМИТ-ордеров используем КОЛИЧЕСТВО БАЗОВОЙ валюты (DOGE), не сумму в EUR,
      3) На каждом закрытом баре печатаем краткую диагностику режима/сигнала,
      4) Для каждого ордера печатаем результат: filled/cancelled.
    """
    if not confirm_live_trade:
        raise SystemExit("Refused to run: add --confirm-live-trade to enable real trading.")

    key = api_key or os.environ.get("EXMO_KEY") or ""
    sec = api_secret or os.environ.get("EXMO_SECRET") or ""
    if not key or not sec:
        raise SystemExit("EXMO_KEY/EXMO_SECRET are required (env or CLI).")

    exmo = ExmoPrivate(key, sec)

    # --- Префлайт: балансы и настройки пары ---
    base_ccy, quote_ccy = (pair.split("_", 1) + [""])[:2]
    try:
        ui = exmo.user_info()
    except Exception as e:
        raise SystemExit(f"user_info failed: {e}")

    # user_info: пытаемся достать свободные балансы
    def _get_balances(uinfo: dict) -> tuple[float, float]:
        bal = uinfo.get("balances") or uinfo.get("balance") or {}

        # возможны строки — приведём к float
        def _f(x):
            try:
                return float(x)
            except Exception:
                return 0.0

        return _f(bal.get(quote_ccy, 0)), _f(bal.get(base_ccy, 0))  # EUR_free, DOGE_free

    eur_free, base_free = _get_balances(ui)

    # pair_settings
    try:
        ps_all = exmo.pair_settings()
        ps = ps_all.get(pair, {}) if isinstance(ps_all, dict) else {}
    except Exception as e:
        ps_all, ps = {}, {}
        print(f"[trade] warning: pair_settings failed: {e}")

    # попытаемся извлечь тики/шаги/минималки из настроек биржи
    price_prec = ps.get("price_precision") or ps.get("price_scale") or ps.get("price_decimals")
    try:
        price_prec = int(price_prec) if price_prec is not None else None
    except Exception:
        price_prec = None

    step_from_settings = ps.get("quantity_step") or ps.get("min_quantity") or ps.get("min_quantity_step")
    try:
        step_from_settings = float(step_from_settings) if step_from_settings is not None else 0.0
    except Exception:
        step_from_settings = 0.0

    min_amount = ps.get("min_amount") or ps.get("min_total")  # минимальная СУММА в котируемой (EUR)
    try:
        min_amount = float(min_amount) if min_amount is not None else 0.0
    except Exception:
        min_amount = 0.0

    # применим фоллбэки только если пользователь не задал параметры вручную (>0)
    eff_price_tick = price_tick if price_tick > 0 else (10.0 ** (-price_prec) if price_prec is not None else 0.0)
    eff_qty_step = qty_step if qty_step > 0 else step_from_settings
    eff_min_quote = min_quote if min_quote > 0 else min_amount

    print("[trade] preflight:")
    print(f"  account: {quote_ccy}_free={eur_free:.6f}, {base_ccy}_free={base_free:.6f}")
    print(
        f"  pair_settings[{pair}]: price_tick={eff_price_tick or 'n/a'}, qty_step={eff_qty_step or 'n/a'}, min_quote={eff_min_quote or 'n/a'}")

    # --- Основной цикл ---
    tf, _ = _parse_span(span)
    tf_sec = _tf_seconds(tf)
    poll = int(poll_sec or max(5, tf_sec // 2))
    rule = normalize_resample_rule(resample_rule) if resample_rule else ""

    pos_qty = 0.0  # локальная оценка позиции
    cash_eur = start_eur  # локальная оценка кэша (для диагностики)
    last_bar_ts: Optional[pd.Timestamp] = None
    first_bar_seen = False
    next_hb = time.time() + max(heartbeat_sec, 0)

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

            # режим/сигнал
            regime = "LONG" if (pd.notna(f_cur) and pd.notna(s_cur) and f_cur > s_cur) else "FLAT"
            sig = None
            base_note = ""
            if pd.notna(f_prev) and pd.notna(s_prev) and pd.notna(f_cur) and pd.notna(s_cur):
                if f_prev <= s_prev and f_cur > s_cur:
                    sig = "buy"
                elif f_prev >= s_prev and f_cur < s_cur:
                    sig = "sell"
            if sig is None and ((enter_on_start and not first_bar_seen) or align_on_state):
                if pos_qty == 0 and regime == "LONG":
                    sig, base_note = "buy", "align"
                elif pos_qty > 0 and regime == "FLAT":
                    sig, base_note = "sell", "align"
            first_bar_seen = True

            # быстрая диагностика бара
            print(
                f"[trade] {ts.isoformat()} regime={regime} signal={sig or (base_note or 'none')} price={price:.6f} f={f_cur:.6f} s={s_cur:.6f}")

            # дневной риск — в этой упрощённой версии просто пропустим, если нарушен
            equity = cash_eur + pos_qty * price
            if max_daily_loss_bps > 0:
                # примем старт дня по предыдущему бару
                day_start_eq = cash_eur + pos_qty * float(df['close'].iloc[-2])
                pl_bps = (equity / max(day_start_eq, 1e-9) - 1.0) * 1e4
                if pl_bps <= -abs(max_daily_loss_bps) and pos_qty > 0:
                    lim = _round_price(price * (1.0 - slip_bps / 1e4), eff_price_tick)
                    qty = _round_qty(pos_qty, eff_qty_step)
                    if qty > 0:
                        oid = _place_limit(exmo, pair, side="sell", price=lim, qty_base=qty,
                                           client_id_prefix=client_id_prefix)
                        filled = _await_and_cleanup(exmo, oid, wait_sec=3.0)
                        print(f"[trade] daily-loss exit oid={oid} -> {'filled' if filled else 'cancelled'}")
                        if filled:
                            pos_qty = 0.0
                            cash_eur += qty * lim
                    # пауза
                    cool = max(1, int(cooldown_bars))
                    for _ in range(cool):
                        if heartbeat_sec > 0 and time.time() >= next_hb:
                            print(f"[trade] {ts.isoformat()} hb equity={equity:.2f} pos={pos_qty:.6f}")
                            next_hb = time.time() + heartbeat_sec
                        time.sleep(poll)
                    continue

            # исполнение
            if sig == "buy":
                # считаем базовое количество (DOGE), а не сумму в EUR
                eur_to_use = qty_eur if qty_eur > 0 else (equity * max(0.0, position_pct) / 100.0)
                if eur_to_use < max(eff_min_quote, 0.0):
                    print(f"[trade] skip buy: eur_to_use={eur_to_use:.2f} < min_quote={eff_min_quote}")
                else:
                    lim = _round_price(price * (1.0 + slip_bps / 1e4), eff_price_tick)
                    qty_base = _round_qty(eur_to_use / max(lim, 1e-9), eff_qty_step)
                    if qty_base <= 0:
                        print(f"[trade] skip buy: qty_base=0 after rounding (qty_step={eff_qty_step})")
                    else:
                        oid = _place_limit(exmo, pair, side="buy", price=lim, qty_base=qty_base,
                                           client_id_prefix=client_id_prefix)
                        filled = _await_and_cleanup(exmo, oid, wait_sec=3.0)
                        print(
                            f"[trade] buy oid={oid} -> {'filled' if filled else 'cancelled'} lim={lim:.6f} qty={qty_base:.6f} {('[' + base_note + ']') if base_note else ''}")
                        if filled:
                            pos_qty += qty_base
                            cash_eur -= qty_base * lim  # грубая оценка кэша

            elif sig == "sell" and pos_qty > 0:
                lim = _round_price(price * (1.0 - slip_bps / 1e4), eff_price_tick)
                qty = _round_qty(pos_qty, eff_qty_step)
                if qty <= 0:
                    print(f"[trade] skip sell: qty=0 after rounding (qty_step={eff_qty_step})")
                else:
                    oid = _place_limit(exmo, pair, side="sell", price=lim, qty_base=qty,
                                       client_id_prefix=client_id_prefix)
                    filled = _await_and_cleanup(exmo, oid, wait_sec=3.0)
                    print(
                        f"[trade] sell oid={oid} -> {'filled' if filled else 'cancelled'} lim={lim:.6f} qty={qty:.6f} {('[' + base_note + ']') if base_note else ''}")
                    if filled:
                        pos_qty -= qty
                        cash_eur += qty * lim

            # heartbeat
            if heartbeat_sec > 0 and time.time() >= next_hb:
                equity = cash_eur + pos_qty * price
                print(f"[trade] {ts.isoformat()} hb equity={equity:.2f} pos={pos_qty:.6f}")
                next_hb = time.time() + heartbeat_sec

            time.sleep(poll)

    except KeyboardInterrupt:
        print("\n[trade] stopped.")


def _place_limit(
        exmo: ExmoPrivate,
        pair: str,
        side: str,
        price: float,
        qty_base: float,
        *,
        client_id_prefix: str,
) -> str:
    """
    Создаёт ЛИМИТ-ордер с количеством в БАЗОВОЙ валюте (DOGE для DOGE_EUR).
    """
    import time as _t
    cid = f"{client_id_prefix}-{int(_t.time())}"
    price_s = f"{price:.10f}".rstrip("0").rstrip(".")
    qty_s = f"{qty_base:.10f}".rstrip("0").rstrip(".")
    resp = exmo.order_create(pair=pair, quantity=qty_s, price=price_s, side=side, client_id=cid)
    oid = str(resp.get("order_id") or resp.get("order_id_str") or "")
    if not oid:
        raise RuntimeError(f"order_create failed: {resp}")
    return oid


def _await_and_cleanup(exmo: ExmoPrivate, order_id: str, wait_sec: float = 3.0) -> bool:
    """
    «Мягкий FOK»: ждём до wait_sec, если ордер всё ещё «в открытых» — отменяем.
    True -> предполагаем исполнение (не найден в open_orders), False -> отменён.
    """
    t0 = time.time()
    while time.time() - t0 < wait_sec:
        time.sleep(0.5)
        try:
            oo = exmo.user_open_orders()
        except Exception:
            # если не смогли получить — попробуем ещё
            continue
        found = False
        if isinstance(oo, dict):
            for _pair, orders in oo.items():
                for o in (orders or []):
                    if str(o.get("order_id")) == order_id:
                        found = True
                        break
                if found:
                    break
        if not found:
            return True  # больше не висит
    try:
        exmo.order_cancel(order_id)
    except Exception:
        pass
    return False


def _hb(ts: pd.Timestamp, equity: float, pos_qty: float, heartbeat_sec: int, next_heartbeat: float) -> None:
    if heartbeat_sec > 0 and time.time() >= next_heartbeat:
        print(f"[trade] {ts.isoformat()} tick equity={equity:.2f} pos={pos_qty:.6f}")
