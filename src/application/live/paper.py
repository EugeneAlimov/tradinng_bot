# src/application/live/paper.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from src.domain.risk.risk_service import RiskService


@dataclass
class TradeRec:
    entry_ts: int
    entry_px: float
    exit_ts: int
    exit_px: float
    qty: float
    pnl: float
    ret: float


@dataclass
class PaperConfig:
    initial_balance: float = 1000.0
    fee_bps: int = 10
    slip_bps: int = 2
    max_position_pct: Optional[float] = 0.25  # 0..1
    stop_loss_bps: Optional[int] = 300  # e.g. 300 = 3.0%
    max_daily_loss_bps: Optional[int] = None  # daily kill-switch


@dataclass
class PaperState:
    cash: float
    qty: float
    avg_entry_px: float
    day_start_equity: float
    day_ymd: Tuple[int, int, int]


class PaperEngine:
    """
    Long-only симулятор с комиссиями/проскальзыванием, стопами и дневным лимитом.
    Торгуем на закрытии последней ЗАКРЫТОЙ свечи (i-1), без look-ahead.
    """

    def __init__(self, cfg: PaperConfig, risk: RiskService, snapshot: Optional[Dict[str, Any]] = None):
        self.cfg = cfg
        self.risk = risk
        self.state = PaperState(
            cash=float(cfg.initial_balance),
            qty=0.0,
            avg_entry_px=0.0,
            day_start_equity=float(cfg.initial_balance),
            day_ymd=(1970, 1, 1),
        )
        self.trades: List[TradeRec] = []
        self.equity_steps: List[Tuple[int, float]] = []
        self.last_processed_ts: Optional[int] = None
        if snapshot:
            self.restore(snapshot)

    # ---- helpers

    @property
    def fee(self) -> float:
        return self.cfg.fee_bps / 1e4

    @property
    def slip(self) -> float:
        return self.cfg.slip_bps / 1e4

    def _fill_buy(self, px: float) -> float:
        return px * (1.0 + self.slip) * (1.0 + self.fee)

    def _fill_sell(self, px: float) -> float:
        return px * (1.0 - self.slip) * (1.0 - self.fee)

    def _equity(self, mkt_px: float) -> float:
        return self.state.cash + self.state.qty * mkt_px

    def _ymd(self, ts: int) -> Tuple[int, int, int]:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return (dt.year, dt.month, dt.day)

    def _roll_day_if_needed(self, ts: int, mkt_px: float):
        ymd = self._ymd(ts)
        if ymd != self.state.day_ymd:
            self.state.day_ymd = ymd
            self.state.day_start_equity = self._equity(mkt_px)

    def _daily_loss_exceeded(self, mkt_px: float) -> bool:
        if not self.cfg.max_daily_loss_bps:
            return False
        eq = self._equity(mkt_px)
        max_loss = self.cfg.max_daily_loss_bps / 1e4
        return (eq - self.state.day_start_equity) <= -abs(self.state.day_start_equity) * max_loss

    def _stoploss_hit(self, close_px: float) -> bool:
        if self.state.qty <= 0 or not self.cfg.stop_loss_bps or self.state.avg_entry_px <= 0:
            return False
        stop = self.state.avg_entry_px * (1.0 - self.cfg.stop_loss_bps / 1e4)
        return close_px <= stop

    # ---- actions

    def _open_long(self, px: float, ts: int):
        if self.state.qty > 0:
            return
        fill = self._fill_buy(px)
        equity = self._equity(px)
        target_pct = self.cfg.max_position_pct if self.cfg.max_position_pct is not None else 1.0
        target_pct = max(0.0, min(1.0, target_pct))
        target_value = equity * target_pct
        qty = 0.0 if fill <= 0 else target_value / fill
        # ограничим кэшем
        if qty * fill > self.state.cash:
            qty = self.state.cash / fill if fill > 0 else 0.0
        if qty <= 0:
            return
        self.state.cash -= qty * fill
        self.state.avg_entry_px = fill
        self.state.qty += qty

    def _close_long(self, px: float, ts: int):
        if self.state.qty <= 0:
            return
        fill = self._fill_sell(px)
        qty = self.state.qty
        proceeds = qty * fill
        entry_val = qty * self.state.avg_entry_px
        pnl = proceeds - entry_val
        ret = (pnl / entry_val) if entry_val > 0 else 0.0
        self.state.cash += proceeds
        self.trades.append(TradeRec(
            entry_ts=self.last_processed_ts if self.last_processed_ts is not None else ts,
            entry_px=self.state.avg_entry_px,
            exit_ts=ts,
            exit_px=fill,
            qty=qty,
            pnl=pnl,
            ret=ret,
        ))
        self.state.qty = 0.0
        self.state.avg_entry_px = 0.0

    # ---- main step

    def on_new_closed_bar(self, ts: int, open_px: float, high_px: float, low_px: float, close_px: float,
                          signal: int) -> Optional[Tuple[int, float]]:
        if self.last_processed_ts is not None and ts <= self.last_processed_ts:
            return None

        self._roll_day_if_needed(ts, close_px)

        # safety сначала
        if self._stoploss_hit(close_px):
            self._close_long(close_px, ts)
            equity = self._equity(close_px)
            self.equity_steps.append((ts, equity))
            self.last_processed_ts = ts
            return (-1, equity)

        if self._daily_loss_exceeded(close_px):
            if signal <= 0 and self.state.qty > 0:
                self._close_long(close_px, ts)
                equity = self._equity(close_px)
                self.equity_steps.append((ts, equity))
                self.last_processed_ts = ts
                return (-1, equity)
            equity = self._equity(close_px)
            self.equity_steps.append((ts, equity))
            self.last_processed_ts = ts
            return (0, equity)

        if signal > 0 and self.state.qty <= 0:
            self._open_long(close_px, ts)
            equity = self._equity(close_px)
            self.equity_steps.append((ts, equity))
            self.last_processed_ts = ts
            return (+1, equity)

        if signal < 0 and self.state.qty > 0:
            self._close_long(close_px, ts)
            equity = self._equity(close_px)
            self.equity_steps.append((ts, equity))
            self.last_processed_ts = ts
            return (-1, equity)

        equity = self._equity(close_px)
        self.equity_steps.append((ts, equity))
        self.last_processed_ts = ts
        return (0, equity)

    # ---- persistence

    def snapshot(self) -> Dict[str, Any]:
        return {
            "cfg": {
                "initial_balance": self.cfg.initial_balance,
                "fee_bps": self.cfg.fee_bps,
                "slip_bps": self.cfg.slip_bps,
                "max_position_pct": self.cfg.max_position_pct,
                "stop_loss_bps": self.cfg.stop_loss_bps,
                "max_daily_loss_bps": self.cfg.max_daily_loss_bps,
            },
            "state": asdict(self.state),
            "trades": [asdict(t) for t in self.trades],
            "equity": [(int(ts), float(eq)) for ts, eq in self.equity_steps],
            "last_ts": self.last_processed_ts,
        }

    def restore(self, snap: Dict[str, Any]) -> None:
        s = snap.get("state") or {}
        self.state = PaperState(
            cash=float(s.get("cash", self.cfg.initial_balance)),
            qty=float(s.get("qty", 0.0)),
            avg_entry_px=float(s.get("avg_entry_px", 0.0)),
            day_start_equity=float(s.get("day_start_equity", self.cfg.initial_balance)),
            day_ymd=tuple(s.get("day_ymd", (1970, 1, 1))),  # type: ignore[call-arg]
        )
        self.trades = []
        for t in snap.get("trades", []):
            self.trades.append(TradeRec(
                entry_ts=int(t["entry_ts"]),
                entry_px=float(t["entry_px"]),
                exit_ts=int(t["exit_ts"]),
                exit_px=float(t["exit_px"]),
                qty=float(t["qty"]),
                pnl=float(t["pnl"]),
                ret=float(t["ret"]),
            ))
        self.equity_steps = [(int(ts), float(eq)) for ts, eq in snap.get("equity", [])]
        self.last_processed_ts = snap.get("last_ts", None)

    # ---- exports

    def export_trades(self) -> List[Dict[str, Any]]:
        return [{
            "entry_ts": t.entry_ts,
            "entry": round(t.entry_px, 10),
            "exit_ts": t.exit_ts,
            "exit": round(t.exit_px, 10),
            "qty": round(t.qty, 10),
            "pnl": round(t.pnl, 10),
            "ret": round(t.ret, 10),
        } for t in self.trades]

    def export_equity(self) -> List[Tuple[int, float]]:
        return [(ts, float(eq)) for ts, eq in self.equity_steps]
