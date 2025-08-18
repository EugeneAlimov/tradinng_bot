from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Any, Optional, Sequence, Tuple, Literal, Protocol

from src.core.domain.models import TradingPair, OrderRequest, Side, TradeFill
from src.core.ports.market_data import MarketDataPort
from src.core.ports.exchange import ExchangePort
from src.core.ports.storage import StoragePort
from src.core.ports.notify import NotifierPort

Signal = Literal["BUY", "SELL", "HOLD"]

# Стратегии
from src.domain.strategy.mean_reversion import MeanReversion

# Новая SMA-стратегия (если не используешь — импорт можно убрать)
try:
    from src.domain.strategy.sma_crossover import SmaCrossover, SmaCfg
except Exception:  # на случай, если файл ещё не добавлен
    SmaCrossover = None  # type: ignore


@dataclass
class TradeEngine:
    market: MarketDataPort
    exchange: ExchangePort
    storage: StoragePort
    notifier: NotifierPort
    strategy: Any  # MeanReversion | SmaCrossover | др., лишь бы .decide(pair, ctx) был
    positions: Any  # PositionService
    risk: Any  # RiskService

    # Новые параметры для свечей
    candles_timeframe: Optional[str] = "1m"
    candles_lookback: int = 60  # сколько свечей прокидывать в стратегию

    def run_tick(
            self,
            pair: TradingPair,
            *,
            extra_ctx: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Выполняет один «тик»:
          1) Берёт текущую цену
          2) (новое) Подмешивает свечи в ctx, если включено
          3) Запрашивает решение у стратегии
          4) Проверяет риск и исполняет через exchange
          5) Фиксирует fill и обновляет позицию
        """
        price = self.market.get_price(pair)
        ctx: Dict[str, Any] = {
            "last_price": price,
            "client_id": f"paper-{pair.symbol()}",
        }

        # Свечи для стратегий (например, SMA crossover)
        if self.candles_timeframe:
            try:
                candles: Sequence[Tuple[int, Decimal, Decimal, Decimal, Decimal]] = (
                    self.market.get_candles(pair, self.candles_timeframe, self.candles_lookback)
                )
                ctx["candles"] = candles
            except Exception as e:
                self.notifier.warn(f"[candles] fail: {e!r}")

        # Передадим любой внешний контекст (например, индикаторы/флаги)
        if extra_ctx:
            ctx.update(extra_ctx)

        # Решение стратегии
        try:
            signal = self.strategy.decide(pair, ctx)
        except Exception as e:
            self.notifier.error(f"[strategy] error: {e!r}")
            return

        action = (signal or {}).get("action", "HOLD")
        if action == "HOLD":
            self.notifier.info(f"[HOLD] {pair.symbol()} @ {price}")
            return

        # Сайзинг/риск
        sized = self.risk.size(ctx)
        if not sized.get("allow"):
            self.notifier.warn("Risk blocked execution")
            return

        side = Side.BUY if action == "BUY" else Side.SELL
        qty = sized["qty"]
        limit_price = sized.get("limit_price")
        client_id = sized.get("client_id")

        # Создаём запрос и исполняем
        req = OrderRequest(
            pair=pair,
            side=side,
            qty=qty,
            limit_price=limit_price,
            client_id=client_id,
        )
        try:
            order_id = self.exchange.place_order(req)
        except Exception as e:
            self.notifier.error(f"[exec] error: {e!r}")
            return

        # В paper-режиме исполняется мгновенно; создадим fill-представление
        fill = TradeFill(
            order_id=order_id,
            pair=pair,
            qty=qty if side == Side.BUY else -qty,
            price=price,  # фактическая цена может отличаться; для paper_exchange у fill есть своя цена
            ts_ms=0,
        )

        # Лог/хранилище
        try:
            self.storage.append_trade({
                "order_id": order_id,
                "pair": pair.symbol(),
                "side": side.value,
                "qty": str(fill.qty),
                "price": str(price),
                "signal": signal,
            })
        except Exception as e:
            self.notifier.warn(f"[store trade] fail: {e!r}")

        # Обновим позицию
        try:
            pos = self.positions.apply(pair, fill)
            self.notifier.info(
                f"[FILL] {pair.symbol()} {side.value} {fill.qty} @ {price}; "
                f"pos_qty={pos.qty} avg={pos.avg_price}"
            )
        except Exception as e:
            self.notifier.error(f"[position] error: {e!r}")


# ====== протоколы для слабой связности ======
class Strategy(Protocol):
    def generate_signal(
            self,
            price_series: Sequence[float],
            fast_series: Sequence[float],
            slow_series: Sequence[float],
    ) -> Signal: ...


class Exchange(Protocol):
    def place_order(self, side: str, qty: float, price: float) -> bool: ...

    def close_position(self, qty: float, price: float) -> bool: ...

    def position_qty(self) -> float: ...


class PnlCalc(Protocol):
    def pnl_bps(self, entry_price: float, exit_price: float) -> float: ...


class Logger(Protocol):
    def info(self, msg: str) -> None: ...

    def warning(self, msg: str) -> None: ...

    def error(self, msg: str) -> None: ...


# ====== основной класс ======
class TradeEngine:
    """
    Лёгкий движок:
      - cooldown по барам,
      - стоп на новые входы по дневному реализованному убытку (bps),
      - использует стратегию с гистерезисом (внутри стратегии).

    Предполагается, что вычисление SMA (fast/slow) и сбор цен уже сделаны выше по пайплайну
    и сюда приходят готовые линии и цена последнего бара.
    """

    def __init__(
            self,
            exchange: Exchange,
            strategy: Strategy,
            risk_service,
            pnl_calc: Optional[PnlCalc],
            logger: Logger,
            *,
            cooldown_bars: int = 0,
            max_daily_loss_bps: float = 0.0,
    ) -> None:
        self.exchange = exchange
        self.strategy = strategy
        self.risk = risk_service
        self.pnl_calc = pnl_calc
        self.logger = logger

        self.cooldown_bars = max(0, int(cooldown_bars))
        self._cooldown_left = 0
        self.max_daily_loss_bps = float(max_daily_loss_bps or 0.0)

        # опционально, если нужно хранить цену входа/направление
        self._last_entry_price: Optional[float] = None
        self._last_side: Optional[str] = None  # "BUY" (long) / "SELL" (short) если используешь шорт

    # ====== cooldown ======
    def _tick_cooldown(self) -> None:
        if self._cooldown_left > 0:
            self._cooldown_left -= 1

    def _arm_cooldown(self) -> None:
        if self.cooldown_bars > 0:
            self._cooldown_left = self.cooldown_bars

    def _can_trade_now(self) -> bool:
        return self._cooldown_left == 0

    # ====== дневной лимит убытка для НОВЫХ входов ======
    def _can_enter_new_position(self) -> bool:
        if self.max_daily_loss_bps <= 0.0:
            return True
        allow = self.risk.allow_new_entries(self.max_daily_loss_bps)
        if not allow:
            self.logger.warning(
                f"[risk] daily loss limit reached "
                f"({self.risk.get_daily_realized_bps():.1f} bps ≤ -{self.max_daily_loss_bps:.1f} bps). "
                f"New entries blocked."
            )
        return allow

    # ====== исполнение ======
    def _place_order(self, side: str, qty: float, price: float) -> bool:
        ok = self.exchange.place_order(side=side, qty=qty, price=price)
        if ok:
            self._arm_cooldown()
            if side == "BUY":
                self._last_entry_price = price
                self._last_side = "BUY"
        return ok

    def _close_position(self, qty: float, price: float) -> bool:
        ok = self.exchange.close_position(qty=qty, price=price)
        if ok:
            # учтём реализованный PnL
            if self.pnl_calc and self._last_entry_price is not None:
                realized_bps = self.pnl_calc.pnl_bps(self._last_entry_price, price)
                self.risk.add_realized_pnl_bps(realized_bps)
                self.logger.info(f"[pnl] realized {realized_bps:.1f} bps")
            self._arm_cooldown()
            self._last_entry_price = None
            self._last_side = None
        return ok

    # ====== основной вход ======
    def on_new_bar(
            self,
            *,
            price_series: Sequence[float],
            fast_series: Sequence[float],
            slow_series: Sequence[float],
            last_price: float,
            qty: float,
    ) -> None:
        """
        Вызывай на закрытии каждой свечи, когда индикаторы обновились.
        """
        self._tick_cooldown()

        signal = self.strategy.generate_signal(price_series, fast_series, slow_series)
        pos_qty = self.exchange.position_qty()

        # Логика:
        # - BUY => открыть/развернуть в лонг
        # - SELL => закрыть лонг (и/или шорт, если поддерживается)
        # - HOLD => ничего
        if signal == "BUY":
            if pos_qty <= 0:  # нет позиции
                if not self._can_trade_now():
                    self.logger.info(f"[trade] cooldown {self._cooldown_left} bars left; skip BUY")
                    return
                if not self._can_enter_new_position():
                    return
                placed = self._place_order("BUY", qty=qty, price=last_price)
                if placed:
                    self.logger.info(f"[trade] BUY {qty} @ {last_price}")
            else:
                # уже в лонге — HOLD
                pass

        elif signal == "SELL":
            if pos_qty > 0:
                # закрываем лонг (развороты/шорт отключены — минимальные изменения)
                closed = self._close_position(qty=pos_qty, price=last_price)
                if closed:
                    self.logger.info(f"[trade] CLOSE LONG {pos_qty} @ {last_price}")
            else:
                # нет лонга — HOLD (шорт не открываем, чтобы не увеличивать переделки)
                pass

        else:
            # HOLD
            pass
