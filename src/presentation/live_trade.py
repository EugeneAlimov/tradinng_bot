from __future__ import annotations

import csv
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

# public (candles, resample)
from src.integrations.exmo import fetch_exmo_candles, resample_ohlcv
# private (orders, wallet)
from src.integrations.exmo_private import ExmoPrivate


# ---------- small io helpers ----------

def _ensure_csv(path: Path, header: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)


def _append_csv(path: Path, row: list) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


def _load_state(path: Path) -> dict:
    if path.exists() and path.stat().st_size > 0:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    # расширенный стейт (cooldown + дневной лимит в bps)
    return {
        "pos_qty": 0.0, "cash_eur": 1000.0, "avg_price": 0.0,
        "pnl_sum_pos": 0.0, "pnl_sum_neg": 0.0, "round_trips": 0, "wins": 0,
        "cooldown_left": 0,
        "daily_date": "", "daily_realized_bps": 0.0, "eq_day_start": 0.0
    }


def _save_state(path: Path, st: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


@dataclass
class PairRules:
    price_tick: float
    qty_step: float
    min_quote: float


# ---------- core trading ----------

def run_live_trade(
        *,
        pair: str,
        span: str,
        resample_rule: str,
        fast: int,
        slow: int,
        start_eur: float,
        qty_eur: float,
        position_pct: float,
        fee_bps: float,
        slip_bps: float,
        price_tick: float,
        qty_step: float,
        min_quote: float,
        poll_sec: int,
        heartbeat_sec: int,
        max_daily_loss_bps: float,
        cooldown_bars: int,
        confirm_live_trade: bool,
        align_on_state: bool,
        enter_on_start: bool,
        fok_wait_sec: float,
        reprice_attempts: int,
        reprice_step_bps: float,
        aggr_limit: bool,
        aggr_ticks: int,
        force_entry: str,
        hysteresis_bps: float = 0.0,
) -> None:
    """
    Живой торговый режим.
    Пишет:
      - data/live_trade_trades.csv  (time,side,price,qty,fee_eur,note)
      - data/live_trade_equity.csv  (time,equity)
      - data/live_trade_balance.csv (pnl_net_eur и т.д.)
      - data/live_trade_state.json
    """
    # --- CSV/paths ---
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    trades_csv = data_dir / "live_trade_trades.csv"
    equity_csv = data_dir / "live_trade_equity.csv"
    balance_csv = data_dir / "live_trade_balance.csv"
    state_json = data_dir / "live_trade_state.json"

    _ensure_csv(trades_csv, ["time", "side", "price", "qty", "fee_eur", "note"])
    _ensure_csv(equity_csv, ["time", "equity"])
    _ensure_csv(balance_csv,
                ["time", "event", "rt", "side", "sell_price", "avg_entry",
                 "qty_closed", "pnl_net_eur", "eur_free", "base_free",
                 "pos_qty_after", "cash_eur_after", "equity_after",
                 "wins", "pnl_pos_sum", "pnl_neg_sum"])

    # --- env and private API ---
    from src.config.env import load_env, env_str
    load_env()  # подхватываем .env если он есть
    api_key = env_str("EXMO_KEY") or env_str("EXMO_API_KEY")
    api_secret = env_str("EXMO_SECRET") or env_str("EXMO_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("EXMO_KEY/EXMO_SECRET are required (env or CLI).")

    exmo = ExmoPrivate(api_key, api_secret)

    # --- rules for pair (min step/quote etc.) ---
    info = exmo.pair_settings(pair)
    rules = PairRules(
        price_tick=float(info.get("min_price_increment") or info.get("price_tick") or price_tick or 0.0),
        qty_step=float(info.get("min_quantity_increment") or info.get("qty_step") or qty_step or 0.0),
        min_quote=float(info.get("min_total") or info.get("min_quote") or min_quote or 0.0),
    )

    # --- state ---
    st = _load_state(state_json)
    pos_qty = float(st.get("pos_qty", 0.0))
    cash_eur = float(st.get("cash_eur", float(start_eur)))
    avg_price = float(st.get("avg_price", 0.0))
    pnl_sum_pos = float(st.get("pnl_sum_pos", 0.0))
    pnl_sum_neg = float(st.get("pnl_sum_neg", 0.0))
    round_trips = int(st.get("round_trips", 0))
    wins = int(st.get("wins", 0))
    cooldown_left = int(st.get("cooldown_left", 0))
    daily_date = str(st.get("daily_date", ""))
    daily_realized_bps = float(st.get("daily_realized_bps", 0.0))
    eq_day_start = float(st.get("eq_day_start", 0.0))

    def _equity(px: float) -> float:
        return cash_eur + pos_qty * px

    # preflight wallet
    try:
        w = exmo.user_info().get("balances") or {}
        eur_free = float((w.get("EUR") or {}).get("available", 0.0))
        base_free = float((w.get(pair.split("_")[0]) or {}).get("available", 0.0))
    except Exception:
        eur_free = base_free = 0.0

    print("[trade] preflight:")
    print(f"  account: EUR_free={eur_free:.6f}, {pair.split('_')[0]}_free={base_free:.6f}")
    print(f"  pair_settings[{pair}]: price_tick={rules.price_tick}, qty_step={rules.qty_step}, min_quote={rules.min_quote}")
    print(f"[trade] resume: pos_qty={pos_qty:.6f} cash_eur={cash_eur:.2f} avg_price={avg_price:.6f}")

    # --- helpers ---
    def _round_step(x: float, step: float, mode: str) -> float:
        if step <= 0:
            return x
        q = x / step
        if mode == "floor":
            q = math.floor(q + 1e-12)
        elif mode == "ceil":
            q = math.ceil(q - 1e-12)
        else:
            q = round(q)
        return q * step

    def _limit_from_price(side: str, px: float) -> float:
        if aggr_limit and rules.price_tick > 0:
            ticks = int(max(0, aggr_ticks))
            if side == "buy":
                px = _round_step(px, rules.price_tick, "ceil") + ticks * rules.price_tick
            else:
                px = _round_step(px, rules.price_tick, "floor") - ticks * rules.price_tick
        else:
            mode = "ceil" if side == "buy" else "floor"
            px = _round_step(px, rules.price_tick, mode)
        return max(px, rules.price_tick) if rules.price_tick > 0 else px

    # candles poll loop
    last_ts: Optional[pd.Timestamp] = None
    next_hb = 0.0

    # daily init
    def _ensure_daily(price_now: float) -> None:
        nonlocal daily_date, daily_realized_bps, eq_day_start
        today = pd.Timestamp.utcnow().date().isoformat()
        if daily_date != today:
            daily_date = today
            eq_day_start = _equity(price_now)
            daily_realized_bps = 0.0

    def _arm_cooldown():
        nonlocal cooldown_left
        if cooldown_bars > 0:
            cooldown_left = cooldown_bars

    def _tick_cooldown():
        nonlocal cooldown_left
        if cooldown_left > 0:
            cooldown_left -= 1

    def _allow_new_entries() -> bool:
        if max_daily_loss_bps > 0 and daily_realized_bps <= -abs(max_daily_loss_bps):
            print(f"[risk] daily loss limit reached: {daily_realized_bps:.1f} bps ≤ -{max_daily_loss_bps:.1f} bps — entries blocked.")
            return False
        if cooldown_left > 0:
            print(f"[trade] cooldown {cooldown_left} bars left — entries blocked.")
            return False
        return True

    def _place_limit(side: str, px: float, qty: float, client_id_prefix: str = "rt") -> Tuple[str, dict]:
        oid = ""
        resp = {}
        try:
            cid = f"{client_id_prefix}-{int(time.time()*1000)}"
            resp = exmo.order_create(
                pair=pair, quantity=qty, price=px, side=side, client_id=cid,
                immediate_or_cancel=True  # быстрый результат; остатки будем «репрайсить»
            )
            oid = str(resp.get("order_id") or resp.get("id") or "")
        except Exception as e:
            print(f"[exmo] order_create error: {e!r}")
        return oid, resp

    try:
        while True:
            # fetch candles
            candles = fetch_exmo_candles(pair, span)
            if resample_rule:
                candles = resample_ohlcv(candles, resample_rule)

            if not candles or len(candles) < max(fast, slow) + 2:
                time.sleep(poll_sec)
                continue

            df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume"])
            df["sma_fast"] = df["close"].rolling(fast, min_periods=fast).mean()
            df["sma_slow"] = df["close"].rolling(slow, min_periods=slow).mean()
            if len(df) < max(fast, slow) + 2:
                time.sleep(poll_sec)
                continue

            prev = df.iloc[-2]
            last = df.iloc[-1]
            ts: pd.Timestamp = pd.to_datetime(last["time"], utc=True)
            if last_ts is not None and ts <= last_ts:
                time.sleep(poll_sec)
                continue
            last_ts = ts

            price = float(last["close"])
            _ensure_daily(price)
            _tick_cooldown()

            pf, ps = float(prev["sma_fast"]), float(prev["sma_slow"])
            f, s = float(last["sma_fast"]), float(last["sma_slow"])

            signal = "none"
            if pf <= ps and f > s:
                signal = "buy"
            elif pf >= ps and f < s:
                signal = "sell"

            # hysteresis filter in bps relative to price
            if signal != "none" and hysteresis_bps > 0.0:
                diff_bps = abs(f - s) / max(1e-12, price) * 1e4
                if diff_bps < hysteresis_bps:
                    signal = "none"

            if force_entry in ("buy", "sell"):
                signal = force_entry

            regime = "LONG" if f >= s else "FLAT"
            base_note = "align" if force_entry == "" else "force"

            def _attempts_loop(side: str, eur_to_use: float, note: str) -> None:
                nonlocal pos_qty, cash_eur, avg_price, pnl_sum_pos, pnl_sum_neg, round_trips, wins, daily_realized_bps

                # entries blocked?
                if side == "buy" and not _allow_new_entries():
                    return

                # qty
                if side == "buy":
                    if eur_to_use <= 0:
                        return
                    qty_raw = eur_to_use / price
                    qty = _round_step(qty_raw, rules.qty_step, "floor") if rules.qty_step > 0 else qty_raw
                    if qty <= 0:
                        return
                else:
                    qty = _round_step(pos_qty, rules.qty_step, "floor") if rules.qty_step > 0 else pos_qty
                    if qty <= 0:
                        return

                lim = _limit_from_price(side, price)

                attempts = max(1, int(reprice_attempts) + 1)
                for i in range(attempts):
                    if i > 0:
                        step = (reprice_step_bps / 1e4) * price
                        lim = lim + step if side == "buy" else lim - step
                        lim = _round_step(lim, rules.price_tick, "ceil" if side == "buy" else "floor")

                    oid, _ = _place_limit(side, lim, qty, client_id_prefix="rt")

                    time.sleep(max(0.5, float(fok_wait_sec)))
                    st_ord = exmo.order_status(pair=pair, order_id=oid)
                    status = str(st_ord.get("status") or "").lower()
                    filled_qty = float(st_ord.get("quantity_processed") or st_ord.get("filled_qty") or 0.0)
                    price_exec = float(st_ord.get("price") or lim)

                    if filled_qty > 0:
                        # комиссия сделки (в €)
                        fee_eur = (price_exec * filled_qty) * (fee_bps / 1e4)
                        # any fill -> arm cooldown
                        _arm_cooldown()

                        if side == "buy":
                            new_pos = pos_qty + filled_qty
                            avg_price = (pos_qty * avg_price + filled_qty * price_exec) / max(new_pos, 1e-9)
                            pos_qty = new_pos
                            # кэш уменьшаем на стоимость + комиссию
                            cash_eur -= filled_qty * price_exec
                            cash_eur -= fee_eur
                        else:
                            qty_closed = min(filled_qty, pos_qty)
                            # валовый pnl по цене
                            pnl_gross = (price_exec - avg_price) * qty_closed
                            # выручка минус комиссия
                            cash_eur += qty_closed * price_exec - fee_eur
                            pos_qty = max(0.0, pos_qty - qty_closed)

                            # реализованный pnl после комиссии продажи
                            pnl_net = pnl_gross - fee_eur
                            if pnl_net >= 0:
                                pnl_sum_pos += pnl_net
                                wins += 1
                            else:
                                pnl_sum_neg += pnl_net

                            # дневной bps от equity начала дня
                            if eq_day_start > 0:
                                pnl_bps = (pnl_net / eq_day_start) * 1e4
                                daily_realized_bps += float(pnl_bps)

                            # если позиция практически нулевая — считаем закрыт rt
                            if pos_qty <= (rules.qty_step or 0.0) / 2:
                                pos_qty = 0.0
                                avg_price = 0.0
                                round_trips += 1
                                eq = _equity(price)
                                _append_csv(balance_csv, [
                                    ts.isoformat(), "CLOSE", round_trips, side.upper(),
                                    f"{price_exec:.10f}", f"{avg_price:.10f}",
                                    f"{qty_closed:.10f}", f"{pnl_net:.10f}",
                                    f"{cash_eur:.8f}", f"{0.0 + 0.0:.8f}",
                                    f"{pos_qty:.10f}", f"{cash_eur:.10f}", f"{eq:.10f}",
                                    wins, f"{pnl_sum_pos:.10f}", f"{pnl_sum_neg:.10f}"
                                ])

                        # лог сделки
                        _append_csv(trades_csv, [
                            ts.isoformat(), side, f"{price_exec:.10f}", f"{filled_qty:.10f}", f"{fee_eur:.10f}", note
                        ])

                        # сохранить стейт
                        st = {
                            "pos_qty": pos_qty, "cash_eur": cash_eur, "avg_price": avg_price,
                            "pnl_sum_pos": pnl_sum_pos, "pnl_sum_neg": pnl_sum_neg,
                            "round_trips": round_trips, "wins": wins,
                            "cooldown_left": cooldown_left,
                            "daily_date": daily_date, "daily_realized_bps": daily_realized_bps,
                            "eq_day_start": eq_day_start,
                        }
                        _save_state(state_json, st)
                        break  # stop attempts after fill

                # equity log
                eq = _equity(price)
                _append_csv(equity_csv, [ts.isoformat(), f"{eq:.10f}"])

            # --- decide to act ---
            eq_now = _equity(price)
            use_eur = qty_eur if qty_eur > 0 else (eq_now * max(0.0, position_pct) / 100.0)

            if (signal == "buy" and (pos_qty <= 0 or enter_on_start)) or (force_entry == "buy"):
                if use_eur >= rules.min_quote:
                    _attempts_loop("buy", use_eur, base_note)

            if ((signal == "sell" and pos_qty > 0) or (force_entry == "sell")) and pos_qty > 0:
                _attempts_loop("sell", 0.0, base_note)

            # heartbeat
            now = time.time()
            if now >= next_hb:
                eq = _equity(price)
                print(f"[trade] {ts.isoformat()} hb equity={eq:.2f} pos={pos_qty:.6f} "
                      f"pnl_real={pnl_sum_pos + pnl_sum_neg:.4f} pnl_unreal={(price - avg_price) * pos_qty:.4f} "
                      f"rt={round_trips} win_rate={(wins / max(1, round_trips)) * 100:.2f}% "
                      f"daily_bps={daily_realized_bps:.1f} cd={cooldown_left}")
                next_hb = now + max(1, int(heartbeat_sec))

            time.sleep(poll_sec)

    except KeyboardInterrupt:
        print("[trade] stopped.")
