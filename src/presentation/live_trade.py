from __future__ import annotations

import csv
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Iterable, Any

import pandas as pd

# public (candles, resample)
from src.integrations.exmo import fetch_exmo_candles, resample_ohlcv
# private (orders, wallet)
from src.integrations.exmo_private import ExmoPrivate

# secure creds + atomic state
from src.security.credentials import get_api_credentials
from src.utils.atomic_state import AtomicState
# alerts
from src.monitoring.alerts import make_alerter


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
    # расширенный стейт: cooldown + дневной лимит + трекинг внешних ордеров
    return {
        "pos_qty": 0.0, "cash_eur": 1000.0, "avg_price": 0.0,
        "pnl_sum_pos": 0.0, "pnl_sum_neg": 0.0, "round_trips": 0, "wins": 0,
        "cooldown_left": 0,
        "daily_date": "", "daily_realized_bps": 0.0, "eq_day_start": 0.0,
        # внешний трекинг: ext_orders[oid] = {"side":"sell","price":float,"qty":float,"filled":float}
        "ext_orders": {}
    }


def _to_df(candles: Any) -> pd.DataFrame:
    """
    Приводит candles к DataFrame c колонками: time, open, high, low, close, volume.
    Поддерживает вход: DataFrame | list/tuple[ (ts, o,h,l,c, [v]) ].
    """
    if candles is None:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    if isinstance(candles, pd.DataFrame):
        df = candles.copy()
        cols_lower = {c: str(c).lower() for c in df.columns}
        inv = {v: k for k, v in cols_lower.items()}
        need = ["time", "open", "high", "low", "close", "volume"]
        if all(col in cols_lower.values() for col in need):
            rename = {inv[c]: c for c in need if c in inv}
            df = df.rename(columns=rename)
            if "volume" not in df.columns:
                df["volume"] = 0.0
            return df[["time", "open", "high", "low", "close", "volume"]]
        mapping = {}
        for c in df.columns:
            cl = str(c).lower()
            if "time" in cl or "ts" in cl or cl == "t":
                mapping[c] = "time"
            elif cl.startswith("o"):
                mapping[c] = "open"
            elif cl.startswith("h"):
                mapping[c] = "high"
            elif cl.startswith("l"):
                mapping[c] = "low"
            elif cl.startswith("c"):
                mapping[c] = "close"
            elif "vol" in cl or cl.startswith("v"):
                mapping[c] = "volume"
        df = df.rename(columns=mapping)
        for col in ["time", "open", "high", "low", "close"]:
            if col not in df.columns:
                df[col] = pd.NA
        if "volume" not in df.columns:
            df["volume"] = 0.0
        return df[["time", "open", "high", "low", "close", "volume"]].copy()

    rows: Iterable = candles if isinstance(candles, (list, tuple)) else list(candles)
    norm = []
    for r in rows:
        if not isinstance(r, (list, tuple)) or len(r) < 5:
            continue
        if len(r) == 5:
            t, o, h, l, c = r
            v = 0.0
        else:
            t, o, h, l, c, v = r[:6]
        norm.append([t, float(o), float(h), float(l), float(c), float(v)])
    return pd.DataFrame(norm, columns=["time", "open", "high", "low", "close", "volume"])


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
        # risk ext (по умолчанию отключено/без ограничений)
        max_position_pct: float = 100.0,
        stop_loss_bps: float = 0.0,
        # reconcile
        reconcile_threshold_qty: float = 0.0,
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
    state_writer = AtomicState(state_json)

    _ensure_csv(trades_csv, ["time", "side", "price", "qty", "fee_eur", "note"])
    _ensure_csv(equity_csv, ["time", "equity"])
    _ensure_csv(balance_csv,
                ["time", "event", "rt", "side", "sell_price", "avg_entry",
                 "qty_closed", "pnl_net_eur", "eur_free", "base_free",
                 "pos_qty_after", "cash_eur_after", "equity_after",
                 "wins", "pnl_pos_sum", "pnl_neg_sum"])

    # --- alerts ---
    alert = make_alerter()

    # --- creds: keyring → env(.env) ---
    api_key, api_secret = get_api_credentials()
    if not api_key or not api_secret:
        from src.config.env import load_env, env_str
        load_env()
        api_key = api_key or env_str("EXMO_KEY") or env_str("EXMO_API_KEY")
        api_secret = api_secret or env_str("EXMO_SECRET") or env_str("EXMO_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("EXMO_KEY/EXMO_SECRET are required (keyring or env/.env).")

    exmo = ExmoPrivate(api_key, api_secret)

    # --- rules for pair (min step/quote etc.) ---
    info = exmo.pair_settings(pair)
    rules = PairRules(
        price_tick=float(info.get("min_price_increment") or info.get("price_tick") or price_tick or 0.0),
        qty_step=float(info.get("min_quantity_increment") or info.get("qty_step") or qty_step or 0.0),
        min_quote=float(info.get("min_total") or info.get("min_quote") or min_quote or 0.0),
    )

    # --- env overrides for risk/reconcile (если CLI не проброшен) ---
    def _env_float(name: str, default: float) -> float:
        try:
            v = os.getenv(name)
            return float(v) if v is not None and v != "" else default
        except Exception:
            return default

    if max_position_pct == 100.0:
        max_position_pct = _env_float("MAX_POSITION_PCT", 100.0)
    if stop_loss_bps == 0.0:
        stop_loss_bps = _env_float("STOP_LOSS_BPS", 0.0)
    if reconcile_threshold_qty == 0.0:
        reconcile_threshold_qty = _env_float("RECONCILE_THRESHOLD_QTY", max(rules.qty_step or 0.0, 1e-9))

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
    ext_orders = dict(st.get("ext_orders", {}))

    def _equity(px: float) -> float:
        return cash_eur + pos_qty * px

    # preflight wallet (user_info → balances)
    try:
        info = exmo.user_info()
        balances = info.get("balances") or {}
        eur_free = float((balances.get("EUR") or {}).get("available", 0.0))
        base_free = float((balances.get(pair.split("_")[0]) or {}).get("available", 0.0))
    except Exception:
        eur_free = base_free = 0.0

    print("[trade] preflight:")
    print(f"  account: EUR_free={eur_free:.6f}, {pair.split('_')[0]}_free={base_free:.6f}")
    print(f"  pair_settings[{pair}]: price_tick={rules.price_tick}, qty_step={rules.qty_step}, min_quote={rules.min_quote}")
    print(f"[trade] resume: pos_qty={pos_qty:.6f} cash_eur={cash_eur:.2f} avg_price={avg_price:.6f}")
    print(f"[trade] {pair} {span} resample={resample_rule} fast={fast} slow={slow} fee={fee_bps}bps slip={slip_bps}bps")
    print(f"[risk] max_position_pct={max_position_pct:.2f}% stop_loss_bps={stop_loss_bps:.1f} reconcile_thr_qty={reconcile_threshold_qty}")

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
        if rules.price_tick > 0:
            mode = "ceil" if side == "buy" else "floor"
            px = _round_step(px, rules.price_tick, mode)
        return max(px, rules.price_tick) if rules.price_tick > 0 else px

    def _place_limit(side: str, px: float, qty: float, client_id_prefix: str = "rt") -> Tuple[str, dict]:
        """Создаёт лимит без server-side IOC (на акке запрещён этот параметр)."""
        oid = ""
        resp = {}
        try:
            cid = f"{client_id_prefix}-{int(time.time()*1000)}"
            resp = exmo.order_create(
                pair=pair, quantity=qty, price=px, side=side, client_id=cid
            )
            oid = str(resp.get("order_id") or resp.get("id") or "")
        except Exception as e:
            print(f"[exmo] order_create error: {e!r}")
            _bump_error(f"order_create: {e}")
        return oid, resp

    # ---------- alerts/error counter ----------
    consecutive_errors = 0

    def _bump_error(msg: str) -> None:
        nonlocal consecutive_errors
        consecutive_errors += 1
        if consecutive_errors >= 3:
            alert.send(f"⚠️ <b>EXMO errors</b>: {consecutive_errors} подряд\n{msg}")
            consecutive_errors = 0  # чтобы не спамить

    def _reset_errors() -> None:
        nonlocal consecutive_errors
        consecutive_errors = 0

    # ---------- external (long-term) sell orders tracking ----------

    def _list_open_orders(pair: str):
        """Вернёт список открытых ордеров по паре с унифицированными полями."""
        try:
            data = exmo.user_open_orders(pair=pair)
            orders = data.get(pair) if isinstance(data, dict) else None
            if not isinstance(orders, list):
                return []
            norm = []
            for o in orders:
                oid = str(o.get("order_id") or o.get("id") or "")
                side = str(o.get("type") or o.get("order_type") or "").lower()
                price = float(o.get("price") or 0.0)
                qty = float(o.get("quantity") or o.get("qty") or 0.0)
                qp = float(o.get("quantity_processed") or o.get("filled_qty") or 0.0)
                client_id = str(o.get("client_id") or "")
                norm.append({"order_id": oid, "side": side, "price": price, "qty": qty, "filled": qp, "client_id": client_id})
            return norm
        except Exception as e:
            _bump_error(f"user_open_orders: {e}")
            return []

    def _filled_of_order(order_id: str) -> Tuple[float, float]:
        """
        Возвращает (filled_qty, avg_price) по трейдам ордера.
        """
        try:
            tr = exmo.order_trades(order_id)
            trades = tr.get("trades") or tr.get("response") or []
            if isinstance(trades, dict):
                trades = list(trades.values())
            qty_sum = 0.0
            px_w = 0.0
            for t in trades:
                q = float(t.get("quantity") or t.get("qty") or 0.0)
                p = float(t.get("price") or 0.0)
                qty_sum += q
                px_w += q * p
            avg = (px_w / qty_sum) if qty_sum > 0 else 0.0
            _reset_errors()
            return qty_sum, avg
        except Exception as e:
            _bump_error(f"order_trades: {e}")
            return 0.0, 0.0

    def _reserved_sell_qty() -> float:
        """Сколько qty сейчас «зарезервировано» под внешние незавершённые SELL-ордера."""
        total = 0.0
        for rec in ext_orders.values():
            if str(rec.get("side")) == "sell":
                total += max(0.0, float(rec.get("qty", 0.0)) - float(rec.get("filled", 0.0)))
        return total

    def _sync_external_orders(current_price: float, fee_bps_val: float):
        """
        Синхронизировать внешние (долгосрочные) ордера:
          - обнаружить/обновить SELL-ордера, выставленные вручную (client_id не начинается с 'rt').
          - доучесть новые исполнения (delta_filled) как обычную продажу с комиссией.
        """
        nonlocal pos_qty, cash_eur, avg_price, pnl_sum_pos, pnl_sum_neg, round_trips, wins, daily_realized_bps, ext_orders

        open_now = _list_open_orders(pair)
        open_ext = {o["order_id"]: o for o in open_now
                    if o["side"] == "sell" and not str(o.get("client_id", "")).lower().startswith("rt")}

        # добавить/обновить текущие внешние ордера
        for oid, o in open_ext.items():
            rec = ext_orders.get(oid, {"side": "sell", "price": o["price"], "qty": o["qty"], "filled": 0.0})
            rec["price"] = o["price"]
            rec["qty"] = o["qty"]
            rec["filled"] = max(float(rec.get("filled", 0.0)), float(o["filled"]))
            ext_orders[oid] = rec

        # обработать известные ордера (могли исполниться/отмениться)
        known_oids = list(ext_orders.keys())
        for oid in known_oids:
            in_open = oid in open_ext
            prev_filled = float(ext_orders[oid].get("filled", 0.0))
            price_exec = float(ext_orders[oid].get("price", current_price))

            if not in_open:
                filled_total, avg_px = _filled_of_order(oid)
                new_fill = max(0.0, filled_total - prev_filled)
                if new_fill > 0 and avg_px > 0:
                    price_exec = avg_px
            else:
                filled_total, avg_px = _filled_of_order(oid)
                if filled_total > 0 and avg_px > 0:
                    price_exec = avg_px
                new_fill = max(0.0, filled_total - prev_filled)

            if new_fill > 0.0:
                fee_eur = (price_exec * new_fill) * (fee_bps_val / 1e4)
                pnl_gross = (price_exec - avg_price) * new_fill
                cash_eur += new_fill * price_exec - fee_eur
                pos_qty = max(0.0, pos_qty - new_fill)
                pnl_net = pnl_gross - fee_eur
                if pnl_net >= 0:
                    pnl_sum_pos += pnl_net
                    wins += 1
                else:
                    pnl_sum_neg += pnl_net
                if eq_day_start > 0:
                    pnl_bps = (pnl_net / eq_day_start) * 1e4
                    daily_realized_bps += float(pnl_bps)

                _append_csv(trades_csv, [
                    pd.Timestamp.utcnow().isoformat(), "sell", f"{price_exec:.10f}", f"{new_fill:.10f}",
                    f"{fee_eur:.10f}", "ext"
                ])

                if pos_qty <= (rules.qty_step or 0.0) / 2:
                    pos_qty = 0.0
                    avg_price = 0.0
                    round_trips += 1
                    eq = cash_eur + pos_qty * current_price
                    _append_csv(balance_csv, [
                        pd.Timestamp.utcnow().isoformat(), "CLOSE", round_trips, "SELL",
                        f"{price_exec:.10f}", f"{avg_price:.10f}",
                        f"{new_fill:.10f}", f"{pnl_net:.10f}",
                        f"{cash_eur:.8f}", f"{0.0 + 0.0:.8f}",
                        f"{pos_qty:.10f}", f"{cash_eur:.10f}", f"{eq:.10f}",
                        wins, f"{pnl_sum_pos:.10f}", f"{pnl_sum_neg:.10f}"
                    ])

                ext_orders[oid]["filled"] = prev_filled + new_fill

            # если ордера нет и исполнений нет — удалить (отменён)
            if (not in_open):
                filled_total, _ = _filled_of_order(oid)
                if filled_total <= 0.0 + 1e-12:
                    ext_orders.pop(oid, None)

        # сохранить стейт после синка
        st2 = {
            "pos_qty": pos_qty, "cash_eur": cash_eur, "avg_price": avg_price,
            "pnl_sum_pos": pnl_sum_pos, "pnl_sum_neg": pnl_sum_neg,
            "round_trips": round_trips, "wins": wins,
            "cooldown_left": cooldown_left,
            "daily_date": daily_date, "daily_realized_bps": daily_realized_bps,
            "eq_day_start": eq_day_start,
            "ext_orders": ext_orders,
        }
        AtomicState(state_json).save(st2)  # отдельный инстанс ок

    # --- reconcile: периодически сверяем фактическую позицию с биржей ---
    last_reconcile = 0.0

    def _reconcile_with_exchange(price_now: float) -> None:
        nonlocal pos_qty, cash_eur, last_reconcile
        if time.time() - last_reconcile < 60:
            return
        last_reconcile = time.time()
        try:
            info = exmo.user_info()
            b = info.get("balances") or {}
            base = pair.split("_")[0]
            base_free = float((b.get(base) or {}).get("available", 0.0))
            base_locked = float((b.get(base) or {}).get("reserved", 0.0))
            on_exchange_qty = base_free + base_locked
            target_pos = max(0.0, on_exchange_qty)
            if abs(target_pos - pos_qty) > max(reconcile_threshold_qty, rules.qty_step or 0.0, 1e-9):
                delta = target_pos - pos_qty
                print(f"[sync] reconcile pos: local {pos_qty:.6f} -> exchange {target_pos:.6f} (Δ={delta:.6f})")
                alert.send(f"ℹ️ <b>Reconcile</b> Δ={delta:.6f}\npos {pos_qty:.6f} → {target_pos:.6f}")
                pos_qty = target_pos
                stx = {
                    "pos_qty": pos_qty, "cash_eur": cash_eur, "avg_price": avg_price,
                    "pnl_sum_pos": pnl_sum_pos, "pnl_sum_neg": pnl_sum_neg,
                    "round_trips": round_trips, "wins": wins,
                    "cooldown_left": cooldown_left,
                    "daily_date": daily_date, "daily_realized_bps": daily_realized_bps,
                    "eq_day_start": eq_day_start, "ext_orders": ext_orders,
                }
                AtomicState(state_json).save(stx)
            _reset_errors()
        except Exception as e:
            _bump_error(f"user_info (reconcile): {e}")

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
            msg = f"daily loss limit reached: {daily_realized_bps:.1f} bps ≤ -{max_daily_loss_bps:.1f} bps — entries blocked."
            print(f"[risk] {msg}")
            alert.send(f"🛑 <b>Daily loss limit</b>\n{msg}")
            return False
        if cooldown_left > 0:
            print(f"[trade] cooldown {cooldown_left} bars left — entries blocked.")
            return False
        return True

    try:
        while True:
            # --- fetch candles ---
            candles = fetch_exmo_candles(pair, span)
            if resample_rule:
                candles = resample_ohlcv(candles, resample_rule)

            df = _to_df(candles)
            if df is None or df.empty or len(df) < max(fast, slow) + 2:
                time.sleep(poll_sec)
                continue

            df = df.copy()
            df["time"] = pd.to_datetime(df["time"], utc=True, unit="ms", errors="coerce") \
                         if pd.api.types.is_numeric_dtype(df["time"]) else pd.to_datetime(df["time"], utc=True, errors="coerce")
            df = df.dropna(subset=["time", "close"])
            if df.empty or len(df) < max(fast, slow) + 2:
                time.sleep(poll_sec)
                continue

            df = df.sort_values("time")
            df["sma_fast"] = df["close"].rolling(fast, min_periods=fast).mean()
            df["sma_slow"] = df["close"].rolling(slow, min_periods=slow).mean()
            if len(df) < max(fast, slow) + 2:
                time.sleep(poll_sec)
                continue

            prev = df.iloc[-2]
            last = df.iloc[-1]
            ts: pd.Timestamp = last["time"]
            if last_ts is not None and ts <= last_ts:
                time.sleep(poll_sec)
                continue
            last_ts = ts

            price = float(last["close"])
            _ensure_daily(price)
            _tick_cooldown()

            # reconcile локального состояния с биржей (раз в 60с)
            _reconcile_with_exchange(price)

            # синхронизация частичных исполнений внешних ордеров
            _sync_external_orders(current_price=price, fee_bps_val=fee_bps)

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

            base_note = "align" if force_entry == "" else "force"

            # --- inner attempts loop (place → wait → status → cancel-if-not-full → (reprice)) ---
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
                    # risk: cap по размеру позиции
                    if max_position_pct < 100.0:
                        eq_now = _equity(price)
                        max_pos_qty = (eq_now * (max_position_pct / 100.0)) / max(price, 1e-12)
                        allowed_qty = max(0.0, max_pos_qty - pos_qty)
                        qty_raw = min(qty_raw, allowed_qty)
                    qty = _round_step(qty_raw, rules.qty_step, "floor") if rules.qty_step > 0 else qty_raw
                    if qty <= 0:
                        return
                else:
                    # свободная для продажи позиция = pos_qty - резерв под внешние SELL
                    free_qty = max(0.0, pos_qty - _reserved_sell_qty())
                    qty = _round_step(free_qty, rules.qty_step, "floor") if rules.qty_step > 0 else free_qty
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
                    # статус
                    try:
                        st_ord = ExmoPrivate.order_status(exmo, pair=pair, order_id=oid)
                        filled_qty = float(st_ord.get("quantity_processed") or st_ord.get("filled_qty") or 0.0)
                        price_exec = float(st_ord.get("price") or lim)
                        _reset_errors()
                    except Exception as e:
                        _bump_error(f"order_status: {e}")
                        filled_qty = 0.0
                        price_exec = lim

                    # уточняем среднюю цену/объём по фактическим сделкам
                    qsum, avg_px = _filled_of_order(oid)
                    if qsum > 0:
                        filled_qty = qsum
                        price_exec = avg_px or price_exec

                    # если ордер не исполнен полностью — отменить перед репрайсом/выходом
                    try:
                        if filled_qty <= 0 or filled_qty < qty - 1e-12:
                            exmo.order_cancel(oid)
                            _reset_errors()
                    except Exception as e:
                        print(f"[exmo] order_cancel warn: {e!r}")
                        _bump_error(f"order_cancel: {e}")

                    if filled_qty > 0:
                        # комиссия сделки (в €)
                        fee_eur = (price_exec * filled_qty) * (fee_bps / 1e4)
                        # any fill -> arm cooldown
                        _arm_cooldown()

                        if side == "buy":
                            new_pos = pos_qty + filled_qty
                            avg_price = (pos_qty * avg_price + filled_qty * price_exec) / max(new_pos, 1e-9)
                            pos_qty = new_pos
                            cash_eur -= filled_qty * price_exec
                            cash_eur -= fee_eur
                        else:
                            qty_closed = min(filled_qty, pos_qty)
                            pnl_gross = (price_exec - avg_price) * qty_closed
                            cash_eur += qty_closed * price_exec - fee_eur
                            pos_qty = max(0.0, pos_qty - qty_closed)

                            pnl_net = pnl_gross - fee_eur
                            if pnl_net >= 0:
                                pnl_sum_pos += pnl_net
                                wins += 1
                            else:
                                pnl_sum_neg += pnl_net

                            if eq_day_start > 0:
                                pnl_bps = (pnl_net / eq_day_start) * 1e4
                                daily_realized_bps += float(pnl_bps)

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

                        _append_csv(trades_csv, [
                            ts.isoformat(), side, f"{price_exec:.10f}", f"{filled_qty:.10f}", f"{fee_eur:.10f}", note
                        ])

                        st3 = {
                            "pos_qty": pos_qty, "cash_eur": cash_eur, "avg_price": avg_price,
                            "pnl_sum_pos": pnl_sum_pos, "pnl_sum_neg": pnl_sum_neg,
                            "round_trips": round_trips, "wins": wins,
                            "cooldown_left": cooldown_left,
                            "daily_date": daily_date, "daily_realized_bps": daily_realized_bps,
                            "eq_day_start": eq_day_start, "ext_orders": ext_orders,
                        }
                        AtomicState(state_json).save(st3)
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

            # risk: стоп-лосс (простой, от avg_price)
            if pos_qty > 0 and stop_loss_bps > 0 and avg_price > 0:
                if price <= avg_price * (1.0 - stop_loss_bps / 1e4):
                    msg = f"stop-loss hit @ {price:.6f} (avg {avg_price:.6f})"
                    print(f"[risk] {msg}")
                    alert.send(f"⛔ <b>Stop-loss</b>\n{pair}: {msg}")
                    _attempts_loop("sell", 0.0, "stoploss")

            # heartbeat
            now = time.time()
            if now >= next_hb:
                eq = _equity(price)
                print(f"[trade] {ts.isoformat()} hb equity={eq:.2f} pos={pos_qty:.6f} "
                      f"pnl_real={pnl_sum_pos + pnl_sum_neg:.4f} pnl_unreal={(price - avg_price) * pos_qty:.4f} "
                      f"rt={round_trips} win_rate={(wins / max(1, round_trips)) * 100:.2f}% "
                      f"daily_bps={daily_realized_bps:.1f} cd={cooldown_left} resv={_reserved_sell_qty():.6f}")
                next_hb = now + max(1, int(heartbeat_sec))

            time.sleep(poll_sec)

    except KeyboardInterrupt:
        print("[trade] stopped.")
