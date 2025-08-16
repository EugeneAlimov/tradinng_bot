# src/analytics/pnl.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import List, Dict, Any, Tuple

getcontext().prec = 50


@dataclass
class PnLSummary:
    pair: str
    trades_total: int
    buys: int
    sells: int
    inventory_base: Decimal
    avg_cost: Decimal | None
    last_price: Decimal
    notional_quote: Decimal
    realized_pnl_quote: Decimal
    unrealized_pnl_quote: Decimal
    total_pnl_quote: Decimal
    fees_quote_converted: Decimal
    base_fees_total: Decimal


def _d(x: Any) -> Decimal:
    return Decimal(str(x))


def _trade_key(ts: Any, tid: Any) -> Tuple[int, int]:
    try:
        return int(ts), int(tid)
    except Exception:
        return int(ts or 0), int(tid or 0)


def _quote_ccy(pair: str) -> str:
    return pair.split("_", 1)[1].upper()


def compute_pnl_with_ledger(pair: str, trades: List[Dict[str, Any]], last_price: Decimal) -> Tuple[
    PnLSummary, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Возвращает:
      summary — агрегаты
      ledger  — построчный разбор (FIFO, на каждой продаже считаем realized)
      equity  — эквити-кривая по времени (ts, equity_quote)
    Ожидается формат EXMO user_trades.
    """
    qccy = _quote_ccy(pair)

    # сортируем сделки по времени и trade_id (стабильно)
    tsorted = sorted(trades, key=lambda t: _trade_key(t.get("date"), t.get("trade_id")))

    # FIFO лоты: список (qty_left, price)
    lots: List[Tuple[Decimal, Decimal]] = []

    buys = sells = 0
    inv_base = Decimal("0")
    realized = Decimal("0")
    fees_quote = Decimal("0")
    fees_base_sum = Decimal("0")

    ledger: List[Dict[str, Any]] = []
    equity: List[Dict[str, Any]] = []

    # хелпер для средневзвешенной
    def current_avg_cost() -> Decimal | None:
        if inv_base <= 0:
            return None
        cost = Decimal("0")
        qty = Decimal("0")
        for q, p in lots:
            cost += q * p
            qty += q
        if qty <= 0:
            return None
        return cost / qty

    for t in tsorted:
        ttype = (t.get("type") or "").lower()
        qty = _d(t.get("quantity", "0"))
        px = _d(t.get("price", "0"))
        amt = _d(t.get("amount", "0"))  # в котируемой валюте
        fee_amt = _d(t.get("commission_amount", "0"))
        fee_ccy = (t.get("commission_currency") or "").upper()
        ts = int(t.get("date") or 0)

        # учёт комиссий
        if fee_ccy == qccy:
            fees_quote += fee_amt
        else:
            # комиссия списана в базовой монете
            fees_base_sum += fee_amt

        realized_row = Decimal("0")
        avg_before = current_avg_cost()

        if ttype == "buy":
            buys += 1
            inv_base += qty
            lots.append((qty, px))
        elif ttype == "sell":
            sells += 1
            inv_base -= qty
            # снимаем с FIFO-лотов и считаем realized
            remaining = qty
            fifo_cost = Decimal("0")
            while remaining > 0 and lots:
                lot_qty, lot_px = lots[0]
                use = min(remaining, lot_qty)
                fifo_cost += use * lot_px
                lot_qty -= use
                remaining -= use
                if lot_qty > 0:
                    lots[0] = (lot_qty, lot_px)
                else:
                    lots.pop(0)
            # realized = cash_in - cost (комиссию в quote вычтем в конце суммарно)
            realized_inc = (qty * px) - fifo_cost
            realized += realized_inc
            realized_row = realized_inc
        else:
            # неизвестный тип — пропускаем
            pass

        avg_after = current_avg_cost()
        notional = inv_base * last_price
        unreal = notional - sum(q * p for q, p in lots)  # mark-to-market против остаточной себестоимости
        total = realized + unreal

        row = {
            "ts": ts,
            "type": ttype,
            "qty": str(qty),
            "price": str(px),
            "amount_quote": str(amt),
            "realized_step": str(realized_row),
            "inventory_base": str(inv_base),
            "avg_cost_before": (str(avg_before) if avg_before is not None else None),
            "avg_cost_after": (str(avg_after) if avg_after is not None else None),
            "realized_cum": str(realized),
        }
        ledger.append(row)

        equity.append({
            "ts": ts,
            "inventory_base": str(inv_base),
            "last_price": str(last_price),
            "equity_quote": str(total),
            "realized": str(realized),
        })

    # итоговые агрегаты
    avg_cost = None
    if inv_base > 0:
        # средневзвешенная по остаточным лотам
        cost = sum(q * p for q, p in lots)
        qty = sum(q for q, _ in lots)
        if qty > 0:
            avg_cost = cost / qty
    notional = inv_base * last_price
    # конвертируем base-комиссии в «эквивалент квоты» по текущей цене
    fees_quote_conv = fees_quote + (fees_base_sum * last_price)
    unrealized = notional - sum(q * p for q, p in lots)
    total = realized + unrealized - fees_quote  # fees_quote уже в realized не завёрстаны
    # Минусовать ли fees_quote_conv из total — вопрос вкуса.
    # Оставим в summary обе цифры: total без fee-конверсии и отдельное поле fees_quote_converted.

    summary = PnLSummary(
        pair=pair,
        trades_total=len(tsorted),
        buys=buys,
        sells=sells,
        inventory_base=inv_base,
        avg_cost=avg_cost,
        last_price=last_price,
        notional_quote=notional,
        realized_pnl_quote=realized - fees_quote,  # вычитаем известные quote fee
        unrealized_pnl_quote=unrealized,
        total_pnl_quote=(realized - fees_quote) + unrealized,
        fees_quote_converted=fees_quote_conv,
        base_fees_total=fees_base_sum,
    )
    return summary, ledger, equity


def compute_pnl(pair: str, trades: List[Dict[str, Any]], last_price: Decimal) -> PnLSummary:
    summary, _, _ = compute_pnl_with_ledger(pair, trades, last_price)
    return summary
