# src/presentation/live_trade.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import csv
import json
import time
import math
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any

import pandas as pd

# --------- Public/Private EXMO integrations ----------
# We support either importing directly from integrations module
# or (as a fallback) through app.py shims if the project layout differs.
try:
    from src.integrations.exmo import fetch_exmo_candles, resample_ohlcv, order_book
except Exception:  # pragma: no cover
    try:
        from .app import fetch_exmo_candles, resample_ohlcv  # type: ignore
        order_book = None  # not available via app shim
    except Exception:
        fetch_exmo_candles = None  # type: ignore
        resample_ohlcv = None      # type: ignore
        order_book = None
from src.integrations.exmo_private import ExmoPrivate  # type: ignore


# ================ Helpers ================

def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _append_csv(path: str, header: Tuple[str, ...], row: Tuple[Any, ...]) -> None:
    """Append a row; write header once if file new/empty."""
    _ensure_dir(path)
    need_header = not os.path.exists(path) or os.stat(path).st_size == 0
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if need_header:
            w.writerow(header)
        w.writerow(row)


def _now_iso(ts_utc: Optional[pd.Timestamp] = None) -> str:
    if ts_utc is None:
        ts_utc = pd.Timestamp.utcnow().tz_localize("UTC")
    if isinstance(ts_utc, pd.Timestamp) and ts_utc.tz is None:
        ts_utc = ts_utc.tz_localize("UTC")
    return ts_utc.isoformat().replace("+00:00", "Z")


def _round_step(x: float, step: float) -> float:
    if step <= 0:
        return float(x)
    return math.floor((x + 1e-12) / step) * step


def _round_tick(p: float, tick: float, up: bool) -> float:
    if tick <= 0:
        return float(p)
    k = math.ceil(p / tick) if up else math.floor(p / tick)
    return k * tick


# ================ Live state ================

@dataclass
class LiveState:
    pos_qty: float = 0.0          # base units (DOGE)
    cash_eur: float = 0.0         # quote wallet the bot "manages"
    avg_price: float = 0.0        # VWAP entry of the open position
    pnl_sum_pos: float = 0.0      # realized PnL of winners (EUR)
    pnl_sum_neg: float = 0.0      # realized PnL of losers (EUR)
    round_trips: int = 0
    wins: int = 0

    @property
    def equity(self) -> float:
        return float(self.cash_eur)

    def to_json(self) -> Dict[str, Any]:
        return {
            "pos_qty": float(self.pos_qty),
            "cash_eur": float(self.cash_eur),
            "avg_price": float(self.avg_price),
            "pnl_sum_pos": float(self.pnl_sum_pos),
            "pnl_sum_neg": float(self.pnl_sum_neg),
            "round_trips": int(self.round_trips),
            "wins": int(self.wins),
        }

    @classmethod
    def from_file(cls, path: str) -> "LiveState":
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return cls(
                pos_qty=float(data.get("pos_qty", 0.0)),
                cash_eur=float(data.get("cash_eur", 0.0)),
                avg_price=float(data.get("avg_price", 0.0)),
                pnl_sum_pos=float(data.get("pnl_sum_pos", 0.0)),
                pnl_sum_neg=float(data.get("pnl_sum_neg", 0.0)),
                round_trips=int(data.get("round_trips", 0)),
                wins=int(data.get("wins", 0)),
            )
        except FileNotFoundError:
            return cls()
        except Exception:
            return cls()

    def save(self, path: str) -> None:
        _ensure_dir(path)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.to_json(), f)
        os.replace(tmp, path)


# ================ Signals ================

def _compute_sma(df: pd.DataFrame, fast: int, slow: int) -> pd.DataFrame:
    out = df.copy()
    out["sma_fast"] = out["close"].rolling(fast, min_periods=fast).mean()
    out["sma_slow"] = out["close"].rolling(slow, min_periods=slow).mean()
    return out.dropna().copy()


def _last_signal(d: pd.DataFrame) -> Tuple[str, str]:
    """
    Returns (regime, signal):
      regime: "LONG" if fast > slow else "FLAT"
      signal: "buy" on upward cross, "sell" on downward cross, "none" otherwise
    """
    if len(d) < 2:
        return "FLAT", "none"
    f1, s1 = float(d["sma_fast"].iloc[-1]), float(d["sma_slow"].iloc[-1])
    f0, s0 = float(d["sma_fast"].iloc[-2]), float(d["sma_slow"].iloc[-2])
    regime = "LONG" if f1 >= s1 else "FLAT"
    signal = "none"
    if f0 < s0 and f1 >= s1:
        signal = "buy"
    elif f0 > s0 and f1 <= s1:
        signal = "sell"
    return regime, signal


# ================ EXMO helpers ================

def _account_free(exmo: ExmoPrivate, base_ccy: str, quote_ccy: str) -> Tuple[float, float]:
    info = exmo.user_info()
    balances = info.get("balances", {}) or info.get("wallet", {}) or {}
    base = float(balances.get(base_ccy, 0) or balances.get(base_ccy.lower(), 0) or 0.0)
    quote = float(balances.get(quote_ccy, 0) or balances.get(quote_ccy.lower(), 0) or 0.0)
    return base, quote


def _best_quotes(pair: str) -> Tuple[Optional[float], Optional[float]]:
    """(best_bid, best_ask) using public order_book() if available."""
    try:
        if order_book is None:
            return None, None
        ob = order_book(pair, limit=1)
        bids = ob.get("bid", []) or ob.get("bids", [])
        asks = ob.get("ask", []) or ob.get("asks", [])
        best_bid = float(bids[0][0]) if bids else None
        best_ask = float(asks[0][0]) if asks else None
        return best_bid, best_ask
    except Exception:
        return None, None


def _fok_limit(
    exmo: ExmoPrivate,
    *,
    pair: str,
    side: str,
    price: float,
    qty_base: float,
    client_id_prefix: str,
    fok_wait_sec: float,
) -> Tuple[str, float, float]:
    """
    Place a FOK-like limit: try to fill quickly, else cancel.
    Returns (status, filled_qty, filled_avg_price).
      status: "filled" | "cancelled"
    """
    # EXMO requires strictly numeric client_id
    cid = int(f"{int(time.time())}{1 if side=='buy' else 2}")
    resp = exmo.order_create(pair=pair, quantity=str(qty_base), price=f"{price:.10f}", side=side, client_id=cid)
    oid = str(resp.get("order_id", resp.get("id", "")))

    # wait a little for a fill
    time.sleep(max(0.5, float(fok_wait_sec)))

    # if order still open → cancel and report cancelled
    open_ = exmo.user_open_orders()
    open_ids = set()
    for p, arr in (open_ or {}).items():
        if isinstance(arr, list):
            for it in arr:
                oid0 = str(it.get("order_id", it.get("id", "")))
                if oid0:
                    open_ids.add(oid0)
    if oid in open_ids:
        try:
            exmo.order_cancel(oid)
        except Exception:
            pass
        return "cancelled", 0.0, 0.0

    # We consider it filled at the requested price (exchange may not return fills detail here)
    return "filled", float(qty_base), float(price)


# ================ Main loop ================

def run_live_trade(
    *,
    pair: str,
    span: str,
    resample_rule: str,
    fast: int,
    slow: int,
    fee_bps: float,
    slip_bps: float,
    poll_sec: int = 15,
    heartbeat_sec: int = 60,
    # sizing
    qty_eur: float = 0.0,
    position_pct: float = 0.0,  # percent of cash_eur per entry (0…100)
    # exchange steps (fallbacks if public settings are missing)
    price_tick: float = 0.0,
    qty_step: float = 0.0,
    min_quote: float = 0.0,
    # behavior
    align_on_state: bool = False,
    enter_on_start: bool = False,
    # logging
    trades_csv: str = "data/live_trade_trades.csv",
    equity_csv: str = "data/live_trade_equity.csv",
    balance_csv: str = "data/live_trade_balance.csv",
    state_json: str = "data/live_trade_state.json",
    # risk
    max_daily_loss_bps: float = 0.0,
    cooldown_bars: int = 0,
    base_ccy: str = "DOGE",
    quote_ccy: str = "EUR",
    # EXMO credentials
    client_id_prefix: str = "sma",
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    # FOK/repricing
    fok_wait_sec: float = 6.0,
    reprice_attempts: int = 0,         # not used in this simplified implementation
    reprice_step_bps: float = 5.0,     # not used in this simplified implementation
    # order book pegging
    aggr_limit: bool = False,
    aggr_ticks: int = 0,
    # force single entry/exit
    force_entry: str = "",
    # auto sweep dust (< qty_step)
    dust_sweep: bool = False,
    dust_sweep_max_eur: float = 0.05,
    # must be set by user to enable live trading
    confirm_live_trade: bool = False,
) -> None:
    """
    SMA crossover live trading with simple FOK limits and robust CSV/state logging.

    What you get:
      - Header-once CSV writers (no duplicate headers), atomic replace on state JSON.
      - Three CSV artifacts:
          * trades_csv: time,side,price,qty,note
          * equity_csv: time,equity
          * balance_csv: time,event,rt,side,sell_price,avg_entry,qty_closed,pnl_eur,
                         eur_free,base_free,pos_qty_after,cash_eur_after,equity_after,wins,
                         pnl_pos_sum,pnl_neg_sum
      - Sell qty is clamped to on-chain DOGE_free floored to qty_step to avoid Insufficient funds.
      - "Dust" < qty_step after SELL marks FLAT (position considered closed).
      - Balance line printed after each CLOSE.
      - Heartbeat prints realized/unrealized PnL, win_rate, PF.
    """
    if not confirm_live_trade:
        raise SystemExit("Refused to run: add --confirm-live-trade to enable real trading.")

    key = api_key or os.environ.get("EXMO_API_KEY") or os.environ.get("EXMO_KEY") or ""
    sec = api_secret or os.environ.get("EXMO_API_SECRET") or os.environ.get("EXMO_SECRET") or ""
    if not key or not sec:
        raise SystemExit("EXMO_KEY/EXMO_SECRET are required (env or CLI).")

    exmo = ExmoPrivate(key, sec)

    # ---------- detect exchange step settings (fallback to CLI) ----------
    try:
        settings = exmo.pair_settings(pair)  # may not exist in your wrapper
    except Exception:
        settings = {}
    price_prec = int(settings.get("price_precision", 0) or 0)
    step_from_settings = float(settings.get("min_quantity_increment", 0) or 0.0)
    min_amount = settings.get("min_amount")
    try:
        min_amount = float(min_amount) if min_amount is not None else 0.0
    except Exception:
        min_amount = 0.0

    eff_price_tick = price_tick if price_tick > 0 else (10.0 ** (-price_prec) if price_prec else 0.0)
    eff_qty_step   = qty_step if qty_step > 0 else step_from_settings
    eff_min_quote  = min_quote if min_quote > 0 else min_amount

    # ---------- preflight ----------
    base_free0, eur_free0 = _account_free(exmo, base_ccy, quote_ccy)
    print("[trade] preflight:")
    print(f"  account: {quote_ccy}_free={eur_free0:.6f}, {base_ccy}_free={base_free0:.6f}")
    print(f"  pair_settings[{pair}]: price_tick={eff_price_tick or 'n/a'}, qty_step={eff_qty_step or 'n/a'}, min_quote={eff_min_quote or 'n/a'}")

    # ---------- restore state ----------
    st = LiveState.from_file(state_json)
    if st.cash_eur <= 0:
        # If no prior state → initialize from "virtual balance" for reporting only.
        st.cash_eur = float(eur_free0) if eur_free0 > 0 else 1000.0

    # Clamp pos to wallet on resume (safety)
    base_free_now, eur_free_now = _account_free(exmo, base_ccy, quote_ccy)
    st.pos_qty = min(st.pos_qty, base_free_now)

    print(f"[trade] resume: pos_qty={st.pos_qty:.6f} cash_eur={st.cash_eur:.2f} avg_price={st.avg_price:.6f}")

    # ---------- CSV headers (created on first write) ----------
    TR_H = ("time", "side", "price", "qty", "note")
    EQ_H = ("time", "equity")
    BL_H = ("time","event","rt","side","sell_price","avg_entry","qty_closed","pnl_eur",
            "eur_free","base_free","pos_qty_after","cash_eur_after","equity_after","wins",
            "pnl_pos_sum","pnl_neg_sum")

    # ---------- runtime vars ----------
    last_bar_ts: Optional[pd.Timestamp] = None
    cooldown_left = 0
    next_hb = time.time() + max(heartbeat_sec, 0)
    poll = max(1, int(poll_sec))

    def _heartbeat(ts: pd.Timestamp, last_price: float) -> None:
        """Print equity (cash + mark-to-market), realized & unrealized PnL."""
        realized_pos = st.pnl_sum_pos
        realized_neg = st.pnl_sum_neg
        unreal = st.pos_qty * (last_price - (st.avg_price or last_price))
        equity_est = st.cash_eur + st.pos_qty * last_price
        trades = int(st.round_trips)
        win_rate = (st.wins / trades * 100.0) if trades > 0 else 0.0
        pf = float("inf") if realized_neg >= 0 else (realized_pos / abs(realized_neg) if realized_pos > 0 and realized_neg < 0 else 0.0)
        print(f"[trade] {ts.isoformat()} hb equity={equity_est:.2f} pos={st.pos_qty:.6f} pnl_real={realized_pos+realized_neg:.4f} pnl_unreal={unreal:.4f} rt={trades} win_rate={win_rate:.2f}% pf={'∞' if pf==float('inf') else f'{pf:.2f}'}")
        _append_csv(equity_csv, EQ_H, (_now_iso(ts), equity_est))

    def _entry_size_eur(last_price: float) -> float:
        if qty_eur > 0:
            return float(qty_eur)
        if position_pct > 0:
            return max(eff_min_quote, st.cash_eur * (position_pct / 100.0))
        # default small probing size if nothing specified
        return max(eff_min_quote, 1.0)

    def _place(side: str, last_price: float, note: str) -> Tuple[bool, float]:
        """Attempt a FOK limit pegged to best quotes (if available). Returns (filled, fill_price)."""
        best_bid, best_ask = _best_quotes(pair)
        if side == "buy":
            base_eur = _entry_size_eur(last_price)
            lim = last_price * (1.0 + slip_bps / 10_000.0)
            if aggr_limit and best_ask:
                lim = best_ask + aggr_ticks * eff_price_tick
            qty = base_eur / max(lim, 1e-12)
            qty = _round_step(qty, eff_qty_step)
            if qty <= 0:
                return False, 0.0
        else:
            # sell: clamp to wallet free (safety) and to step
            base_free, _ = _account_free(exmo, base_ccy, quote_ccy)
            qty = _round_step(min(st.pos_qty, base_free), eff_qty_step)
            if qty <= 0:
                return False, 0.0
            lim = last_price * (1.0 - slip_bps / 10_000.0)
            if aggr_limit and best_bid:
                lim = max(best_bid - aggr_ticks * eff_price_tick, eff_price_tick)

        status, filled_qty, filled_price = _fok_limit(
            exmo, pair=pair, side=side, price=lim, qty_base=qty,
            client_id_prefix=client_id_prefix, fok_wait_sec=fok_wait_sec
        )
        filled = (status == "filled" and filled_qty > 0)
        if filled:
            _append_csv(trades_csv, TR_H, (_now_iso(), side.upper(), filled_price, filled_qty, note))
        return filled, filled_price

    def _on_buy_fill(price: float, qty: float) -> None:
        cost = price * qty
        fee = cost * (fee_bps / 10_000.0)
        st.cash_eur -= (cost + fee)
        total_qty = st.pos_qty + qty
        st.avg_price = (st.avg_price * st.pos_qty + price * qty) / max(total_qty, 1e-12)
        st.pos_qty = total_qty

    def _on_sell_fill(price: float, qty: float, ts: pd.Timestamp) -> None:
        proceeds = price * qty
        fee = proceeds * (fee_bps / 10_000.0)
        st.cash_eur += (proceeds - fee)
        st.pos_qty = max(0.0, st.pos_qty - qty)

        # closed PnL for that slice
        pnl = (price - st.avg_price) * qty - fee
        st.round_trips += 1
        if pnl > 0:
            st.pnl_sum_pos += pnl
            st.wins += 1
        else:
            st.pnl_sum_neg += pnl

        # if position is effectively closed → reset avg
        if st.pos_qty <= (eff_qty_step * 0.5):
            st.avg_price = 0.0
            st.pos_qty = 0.0

        # wallet snapshot (for nice log line)
        base_free, eur_free = _account_free(exmo, base_ccy, quote_ccy)
        equity_est = st.cash_eur + st.pos_qty * price
        _append_csv(
            balance_csv, BL_H,
            (_now_iso(ts), "CLOSE", st.round_trips, "SELL", price, st.avg_price or 0.0, qty, pnl,
             eur_free, base_free, st.pos_qty, st.cash_eur, equity_est, st.wins, st.pnl_sum_pos, st.pnl_sum_neg)
        )
        print(f"[trade] closed rt={st.round_trips} qty={qty:.6f} sell={price:.6f} avg={st.avg_price:.6f} pnl={pnl:.6f} EUR  |  balances: {quote_ccy}_free={eur_free:.6f}, {base_ccy}_free={base_free:.6f}, equity≈{equity_est:.2f}")

    # Optional one-shot action at start (force_entry)
    def _handle_force(side: str, ts: pd.Timestamp) -> None:
        filled, fp = _place(side, last_price=float(df_sma["close"].iloc[-1]), note="force")
        if filled:
            if side == "buy":
                qty = _round_step(_entry_size_eur(fp)/fp, eff_qty_step)
                _on_buy_fill(fp, qty)
            else:
                qty = _round_step(min(st.pos_qty, _account_free(exmo, base_ccy, quote_ccy)[0]), eff_qty_step)
                if qty > 0:
                    _on_sell_fill(fp, qty, ts)
            st.save(state_json)

    # Main loop
    print(f"[trade] {pair} {span} resample={'—' if not resample_rule else resample_rule} fast={fast} slow={slow} fee={fee_bps}bps slip={slip_bps}bps")

    next_hb = time.time() + max(heartbeat_sec, 0)
    try:
        # initial heartbeat snapshot using last price if available later
        while True:
            # 1) pull latest candles
            df = fetch_exmo_candles(pair, span) if fetch_exmo_candles else None
            if df is None or df.empty:
                time.sleep(poll)
                continue
            if resample_rule:
                df = resample_ohlcv(df, resample_rule)  # type: ignore
            df = df.dropna().copy()
            if df.empty:
                time.sleep(poll)
                continue

            # 2) indicators & signal
            df_sma = _compute_sma(df, fast=fast, slow=slow)
            if df_sma.empty:
                time.sleep(poll)
                continue

            ts: pd.Timestamp = df_sma["time"].iloc[-1] if "time" in df_sma.columns else df_sma.index[-1]  # type: ignore
            price = float(df_sma["close"].iloc[-1])
            regime, sig = _last_signal(df_sma)

            # First bar initialization / force entry
            if last_bar_ts is None:
                last_bar_ts = ts
                if enter_on_start and force_entry in ("buy", "sell"):
                    _handle_force(force_entry, ts)
                # heartbeat
                if heartbeat_sec > 0:
                    _heartbeat(ts, price)
                time.sleep(poll)
                continue

            # Skip within same bar (avoid multiple signals)
            if ts == last_bar_ts:
                # periodic heartbeat even inside the same bar
                if heartbeat_sec > 0 and time.time() >= next_hb:
                    _heartbeat(ts, price)
                    next_hb = time.time() + heartbeat_sec
                time.sleep(poll)
                continue

            # New bar arrived
            last_bar_ts = ts

            # Cooldown logic
            if cooldown_left > 0:
                cooldown_left -= 1

            # Apply max daily loss (approx on realized pnl only)
            if max_daily_loss_bps > 0:
                realized = st.pnl_sum_pos + st.pnl_sum_neg
                if realized < 0:
                    eq0 = st.cash_eur  # cash_eur approximates starting equity for the session
                    if abs(realized) >= (eq0 * max_daily_loss_bps / 10_000.0):
                        print(f"[trade] daily loss limit hit ({max_daily_loss_bps} bps). Ignoring entries until restart.")
                        sig = "none"

            # 3) act on signal
            if cooldown_left <= 0:
                if sig == "buy" and st.pos_qty <= 0:
                    filled, fp = _place("buy", last_price=price, note=regime)
                    if filled:
                        qty = _round_step(_entry_size_eur(fp)/fp, eff_qty_step)
                        _on_buy_fill(fp, qty)
                        st.save(state_json)
                        if cooldown_bars > 0:
                            cooldown_left = cooldown_bars

                elif sig == "sell" and st.pos_qty > 0:
                    qty = _round_step(min(st.pos_qty, _account_free(exmo, base_ccy, quote_ccy)[0]), eff_qty_step)
                    if qty > 0:
                        filled, fp = _place("sell", last_price=price, note=regime)
                        if filled:
                            _on_sell_fill(fp, qty, ts)
                            st.save(state_json)
                            if cooldown_bars > 0:
                                cooldown_left = cooldown_bars
                    else:
                        print(f"[trade] skip sell: wallet {base_ccy}_free={_account_free(exmo, base_ccy, quote_ccy)[0]:.6f} < step={eff_qty_step}")

            # heartbeat after processing new bar
            if heartbeat_sec > 0 and time.time() >= next_hb:
                _heartbeat(ts, price)
                next_hb = time.time() + heartbeat_sec

            time.sleep(poll)

    except KeyboardInterrupt:
        print("\n[trade] stopped.")
        trades = int(st.round_trips)
        realized = st.pnl_sum_pos + st.pnl_sum_neg
        pf = float("inf") if st.pnl_sum_neg >= 0 else (st.pnl_sum_pos / abs(st.pnl_sum_neg) if st.pnl_sum_pos > 0 and st.pnl_sum_neg < 0 else 0.0)
        equity_est = st.cash_eur + st.pos_qty * (price if "price" in locals() else 0.0)
        win_rate = (st.wins / trades * 100.0) if trades > 0 else 0.0
        print(f"[live-report] equity≈{equity_est:.6f}  rt={trades}  win_rate={win_rate:.2f}%  pf={'∞' if pf==float('inf') else f'{pf:.2f}'}")
        # save state on exit
        st.save(state_json)
