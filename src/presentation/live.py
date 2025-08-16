# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any

import numpy as np
import pandas as pd

# ===== Попытка импортов из integrations.exmo / exmo_private с фолбэками =====

def _try_import_public():
    try:
        from src.integrations.exmo import (
            fetch_exmo_candles as _f,
            resample_ohlcv as _r,
            normalize_resample_rule as _n,
        )
        # ExmoPublic опционально — если есть в модуле
        try:
            from src.integrations.exmo import ExmoPublic as _P
        except Exception:
            _P = None
        return _f, _r, _n, _P
    except Exception:
        try:
            from ..integrations.exmo import (
                fetch_exmo_candles as _f,
                resample_ohlcv as _r,
                normalize_resample_rule as _n,
            )
            try:
                from ..integrations.exmo import ExmoPublic as _P
            except Exception:
                _P = None
            return _f, _r, _n, _P
        except Exception:
            return None, None, None, None


def _try_import_private():
    try:
        from src.integrations.exmo_private import ExmoPrivate as _E
        return _E
    except Exception:
        try:
            from ..integrations.exmo_private import ExmoPrivate as _E
            return _E
        except Exception:
            return None


_FEXMO, _RESAMPLE, _NORM, _PUBCLS = _try_import_public()
_ExmoPrivate = _try_import_private()


# ===== Фолбэки публичных утилит =====

def fetch_exmo_candles(pair: str, span: str, verbose: bool = False) -> pd.DataFrame:
    if _FEXMO is None:
        raise RuntimeError("integrations.exmo.fetch_exmo_candles отсутствует.")
    return _FEXMO(pair, span, verbose=verbose)


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if not rule:
        return df.copy()
    if _RESAMPLE is not None:
        return _RESAMPLE(df, rule)
    # Простейший фолбэк
    x = df.copy()
    if "time" in x.columns:
        x["time"] = pd.to_datetime(x["time"], utc=True, errors="coerce")
        x = x.set_index("time")
    if not isinstance(x.index, pd.DatetimeIndex):
        raise ValueError("DataFrame должен иметь DatetimeIndex или колонку 'time'")
    o = x["open"].resample(rule).first()
    h = x["high"].resample(rule).max()
    l = x["low"].resample(rule).min()
    c = x["close"].resample(rule).last()
    v = x["volume"].resample(rule).sum() if "volume" in x.columns else None
    out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c})
    if v is not None:
        out["volume"] = v
    out = out.dropna().reset_index()
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


# ===== Вспомогательные утилиты =====

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


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _bps_to_ratio(bps: float) -> float:
    return float(bps) / 10_000.0


def _round_to_step(x: float, step: float) -> float:
    if step <= 0:
        return float(x)
    return math.floor(x / step + 1e-12) * step


def _round_price_tick(p: float, tick: float) -> float:
    if tick <= 0:
        return float(p)
    return round(round(p / tick) * tick, 10)


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _append_csv_row(path: str, header: Tuple[str, ...], row: Dict[str, Any]) -> None:
    """Надёжная дозапись CSV: заголовок только при первом создании файла."""
    _ensure_dir(path)
    write_header = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(header))
        if write_header:
            w.writeheader()
        # гарантируем порядок полей
        w.writerow({k: row.get(k, "") for k in header})


# ===== Состояние лайва =====

STATE_PATH = "data/live_trade_state.json"
TRADES_CSV = "data/live_trade_trades.csv"
EQUITY_CSV = "data/live_trade_equity.csv"
BALANCE_CSV = "data/live_trade_balance.csv"


@dataclass
class LiveState:
    pos_qty: float = 0.0
    cash_eur: float = 0.0
    avg_price: float = 0.0
    pnl_sum_pos: float = 0.0
    pnl_sum_neg: float = 0.0
    round_trips: int = 0
    wins: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pos_qty": float(self.pos_qty),
            "cash_eur": float(self.cash_eur),
            "avg_price": float(self.avg_price),
            "pnl_sum_pos": float(self.pnl_sum_pos),
            "pnl_sum_neg": float(self.pnl_sum_neg),
            "round_trips": int(self.round_trips),
            "wins": int(self.wins),
        }

    @staticmethod
    def load(path: str) -> "LiveState":
        if not os.path.exists(path):
            return LiveState()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        st = LiveState()
        st.pos_qty = float(data.get("pos_qty", 0.0))
        st.cash_eur = float(data.get("cash_eur", 0.0))
        st.avg_price = float(data.get("avg_price", 0.0))
        st.pnl_sum_pos = float(data.get("pnl_sum_pos", 0.0))
        st.pnl_sum_neg = float(data.get("pnl_sum_neg", 0.0))
        st.round_trips = int(data.get("round_trips", 0))
        st.wins = int(data.get("wins", 0))
        return st

    def save(self, path: str) -> None:
        _ensure_dir(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)


# ===== Работа со стаканом (для aggr-limit) =====

class _OrderBookClient:
    """Обёртка над ExmoPublic, если доступен. Иначе безопасные фолбэки."""

    def __init__(self):
        self.client = _PUBCLS() if _PUBCLS is not None else None

    def best_quotes(self, pair: str) -> Tuple[Optional[float], Optional[float]]:
        """Возвращает (best_bid, best_ask) или (None, None), если недоступно."""
        if self.client is None:
            return None, None
        try:
            ob = self.client.order_book(pair=pair)
            bids = ob.get("bid") or ob.get("bids") or []
            asks = ob.get("ask") or ob.get("asks") or []
            best_bid = float(bids[0][0]) if bids else None
            best_ask = float(asks[0][0]) if asks else None
            return best_bid, best_ask
        except Exception:
            return None, None


# ===== Основная логика =====

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
    poll_sec: Optional[int],
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
) -> None:

    if _ExmoPrivate is None:
        raise RuntimeError("integrations.exmo_private.ExmoPrivate отсутствует.")

    api_key = os.environ.get("EXMO_KEY") or os.environ.get("EXMO_API_KEY") or ""
    api_secret = os.environ.get("EXMO_SECRET") or os.environ.get("EXMO_API_SECRET") or ""
    if not api_key or not api_secret:
        print("EXMO_KEY/EXMO_SECRET are required (env).")
        raise SystemExit(1)

    exmo = _ExmoPrivate(api_key=api_key, api_secret=api_secret)
    ob_client = _OrderBookClient()

    tf, _ = _parse_span(span)
    tf_sec = _tf_seconds(tf)
    poll = int(poll_sec or max(5, tf_sec // 2))
    rule = normalize_resample_rule(resample_rule) if resample_rule else "—"

    fee_r = _bps_to_ratio(fee_bps)
    slip_r = _bps_to_ratio(slip_bps)
    reprice_step_r = _bps_to_ratio(reprice_step_bps)

    # --- загрузка и первичный отчёт кошелька ---
    acc = exmo.user_info()  # предполагается, что такой метод есть в вашем exmo_private
    eur_free = float(acc.get("balances", {}).get("EUR", 0.0))
    base = pair.split("_")[0]
    base_free = float(acc.get("balances", {}).get(base, 0.0))
    pair_settings = {
        "price_tick": price_tick or 0.0,
        "qty_step": qty_step or 0.0,
        "min_quote": min_quote or 0.0,
    }
    print("[trade] preflight:")
    print(f"  account: EUR_free={eur_free:.6f}, {base}_free={base_free:.6f}")
    print(f"  pair_settings[{pair}]: price_tick={pair_settings['price_tick']}, qty_step={pair_settings['qty_step']}, min_quote={pair_settings['min_quote']}")

    st = LiveState.load(STATE_PATH)
    if st.cash_eur <= 0.0:
        st.cash_eur = float(start_eur)

    print(f"[trade] resume: pos_qty={st.pos_qty:.6f} cash_eur={st.cash_eur:.2f} avg_price={st.avg_price:.6f}")
    print(f"[trade] {pair} {span} resample={rule} fast={fast} slow={slow} fee={fee_bps}bps slip={slip_bps}bps")

    # Печать подтверждения «торговать?»
    if confirm_live_trade:
        ans = input("Proceed with LIVE trading? [y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted by user.")
            return

    def _quantize(price: float, qty: float) -> Tuple[float, float]:
        qp = _round_price_tick(price, pair_settings["price_tick"])
        qq = _round_to_step(qty, pair_settings["qty_step"])
        return qp, qq

    def _equity(mark_price: float) -> float:
        return st.cash_eur + st.pos_qty * mark_price

    def _append_equity(ts: str, eq: float) -> None:
        _append_csv_row(EQUITY_CSV, ("time", "equity"), {"time": ts, "equity": eq})

    def _append_trade(ts: str, side: str, price: float, qty: float, note: str = "") -> None:
        _append_csv_row(
            TRADES_CSV,
            ("time", "side", "price", "qty", "note"),
            {"time": ts, "side": side.upper(), "price": price, "qty": qty, "note": note or ""},
        )

    def _append_balance_close(
        ts: str,
        side: str,
        sell_price: float,
        avg_entry: float,
        qty_closed: float,
        pnl_eur: float,
        eur_free_now: float,
        base_free_now: float,
        equity_after: float,
    ) -> None:
        _append_csv_row(
            BALANCE_CSV,
            (
                "time", "event", "rt", "side",
                "sell_price", "avg_entry", "qty_closed", "pnl_eur",
                "eur_free", "base_free",
                "pos_qty_after", "cash_eur_after", "equity_after",
                "wins", "pnl_pos_sum", "pnl_neg_sum",
            ),
            {
                "time": ts, "event": "CLOSE", "rt": st.round_trips, "side": side.upper(),
                "sell_price": sell_price, "avg_entry": avg_entry, "qty_closed": qty_closed, "pnl_eur": pnl_eur,
                "eur_free": eur_free_now, "base_free": base_free_now,
                "pos_qty_after": st.pos_qty, "cash_eur_after": st.cash_eur, "equity_after": equity_after,
                "wins": st.wins, "pnl_pos_sum": st.pnl_sum_pos, "pnl_neg_sum": st.pnl_sum_neg,
            },
        )

    def _best_limit_for(side: str, mid_price: float) -> float:
        if not aggr_limit:
            # лимит с учётом «скольжения» от текущей цены
            if side == "buy":
                return mid_price * (1.0 + slip_r)
            else:
                return mid_price * (1.0 - slip_r)

        bid, ask = ob_client.best_quotes(pair)
        if side == "buy":
            # чтобы исполнилось сразу: лимит ≥ лучшей аски
            base_px = ask if ask is not None else mid_price
            return base_px + aggr_ticks * (pair_settings["price_tick"] or 0.0)
        else:
            # чтобы исполнилось сразу: лимит ≤ лучшего бида
            base_px = bid if bid is not None else mid_price
            return base_px - aggr_ticks * (pair_settings["price_tick"] or 0.0)

    def _wait_and_cancel_if_needed(oid: str, timeout_sec: float) -> Tuple[bool, float, float]:
        """
        Ожидаем исполнения FOK-стилем: если за timeout_sec не исполнилось полностью —
        отменяем и возвращаем (filled?, filled_qty, filled_avg_price).
        """
        t0 = time.time()
        filled_qty = 0.0
        filled_cost = 0.0
        while time.time() - t0 < max(0.5, float(timeout_sec)):
            try:
                stt = exmo.order_trades(oid)  # предполагается метод: список сделок по ордеру
                # если есть частичка — суммируем
                fq = 0.0
                fc = 0.0
                for tr in stt or []:
                    q = float(tr.get("quantity", 0.0))
                    p = float(tr.get("price", 0.0))
                    fq += q
                    fc += q * p
                if fq > 0:
                    filled_qty = fq
                    filled_cost = fc
                # проверим статус ордера
                info = exmo.order_status(oid)  # предполагается метод
                if str(info.get("status", "")).lower() in ("cancelled", "canceled", "done", "filled", "closed"):
                    break
                # если полностью исполнен
                q_orig = float(info.get("quantity", 0.0))
                q_rest = float(info.get("quantity_remaining", 0.0))
                if q_orig > 0 and q_rest <= 1e-12:
                    break
            except Exception:
                pass
            time.sleep(0.25)

        # отменяем, если не похоже на полностью исполненный
        try:
            info = exmo.order_status(oid)
            q_orig = float(info.get("quantity", 0.0))
            q_rest = float(info.get("quantity_remaining", 0.0))
            if q_orig > 0 and q_rest <= 1e-12:
                # полностью
                fq = max(filled_qty, q_orig) if filled_qty <= 0 else filled_qty
                fc = max(filled_cost, fq * float(info.get("price", 0.0)))
                return True, fq, (fc / max(fq, 1e-9))
        except Exception:
            pass

        try:
            exmo.order_cancel(oid)
        except Exception:
            pass
        return False, filled_qty, (filled_cost / max(filled_qty, 1e-9) if filled_qty > 0 else 0.0)

    def _place_limit(
        side: str,
        lim_price: float,
        qty_base: float,
        note: str = "",
        client_id_prefix: str = "",
        tries: int = 0,
    ) -> Tuple[str, str]:
        """
        Размещаем лимитный ордер. Возвращаем (oid, status_str).
        Строго целочисленный client_id, как просила EXMO (исправляет 50249).
        """
        # client_id: YYYYMMDDhhmmss + короткий хвост
        nowi = int(datetime.now(timezone.utc).timestamp())
        cid_int = int(f"{nowi}{np.random.randint(100,999)}")

        lim_qp, lim_qq = _quantize(lim_price, qty_base)
        if lim_qq <= 0:
            return "", f"skip {side}: qty={qty_base:.8f} < step"

        params_note = f"{note}".strip()
        try:
            resp = exmo.order_create(
                pair=pair,
                quantity=str(lim_qq),
                price=str(lim_qp),
                side=side,
                client_id=cid_int,  # Строго число!
            )
            oid = str(resp.get("result", {}).get("order_id") or resp.get("order_id") or "")
            if not oid:
                return "", f"rejected {side}: no order_id"
            return oid, f"placed lim={lim_qp} qty={lim_qq} {params_note}"
        except Exception as e:
            return "", f"error place {side}: {e}"

    # --- Основной цикл лайва ---
    last_ts = None
    next_hb = time.time() + max(heartbeat_sec, 0)

    # стартовый вход, если нужно
    pending_forced = force_entry.strip().lower() if force_entry else ""

    try:
        while True:
            # 1) загрузка свечей
            df = fetch_exmo_candles(pair, span, verbose=False)
            if df.empty:
                time.sleep(poll)
                continue
            if resample_rule:
                df = resample_ohlcv(df, resample_rule)
            if "time" not in df.columns:
                # интеграции всегда должны отдавать колонку time
                time.sleep(poll)
                continue

            # 2) сигналы SMA
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

            regime = "LONG" if fc >= sc else "FLAT"
            signal = "none"
            if fp <= sp and fc > sc:
                signal = "buy"
            elif fp >= sp and fc < sc:
                signal = "sell"

            # форс-вход/выход (однократно)
            if pending_forced in ("buy", "sell"):
                signal = pending_forced
                pending_forced = ""

            # 3) торговые действия
            note = ""
            if signal == "buy":
                # если align_on_state и уже в LONG — не дублируем вход
                if align_on_state and st.pos_qty > 0:
                    note = "[align]"
                    # ничего не делаем
                else:
                    # считаем EUR для входа
                    eq_now = _equity(c)
                    eur_to_use = qty_eur if qty_eur > 0 else (eq_now * max(position_pct, 0.0) / 100.0)
                    # >= min_quote
                    if eur_to_use >= max(0.0, min_quote):
                        lim = _best_limit_for("buy", c)
                        # попытки репрайсинга
                        placed = False
                        status_text = ""
                        for k in range(int(reprice_attempts) + 1):
                            use_lim = lim * (1.0 + k * reprice_step_r)
                            q_base = eur_to_use / use_lim
                            oid, stx = _place_limit("buy", use_lim, q_base, note=note, client_id_prefix="B", tries=k)
                            status_text = stx
                            if oid:
                                filled, fq, favg = _wait_and_cancel_if_needed(oid, fok_wait_sec)
                                if filled and fq > 0:
                                    # учёт комиссии: уменьшаем на fee_r
                                    cost = fq * favg * (1.0 + fee_r)
                                    st.avg_price = (st.pos_qty * st.avg_price + cost) / max(st.pos_qty + fq, 1e-9)
                                    st.pos_qty += fq
                                    st.cash_eur -= cost
                                    tss = ts.isoformat()
                                    _append_trade(tss, "BUY", favg, fq, note.strip())
                                    eq = _equity(c)
                                    _append_equity(tss, eq)
                                    print(f"[trade] buy[{k+1}/{reprice_attempts+1}] oid={oid} -> filled lim={use_lim:.6f} qty={fq:.6f} {'ob' if aggr_limit else ''}  {note}")
                                    placed = True
                                    break
                                else:
                                    print(f"[trade] buy[{k+1}/{reprice_attempts+1}] oid={oid} -> cancelled lim={use_lim:.6f} qty={q_base:.6f} slip={((use_lim/c)-1.0)*1e4:.1f}bps {note}")
                            else:
                                print(f"[trade] {status_text}")
                        if not placed:
                            pass  # не вошли — ок

            elif signal == "sell":
                # продавать есть ли что
                if st.pos_qty > 0:
                    # если align_on_state выключен — выходим сразу;
                    # если включён — выходим (сигнал sell как раз на выход)
                    q_to_sell = st.pos_qty
                    lim = _best_limit_for("sell", c)
                    placed = False
                    for k in range(int(reprice_attempts) + 1):
                        use_lim = lim * (1.0 - k * reprice_step_r)
                        oid, stx = _place_limit("sell", use_lim, q_to_sell, note=note, client_id_prefix="S", tries=k)
                        if oid:
                            filled, fq, favg = _wait_and_cancel_if_needed(oid, fok_wait_sec)
                            if filled and fq > 0:
                                # комиссия
                                proceeds = fq * favg * (1.0 - fee_r)
                                qty_closed = fq
                                pnl = proceeds - (qty_closed * st.avg_price)

                                st.round_trips += 1
                                if pnl >= 0:
                                    st.wins += 1
                                    st.pnl_sum_pos += pnl
                                else:
                                    st.pnl_sum_neg += pnl

                                st.pos_qty -= qty_closed
                                if st.pos_qty < (qty_step or 0.0) - 1e-12:
                                    # считаем «пыль» не торгуемой
                                    dust = max(0.0, st.pos_qty)
                                    if dust > 0.0:
                                        print(f"[trade] dust leftover {dust:.6f} < step={qty_step}, marking FLAT.")
                                    st.pos_qty = 0.0
                                    st.avg_price = 0.0

                                st.cash_eur += proceeds
                                tss = ts.isoformat()
                                _append_trade(tss, "SELL", favg, fq, note.strip())
                                eq = _equity(c)
                                # снимок кошелька (EUR_free/BASE_free) после сделки
                                try:
                                    acc2 = exmo.user_info()
                                    eur_free2 = float(acc2.get("balances", {}).get("EUR", 0.0))
                                    base_free2 = float(acc2.get("balances", {}).get(base, 0.0))
                                except Exception:
                                    eur_free2 = eur_free
                                    base_free2 = base_free

                                _append_balance_close(
                                    tss, "sell", favg, st.avg_price if st.pos_qty > 0 else 0.0,
                                    qty_closed, pnl, eur_free2, base_free2, eq,
                                )
                                _append_equity(tss, eq)

                                print(
                                    f"[trade] closed rt={st.round_trips} qty={qty_closed:.6f} sell={favg:.6f} "
                                    f"avg={max(st.avg_price,0.0):.6f} pnl={pnl:.6f} EUR  |  "
                                    f"balances: EUR_free={eur_free2:.6f}, {base}_free={base_free2:.6f}, equity≈{eq:.2f}"
                                )
                                placed = True
                                break
                            else:
                                print(f"[trade] sell[{k+1}/{reprice_attempts+1}] oid={oid} -> cancelled lim={use_lim:.6f} qty={q_to_sell:.6f}")
                        else:
                            print(f"[trade] {stx}")
                    if not placed:
                        pass

            # 4) регулярные отчёты/сохранение
            tss = ts.isoformat()
            eq = _equity(c)
            if heartbeat_sec > 0 and time.time() >= next_hb:
                # реал/нереал PnL (грубый подсчёт)
                unreal = (c - st.avg_price) * st.pos_qty if st.pos_qty > 0 else 0.0
                real_sum = st.pnl_sum_pos + st.pnl_sum_neg
                print(
                    f"[trade] {tss} hb equity={eq:.2f} pos={st.pos_qty:.6f} "
                    f"pnl_real={real_sum:.4f} pnl_unreal={unreal:.4f} rt={st.round_trips} "
                    f"win_rate={(100.0*st.wins/max(1, st.round_trips)):.2f}% pf={'∞' if st.pnl_sum_neg==0 else (st.pnl_sum_pos/abs(st.pnl_sum_neg)):.2f}"
                )
                next_hb = time.time() + heartbeat_sec
            # сохраняем стейт и текущую equity на каждом тике (последняя перезапись equity не страшна)
            _append_equity(tss, eq)
            st.save(STATE_PATH)

            time.sleep(poll)

    except KeyboardInterrupt:
        print("[trade] stopped.")
        # финальный отчёт
        eq = st.cash_eur + st.pos_qty * (c if 'c' in locals() else 0.0)
        rt = st.round_trips
        wr = (100.0 * st.wins / max(1, rt))
        pf = (st.pnl_sum_pos / abs(st.pnl_sum_neg)) if st.pnl_sum_neg != 0 else float("inf")
        print(f"[live-report] equity≈{eq:.6f}  rt={rt}  win_rate={wr:.2f}%  pf={'∞' if pf==float('inf') else f'{pf:.2f}'}")
