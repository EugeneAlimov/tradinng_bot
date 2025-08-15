# -*- coding: utf-8 -*-
from typing import List, Dict, Tuple
from dataclasses import dataclass
from .resample import normalize_row
from src.strategies.sma import Bar, SmaCross, Signal

@dataclass
class ExecParams:
    fee_bps: float = 10.0
    slip_bps: float = 2.0
    start_eur: float = 1_000.0
    risk_f: float = 0.0      # доля кэша на вход; если 0 — используем qty_eur
    qty_eur: float = 100.0   # фикс. сумма входа

@dataclass
class Stops:
    sl_bps: float = 0.0
    tp_bps: float = 0.0

def _bar_from_row(r: Dict) -> Bar:
    n = normalize_row(r)
    return Bar(n["ts"], n["o"], n["h"], n["l"], n["c"], n["v"])

def backtest_sma(rows: List[Dict], fast: int, slow: int,
                 execp: ExecParams, stops: Stops
                 ) -> Tuple[List[Dict], List[Dict], Dict]:
    """
    Возврат:
      trades: [{side, ts_in, px_in, ts_out, px_out, pnl_eur}]
      markers: [{ts, price, kind}]
      stats: dict
    """
    if not rows: return [], [], {}

    strat = SmaCross(fast, slow)
    FEE = execp.fee_bps / 1e4
    SLIP = execp.slip_bps / 1e4

    cash = execp.start_eur
    qty  = 0.0
    entry_px = None
    entry_ts = None

    trades: List[Dict] = []
    markers: List[Dict] = []

    for i, r in enumerate(rows):
        b = _bar_from_row(r)
        sig = strat.on_bar(b)

        # стоп/тейк активны только если есть позиция
        if qty > 0.0 and entry_px is not None:
            hit_price = None
            hit_kind  = None
            if stops.tp_bps > 0:
                tp = entry_px * (1 + stops.tp_bps/1e4)
                if b.h >= tp:
                    hit_price, hit_kind = tp, "take"
            if hit_price is None and stops.sl_bps > 0:
                sl = entry_px * (1 - stops.sl_bps/1e4)
                if b.l <= sl:
                    hit_price, hit_kind = sl, "stop"
            if hit_price is not None:
                # исполнение выхода
                px_exec = hit_price * (1 - SLIP)
                amount = qty * px_exec
                fee = amount * FEE
                cash += (amount - fee)
                trades.append({"side":"sell","ts_in":entry_ts,"px_in":entry_px,
                               "ts_out":b.ts,"px_out":px_exec,"pnl_eur": (amount-fee) - (entry_px*(1+SLIP)*qty) - (entry_px*(1+SLIP)*qty*FEE)})
                markers.append({"ts": b.ts, "price": px_exec, "kind": hit_kind})
                qty = 0.0; entry_px=None; entry_ts=None
                strat.in_position = False  # принудительно

        # вход/выход по сигналу
        if sig:
            if sig.side == "buy" and qty == 0.0:
                px = b.c * (1 + SLIP)
                budget = execp.qty_eur if execp.risk_f <= 0 else cash * execp.risk_f
                if budget > 0 and cash >= budget:
                    fee = budget * FEE
                    got = (budget - fee) / px
                    qty += got
                    cash -= budget
                    entry_px = px
                    entry_ts = b.ts
                    markers.append({"ts": b.ts, "price": px, "kind": "buy"})
            elif sig.side == "sell" and qty > 0.0:
                px = b.c * (1 - SLIP)
                amount = qty * px
                fee = amount * FEE
                cash += (amount - fee)
                trades.append({"side":"sell","ts_in":entry_ts,"px_in":entry_px,
                               "ts_out":b.ts,"px_out":px,"pnl_eur": (amount-fee) - (entry_px*(1+SLIP)*qty) - (entry_px*(1+SLIP)*qty*FEE)})
                markers.append({"ts": b.ts, "price": px, "kind": "sell"})
                qty = 0.0; entry_px=None; entry_ts=None

    # закрыть по последнему бару (если нужно) — опционально, тут оставим открытую позицию как есть
    equity = cash + (qty * rows[-1]["c"] if qty>0 else 0.0)
    stats = {"cash": round(cash, 6), "qty": qty, "equity": round(equity, 6), "n_trades": len(trades)}
    return trades, markers, stats
