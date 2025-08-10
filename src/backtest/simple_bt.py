# src/backtest/simple_bt.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import List, Dict, Any, Tuple, Optional

getcontext().prec = 50  # высокая точность для денег


@dataclass
class BtConfig:
    fast: int = 10
    slow: int = 30
    fee_bps: Decimal = Decimal("10")    # 10 bps = 0.1%
    size_quote: Decimal = Decimal("100")  # размер на сделку в котируемой валюте


@dataclass
class BtTrade:
    ts: int
    side: str  # "buy"/"sell"
    price: Decimal
    qty_base: Decimal
    fee_quote: Decimal


@dataclass
class BtResult:
    pair: str
    tf: str
    cfg: BtConfig
    trades: List[BtTrade]
    equity: List[Tuple[int, Decimal]]  # (ts, equity_quote)
    total_pnl: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    fees_quote: Decimal
    position_base: Decimal
    avg_cost: Optional[Decimal]


def _sma(values: List[Decimal], win: int) -> List[Optional[Decimal]]:
    out: List[Optional[Decimal]] = [None] * len(values)
    if win <= 0:
        return out
    s = Decimal("0")
    for i, v in enumerate(values):
        s += v
        if i >= win:
            s -= values[i - win]
        if i >= win - 1:
            out[i] = s / Decimal(win)
    return out


def backtest_sma(
    pair: str,
    tf: str,
    ohlcv: List[Dict[str, Any]],
    cfg: BtConfig,
) -> BtResult:
    """
    ohlcv: [{'ts': int, 'open': '...', 'high': '...', 'low': '...', 'close': '...', 'volume': '...'}, ...]
    """
    closes: List[Decimal] = [Decimal(str(r["close"])) for r in ohlcv]
    ts_list: List[int] = [int(r["ts"]) for r in ohlcv]

    sma_f = _sma(closes, cfg.fast)
    sma_s = _sma(closes, cfg.slow)

    in_pos = False
    pos_qty = Decimal("0")
    pos_cost = Decimal("0")   # суммарные затраты в quote
    trades: List[BtTrade] = []
    equity: List[Tuple[int, Decimal]] = []
    realized = Decimal("0")
    fees_q = Decimal("0")

    fee_rate = cfg.fee_bps / Decimal("10000")

    for i in range(len(closes)):
        price = closes[i]
        ts = ts_list[i]
        fast = sma_f[i]
        slow = sma_s[i]

        # обновим equity (mark-to-market)
        mtm = (pos_qty * price) + realized
        equity.append((ts, mtm))

        if fast is None or slow is None:
            continue

        # сигналы: пересечение fast/slow
        cross_up = (sma_f[i - 1] is not None and sma_s[i - 1] is not None
                    and sma_f[i - 1] <= sma_s[i - 1] and fast > slow)
        cross_dn = (sma_f[i - 1] is not None and sma_s[i - 1] is not None
                    and sma_f[i - 1] >= sma_s[i - 1] and fast < slow)

        # BUY
        if cross_up and not in_pos:
            quote_to_spend = cfg.size_quote
            qty = (quote_to_spend / price)
            fee = quote_to_spend * fee_rate
            trades.append(BtTrade(ts=ts, side="buy", price=price, qty_base=qty, fee_quote=fee))
            in_pos = True
            pos_qty += qty
            pos_cost += quote_to_spend + fee  # стоимость позиции с комиссией
            fees_q += fee

        # SELL
        elif cross_dn and in_pos:
            notional = pos_qty * price
            fee = notional * fee_rate
            trades.append(BtTrade(ts=ts, side="sell", price=price, qty_base=pos_qty, fee_quote=fee))
            realized += (notional - fee) - pos_cost
            fees_q += fee
            in_pos = False
            pos_qty = Decimal("0")
            pos_cost = Decimal("0")

    # закрытие на последней цене (не исполняем сделку, просто считаем нереализ)
    last_price = closes[-1] if closes else Decimal("0")
    unrealized = pos_qty * last_price
    total = realized + unrealized

    avg_cost: Optional[Decimal] = None
    if in_pos and pos_qty > 0:
        avg_cost = pos_cost / pos_qty

    return BtResult(
        pair=pair,
        tf=tf,
        cfg=cfg,
        trades=trades,
        equity=equity,
        total_pnl=total,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        fees_quote=fees_q,
        position_base=pos_qty,
        avg_cost=avg_cost,
    )


def save_trades_csv(trades: List[BtTrade], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("ts,side,price,qty_base,fee_quote\n")
        for t in trades:
            f.write(f"{t.ts},{t.side},{t.price},{t.qty_base},{t.fee_quote}\n")


def save_equity_csv(equity: List[Tuple[int, Decimal]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("ts,equity_quote\n")
        for ts, eq in equity:
            f.write(f"{ts},{eq}\n")
