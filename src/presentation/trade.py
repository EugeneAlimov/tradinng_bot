# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import time
from typing import Optional, Tuple

import pandas as pd
import json, csv

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
    if not confirm_live_trade:
        raise SystemExit("Refused to run: add --confirm-live-trade to enable real trading.")

    key = api_key or os.environ.get("EXMO_KEY") or ""
    sec = api_secret or os.environ.get("EXMO_SECRET") or ""
    if not key or not sec:
        raise SystemExit("EXMO_KEY/EXMO_SECRET are required (env or CLI).")

    exmo = ExmoPrivate(key, sec)

    # --- файлы логов и состояние (дефолты, без новых флагов) ---
    trades_csv = "data/live_trade_trades.csv"
    equity_csv = "data/live_trade_equity.csv"
    state_path = "data/live_trade_state.json"

    # --- префлайт ---
    base_ccy, quote_ccy = (pair.split("_", 1) + [""])[:2]
    try:
        ui = exmo.user_info()
    except Exception as e:
        raise SystemExit(f"user_info failed: {e}")

    def _f(x):
        try:
            return float(x)
        except Exception:
            return 0.0

    bal = (ui.get("balances") or ui.get("balance") or {})
    eur_free = _f(bal.get(quote_ccy, 0))
    base_free = _f(bal.get(base_ccy, 0))

    try:
        ps = exmo.pair_settings(pair)
    except Exception as e:
        ps = {}
        print(f"[trade] warning: pair_settings failed: {e}")

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
    min_amount = ps.get("min_amount") or ps.get("min_total")
    try:
        min_amount = float(min_amount) if min_amount is not None else 0.0
    except Exception:
        min_amount = 0.0

    eff_price_tick = price_tick if price_tick > 0 else (10.0 ** (-price_prec) if price_prec is not None else 0.0)
    eff_qty_step = qty_step if qty_step > 0 else step_from_settings
    eff_min_quote = min_quote if min_quote > 0 else min_amount

    print("[trade] preflight:")
    print(f"  account: {quote_ccy}_free={eur_free:.6f}, {base_ccy}_free={base_free:.6f}")
    print(
        f"  pair_settings[{pair}]: price_tick={eff_price_tick or 'n/a'}, qty_step={eff_qty_step or 'n/a'}, min_quote={eff_min_quote or 'n/a'}")

    # --- восстановление состояния (если есть) ---
    st = _load_state(state_path)
    pos_qty = float(st.get("pos_qty", 0.0))
    cash_eur = float(st.get("cash_eur", start_eur))
    avg_price = float(st.get("avg_price", 0.0))  # средняя цена входа для PnL
    pnl_sum_pos = float(st.get("pnl_sum_pos", 0.0))
    pnl_sum_neg = float(st.get("pnl_sum_neg", 0.0))
    round_trips = int(st.get("round_trips", 0))
    wins = int(st.get("wins", 0))
    print(f"[trade] resume: pos_qty={pos_qty:.6f} cash_eur={cash_eur:.2f} avg_price={avg_price:.6f}")

    tf, _ = _parse_span(span)
    tf_sec = _tf_seconds(tf)
    poll = int(poll_sec or max(5, tf_sec // 2))
    rule = normalize_resample_rule(resample_rule) if resample_rule else ""

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

            regime = "LONG" if (pd.notna(f_cur) and pd.notna(s_cur) and f_cur > s_cur) else "FLAT"
            sig, base_note = None, ""
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

            print(
                f"[trade] {ts.isoformat()} regime={regime} signal={sig or (base_note or 'none')} price={price:.6f} f={f_cur:.6f} s={s_cur:.6f}")

            equity = cash_eur + pos_qty * price

            # дневной стоп (упрощённо отн. к предыдущему бару)
            if max_daily_loss_bps > 0 and pos_qty > 0:
                day_start_eq = cash_eur + pos_qty * float(df['close'].iloc[-2])
                pl_bps = (equity / max(day_start_eq, 1e-9) - 1.0) * 1e4
                if pl_bps <= -abs(max_daily_loss_bps):
                    lim = _round_price(price * (1.0 - slip_bps / 1e4), eff_price_tick)
                    qty = _round_qty(pos_qty, eff_qty_step)
                    if qty > 0:
                        oid = _place_limit(exmo, pair, side="sell", price=lim, qty_base=qty,
                                           client_id_prefix=client_id_prefix)
                        filled = _await_and_cleanup(exmo, oid, wait_sec=3.0)
                        print(f"[trade] daily-loss exit oid={oid} -> {'filled' if filled else 'cancelled'}")
                        if filled:
                            # закрыли круг — считаем PnL относительно avg_price
                            trade_pnl = (lim - avg_price) * qty - (lim + avg_price) * qty * (fee_bps / 1e4)
                            (pnl_sum_pos if trade_pnl >= 0 else pnl_sum_neg).__iadd__(trade_pnl)
                            if trade_pnl >= 0: wins += 1
                            round_trips += 1
                            pos_qty = 0.0
                            cash_eur += qty * lim
                            avg_price = 0.0
                    cool = max(1, int(cooldown_bars))
                    for _ in range(cool):
                        _append_csv(equity_csv, {"time": ts.isoformat(), "equity": equity})
                        if heartbeat_sec > 0 and time.time() >= next_hb:
                            print(f"[trade] {ts.isoformat()} hb equity={equity:.2f} pos={pos_qty:.6f}")
                            next_hb = time.time() + heartbeat_sec
                        time.sleep(poll)
                    _save_state(state_path, {
                        "pos_qty": pos_qty, "cash_eur": cash_eur, "avg_price": avg_price,
                        "pnl_sum_pos": pnl_sum_pos, "pnl_sum_neg": pnl_sum_neg,
                        "round_trips": round_trips, "wins": wins
                    })
                    continue

            # исполнение по сигналу
            if sig == "buy":
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
                            # обновим позицию и среднюю
                            new_qty = pos_qty + qty_base
                            avg_price = ((pos_qty * avg_price) + (qty_base * lim)) / max(new_qty, 1e-9)
                            pos_qty = new_qty
                            cash_eur -= qty_base * lim
                            _append_csv(trades_csv, {
                                "time": ts.isoformat(), "side": "BUY", "price": lim, "qty": qty_base, "note": base_note
                            })

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
                        # круг закрыт — считаем PnL
                        trade_pnl = (lim - avg_price) * qty - (lim + avg_price) * qty * (fee_bps / 1e4)
                        if trade_pnl >= 0:
                            pnl_sum_pos += trade_pnl; wins += 1
                        else:
                            pnl_sum_neg += trade_pnl
                        round_trips += 1
                        pos_qty -= qty
                        cash_eur += qty * lim
                        avg_price = 0.0
                        _append_csv(trades_csv, {
                            "time": ts.isoformat(), "side": "SELL", "price": lim, "qty": qty, "note": base_note
                        })

            equity = cash_eur + pos_qty * price
            _append_csv(equity_csv, {"time": ts.isoformat(), "equity": equity})

            _save_state(state_path, {
                "pos_qty": pos_qty, "cash_eur": cash_eur, "avg_price": avg_price,
                "pnl_sum_pos": pnl_sum_pos, "pnl_sum_neg": pnl_sum_neg,
                "round_trips": round_trips, "wins": wins
            })

            if heartbeat_sec > 0 and time.time() >= next_hb:
                print(f"[trade] {ts.isoformat()} hb equity={equity:.2f} pos={pos_qty:.6f}")
                next_hb = time.time() + heartbeat_sec

            time.sleep(poll)

    except KeyboardInterrupt:
        # финальная сводка
        total_trades = round_trips
        pf = float("inf") if pnl_sum_neg >= 0 else (pnl_sum_pos / abs(pnl_sum_neg) if pnl_sum_pos > 0 else 0.0)
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
        equity_est = cash_eur + pos_qty * (price if 'price' in locals() else 0.0)
        print("\n[trade] stopped.")
        print(
            f"[live-report] equity≈{equity_est:.6f}  rt={total_trades}  win_rate={win_rate:.2f}%  pf={'∞' if pf == float('inf') else f'{pf:.2f}'}")


def _place_limit(
        exmo: ExmoPrivate,
        pair: str,
        side: str,
        price: float,
        qty_base: float,
        *,
        client_id_prefix: str,
) -> str:
    import time as _t, random, string
    cid = f"{client_id_prefix}-{int(_t.time())}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=4))}"
    price_s = f"{price:.10f}".rstrip("0").rstrip(".")
    qty_s = f"{qty_base:.10f}".rstrip("0").rstrip(".")
    resp = exmo.order_create(pair=pair, quantity=qty_s, price=price_s, side=side, client_id=cid)
    oid = str(resp.get("order_id") or resp.get("order_id_str") or "")
    if not oid:
        raise RuntimeError(f"order_create failed: {resp}")
    return oid


def _await_and_cleanup(exmo: ExmoPrivate, order_id: str, wait_sec: float = 3.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < wait_sec:
        time.sleep(0.5)
        try:
            oo = exmo.user_open_orders()
        except Exception:
            continue
        found = False
        if isinstance(oo, dict):
            for _pair, orders in oo.items():
                for o in (orders or []):
                    if str(o.get("order_id")) == order_id:
                        found = True
                        break
                if found: break
        if not found:
            return True
    try:
        exmo.order_cancel(order_id)
    except Exception:
        pass
    return False


def _hb(ts: pd.Timestamp, equity: float, pos_qty: float, heartbeat_sec: int, next_heartbeat: float) -> None:
    if heartbeat_sec > 0 and time.time() >= next_heartbeat:
        print(f"[trade] {ts.isoformat()} tick equity={equity:.2f} pos={pos_qty:.6f}")


def _append_csv(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header_exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not header_exists:
            w.writeheader()
        w.writerow(row)


def _save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, path)


def _load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}
