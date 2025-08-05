from typing import Optional, List, Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum

# Импорты из Core слоя
try:
    from ...core.interfaces import IPositionManager, IPersistenceService
    from ...core.models import (
        Position, Trade, TradingPair, Money, Price,
        OrderResult, OrderType, TradingSession
    )
    from ...core.exceptions import (
        PositionError, PositionNotFoundError, ValidationError,
        DataIntegrityError
    )
    from ...core.events import DomainEvent, publish_event
    from ...config.settings import get_current_config
except ImportError:
    # Fallback для случая если Core слой еще не готов
    class IPositionManager: pass
    class IPersistenceService: pass
    class Position: pass
    class Trade: pass
    class TradingPair: pass
    class Money: pass
    class Price: pass
    class OrderResult: pass
    class OrderType: pass
    class TradingSession: pass
    class PositionError(Exception): pass
    class PositionNotFoundError(Exception): pass
    class ValidationError(Exception): pass
    class DataIntegrityError(Exception): pass
    class DomainEvent: pass
    def publish_event(event): pass
    def get_current_config(): return None


# ================= ТИПЫ ПОЗИЦИЙ =================

class PositionStatus(Enum):
    """📊 Статусы позиций"""
    OPEN = "open"                 # Открыта
    CLOSED = "closed"             # Закрыта
    CLOSING = "closing"           # Закрывается
    SUSPENDED = "suspended"       # Приостановлена


class PositionType(Enum):
    """🎯 Типы позиций"""
    LONG = "long"                 # Длинная позиция
    SHORT = "short"               # Короткая позиция


@dataclass
class PositionSummary:
    """📋 Сводка позиции"""
    currency: str
    quantity: Decimal
    avg_price: Decimal
    current_price: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_percent: float
    cost_basis: Decimal
    last_updated: datetime

    @property
    def is_profitable(self) -> bool:
        """Прибыльная ли позиция"""
        return self.unrealized_pnl > 0

    @property
    def is_empty(self) -> bool:
        """Пустая ли позиция"""
        return self.quantity <= 0


@dataclass
class PortfolioMetrics:
    """📈 Метрики портфеля"""
    total_value: Decimal = Decimal('0')
    total_cost: Decimal = Decimal('0')
    total_pnl: Decimal = Decimal('0')
    total_pnl_percent: float = 0.0
    positions_count: int = 0
    profitable_positions: int = 0
    losing_positions: int = 0
    largest_position_value: Decimal = Decimal('0')
    concentration_risk: float = 0.0  # Доля крупнейшей позиции

    @property
    def win_rate(self) -> float:
        """Процент прибыльных позиций"""
        if self.positions_count == 0:
            return 0.0
        return (self.profitable_positions / self.positions_count) * 100


# ================= ОСНОВНОЙ СЕРВИС =================

class PositionService(IPositionManager):
    """📊 Сервис управления позициями"""

    def __init__(
        self,
        persistence_service: Optional[IPersistenceService] = None
    ):
        self.persistence = persistence_service

        # Текущие позиции (в памяти для быстрого доступа)
        self.positions: Dict[str, Position] = {}

        # Сессия торговли
        self.current_session: Optional[TradingSession] = None

        # Кэш цен для расчетов
        self.price_cache: Dict[str, Price] = {}
        self.cache_ttl = timedelta(minutes=1)

        # Логирование
        self.logger = logging.getLogger(__name__)

        self.logger.info("📊 PositionService инициализирован")

        # Загружаем существующие позиции
        self._load_positions()

    # ================= ОСНОВНЫЕ МЕТОДЫ ИНТЕРФЕЙСА =================

    async def get_position(self, currency: str) -> Optional[Position]:
        """📋 Получение текущей позиции"""

        try:
            currency = currency.upper()

            # Проверяем в памяти
            if currency in self.positions:
                position = self.positions[currency]

                # Обновляем метаданные
                position.updated_at = datetime.now()

                return position

            # Пытаемся загрузить из персистентности
            if self.persistence:
                position = await self.persistence.load_position(currency)
                if position:
                    self.positions[currency] = position
                    return position

            return None

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения позиции {currency}: {e}")
            raise PositionError(f"Ошибка получения позиции {currency}: {e}") from e

    async def get_all_positions(self) -> List[Position]:
        """📋 Получение всех позиций"""

        return [pos for pos in self.positions.values() if not pos.is_empty]

    async def update_position(self, trade: Trade) -> Position:
        """🔄 Обновление позиции после сделки"""

        try:
            currency = trade.pair.base

            # Получаем или создаем позицию
            position = await self.get_position(currency)
            if not position:
                position = Position(
                    currency=currency,
                    quantity=Decimal('0'),
                    avg_price=Decimal('0'),
                    total_cost=Decimal('0')
                )
                self.positions[currency] = position

            # Обновляем позицию
            if trade.order_type == OrderType.BUY:
                await self._handle_buy_trade(position, trade)
            elif trade.order_type == OrderType.SELL:
                await self._handle_sell_trade(position, trade)

            # Сохраняем позицию
            if self.persistence:
                await self.persistence.save_position(position)

            # Публикуем событие
            await self._publish_position_event("position_updated", position, trade)

            self.logger.info(f"📊 Позиция {currency} обновлена: {position.quantity:.6f}")

            return position

        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления позиции: {e}")
            raise PositionError(f"Ошибка обновления позиции: {e}") from e

    async def close_position(self, currency: str, reason: str) -> None:
        """🔒 Закрытие позиции"""

        try:
            position = await self.get_position(currency)
            if not position or position.is_empty:
                raise PositionNotFoundError(currency)

            # Обновляем позицию
            position.quantity = Decimal('0')
            position.updated_at = datetime.now()
            position.metadata['closed_reason'] = reason
            position.metadata['closed_at'] = datetime.now().isoformat()

            # Сохраняем
            if self.persistence:
                await self.persistence.save_position(position)

            # Публикуем событие
            await self._publish_position_event("position_closed", position)

            self.logger.info(f"🔒 Позиция {currency} закрыта: {reason}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка закрытия позиции {currency}: {e}")
            raise PositionError(f"Ошибка закрытия позиции {currency}: {e}") from e

    async def get_portfolio_summary(self) -> Dict[str, Any]:
        """📈 Сводка портфеля"""

        try:
            positions = await self.get_all_positions()
            summaries = []
            metrics = PortfolioMetrics()

            for position in positions:
                # Получаем текущую цену
                current_price = await self._get_current_price(position.currency)
                if not current_price:
                    continue

                # Создаем сводку позиции
                summary = await self._create_position_summary(position, current_price)
                summaries.append(summary)

                # Обновляем метрики портфеля
                self._update_portfolio_metrics(metrics, summary)

            return {
                'positions': [self._summary_to_dict(s) for s in summaries],
                'metrics': self._metrics_to_dict(metrics),
                'last_updated': datetime.now().isoformat(),
                'positions_count': len(summaries)
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения сводки портфеля: {e}")
            raise PositionError(f"Ошибка получения сводки портфеля: {e}") from e

    async def calculate_total_value(self, prices: Dict[str, Decimal]) -> Decimal:
        """💰 Расчет общей стоимости портфеля"""

        total_value = Decimal('0')

        try:
            positions = await self.get_all_positions()

            for position in positions:
                currency = position.currency

                # Используем переданные цены или получаем из кэша
                if currency in prices:
                    current_price = prices[currency]
                else:
                    price_obj = await self._get_current_price(currency)
                    current_price = price_obj.value if price_obj else Decimal('0')

                position_value = position.quantity * current_price
                total_value += position_value

            return total_value

        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета общей стоимости: {e}")
            return Decimal('0')

    async def get_position_history(self, currency: str, days: int = 30) -> List[Position]:
        """📜 История позиций"""

        try:
            if not self.persistence:
                return []

            # Загружаем историю из персистентности
            from_date = datetime.now() - timedelta(days=days)
            trades = await self.persistence.load_trades(currency, from_date)

            # Восстанавливаем историю позиций
            history = self._reconstruct_position_history(trades)

            return history

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения истории позиций {currency}: {e}")
            return []

    # ================= ПРИВАТНЫЕ МЕТОДЫ =================

    async def _handle_buy_trade(self, position: Position, trade: Trade) -> None:
        """🛒 Обработка сделки покупки"""

        old_quantity = position.quantity
        old_cost = position.total_cost

        # Увеличиваем позицию
        new_quantity = old_quantity + trade.quantity
        additional_cost = trade.quantity * trade.price
        new_total_cost = old_cost + additional_cost

        # Пересчитываем среднюю цену
        if new_quantity > 0:
            position.avg_price = new_total_cost / new_quantity

        position.quantity = new_quantity
        position.total_cost = new_total_cost
        position.updated_at = datetime.now()

        # Добавляем сделку в историю
        position.trades.append(trade)

        self.logger.debug(f"🛒 Покупка: {old_quantity:.6f} + {trade.quantity:.6f} = {new_quantity:.6f}")

    async def _handle_sell_trade(self, position: Position, trade: Trade) -> None:
        """💎 Обработка сделки продажи"""

        if position.quantity < trade.quantity:
            self.logger.warning(f"⚠️ Продажа {trade.quantity:.6f} больше позиции {position.quantity:.6f}")

        old_quantity = position.quantity

        # Уменьшаем позицию
        new_quantity = max(Decimal('0'), old_quantity - trade.quantity)

        # Пропорционально уменьшаем общую стоимость
        if old_quantity > 0:
            cost_reduction_ratio = trade.quantity / old_quantity
            cost_reduction = position.total_cost * cost_reduction_ratio
            position.total_cost = max(Decimal('0'), position.total_cost - cost_reduction)

        position.quantity = new_quantity
        position.updated_at = datetime.now()

        # Если позиция закрыта, сбрасываем среднюю цену
        if position.is_empty:
            position.avg_price = Decimal('0')
            position.total_cost = Decimal('0')

        # Добавляем сделку в историю
        position.trades.append(trade)

        self.logger.debug(f"💎 Продажа: {old_quantity:.6f} - {trade.quantity:.6f} = {new_quantity:.6f}")

    async def _get_current_price(self, currency: str) -> Optional[Price]:
        """💰 Получение текущей цены"""

        try:
            # Проверяем кэш
            cache_key = currency
            if cache_key in self.price_cache:
                cached_price = self.price_cache[cache_key]
                if datetime.now() - cached_price.timestamp < self.cache_ttl:
                    return cached_price

            # Здесь должна быть интеграция с market data provider
            # Пока возвращаем заглушку
            price = Price(
                value=Decimal('0.1'),  # Заглушка
                pair=TradingPair.from_string(f"{currency}_EUR"),
                timestamp=datetime.now()
            )

            # Кэшируем цену
            self.price_cache[cache_key] = price

            return price

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения цены {currency}: {e}")
            return None

    async def _create_position_summary(
        self,
        position: Position,
        current_price: Price
    ) -> PositionSummary:
        """📋 Создание сводки позиции"""

        market_value = position.quantity * current_price.value
        unrealized_pnl = market_value - position.total_cost

        unrealized_pnl_percent = 0.0
        if position.total_cost > 0:
            unrealized_pnl_percent = float(unrealized_pnl / position.total_cost * 100)

        return PositionSummary(
            currency=position.currency,
            quantity=position.quantity,
            avg_price=position.avg_price,
            current_price=current_price.value,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_percent=unrealized_pnl_percent,
            cost_basis=position.total_cost,
            last_updated=position.updated_at
        )

    def _update_portfolio_metrics(
        self,
        metrics: PortfolioMetrics,
        summary: PositionSummary
    ) -> None:
        """📈 Обновление метрик портфеля"""

        metrics.total_value += summary.market_value
        metrics.total_cost += summary.cost_basis
        metrics.total_pnl += summary.unrealized_pnl
        metrics.positions_count += 1

        if summary.is_profitable:
            metrics.profitable_positions += 1
        else:
            metrics.losing_positions += 1

        # Обновляем крупнейшую позицию
        if summary.market_value > metrics.largest_position_value:
            metrics.largest_position_value = summary.market_value

        # Рассчитываем общий процент P&L
        if metrics.total_cost > 0:
            metrics.total_pnl_percent = float(metrics.total_pnl / metrics.total_cost * 100)

        # Рассчитываем концентрационный риск
        if metrics.total_value > 0:
            metrics.concentration_risk = float(metrics.largest_position_value / metrics.total_value * 100)

    def _load_positions(self) -> None:
        """📂 Загрузка позиций при инициализации"""

        try:
            # Здесь должна быть логика загрузки из файла или БД
            # Пока создаем пустой словарь
            self.positions = {}
            self.logger.info("📂 Позиции загружены")

        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки позиций: {e}")
            self.positions = {}

    def _reconstruct_position_history(self, trades: List[Trade]) -> List[Position]:
        """🔄 Восстановление истории позиций из сделок"""

        history = []

        # Группируем сделки по валютам
        trades_by_currency = {}
        for trade in trades:
            currency = trade.pair.base
            if currency not in trades_by_currency:
                trades_by_currency[currency] = []
            trades_by_currency[currency].append(trade)

        # Восстанавливаем историю для каждой валюты
        for currency, currency_trades in trades_by_currency.items():
            # Сортируем по времени
            currency_trades.sort(key=lambda t: t.timestamp)

            # Создаем снимки позиции после каждой сделки
            position = Position(
                currency=currency,
                quantity=Decimal('0'),
                avg_price=Decimal('0'),
                total_cost=Decimal('0')
            )

            for trade in currency_trades:
                # Обновляем позицию (упрощенная логика)
                if trade.order_type == OrderType.BUY:
                    new_quantity = position.quantity + trade.quantity
                    new_cost = position.total_cost + trade.total_cost
                    if new_quantity > 0:
                        position.avg_price = new_cost / new_quantity
                    position.quantity = new_quantity
                    position.total_cost = new_cost
                elif trade.order_type == OrderType.SELL:
                    position.quantity = max(Decimal('0'), position.quantity - trade.quantity)
                    if position.quantity == 0:
                        position.avg_price = Decimal('0')
                        position.total_cost = Decimal('0')

                # Создаем снимок
                snapshot = Position(
                    currency=position.currency,
                    quantity=position.quantity,
                    avg_price=position.avg_price,
                    total_cost=position.total_cost,
                    created_at=trade.timestamp,
                    updated_at=trade.timestamp
                )
                history.append(snapshot)

        return history

    async def _publish_position_event(
        self,
        event_type: str,
        position: Position,
        trade: Optional[Trade] = None
    ) -> None:
        """📡 Публикация события позиции"""

        try:
            event = DomainEvent()
            event.event_type = event_type
            event.source = "position_service"
            event.metadata = {
                'currency': position.currency,
                'quantity': str(position.quantity),
                'avg_price': str(position.avg_price),
                'total_cost': str(position.total_cost)
            }

            if trade:
                event.metadata['trade_id'] = trade.id
                event.metadata['trade_type'] = trade.order_type.value

            await publish_event(event)

        except Exception as e:
            self.logger.error(f"❌ Ошибка публикации события позиции: {e}")

    def _summary_to_dict(self, summary: PositionSummary) -> Dict[str, Any]:
        """📤 Конвертация сводки в словарь"""

        return {
            'currency': summary.currency,
            'quantity': str(summary.quantity),
            'avg_price': str(summary.avg_price),
            'current_price': str(summary.current_price),
            'market_value': str(summary.market_value),
            'unrealized_pnl': str(summary.unrealized_pnl),
            'unrealized_pnl_percent': summary.unrealized_pnl_percent,
            'cost_basis': str(summary.cost_basis),
            'is_profitable': summary.is_profitable,
            'last_updated': summary.last_updated.isoformat()
        }

    def _metrics_to_dict(self, metrics: PortfolioMetrics) -> Dict[str, Any]:
        """📈 Конвертация метрик в словарь"""

        return {
            'total_value': str(metrics.total_value),
            'total_cost': str(metrics.total_cost),
            'total_pnl': str(metrics.total_pnl),
            'total_pnl_percent': metrics.total_pnl_percent,
            'positions_count': metrics.positions_count,
            'profitable_positions': metrics.profitable_positions,
            'losing_positions': metrics.losing_positions,
            'win_rate': metrics.win_rate,
            'largest_position_value': str(metrics.largest_position_value),
            'concentration_risk': metrics.concentration_risk
        }

    # ================= ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ =================

    async def validate_position_integrity(self, currency: str) -> Dict[str, Any]:
        """✅ Валидация целостности позиции"""

        try:
            position = await self.get_position(currency)
            if not position:
                return {'valid': True, 'reason': 'No position to validate'}

            # Проверки целостности
            checks = {
                'quantity_positive': position.quantity >= 0,
                'avg_price_positive': position.avg_price >= 0,
                'total_cost_positive': position.total_cost >= 0,
                'avg_price_consistency': True,  # Будет проверено ниже
                'trades_consistency': True      # Будет проверено ниже
            }

            # Проверка согласованности средней цены
            if position.quantity > 0 and position.total_cost > 0:
                calculated_avg = position.total_cost / position.quantity
                price_diff = abs(calculated_avg - position.avg_price)
                checks['avg_price_consistency'] = price_diff < Decimal('0.00000001')

            # Проверка согласованности с историей сделок
            if position.trades:
                reconstructed = self._reconstruct_from_trades(position.trades)
                checks['trades_consistency'] = (
                    abs(reconstructed['quantity'] - position.quantity) < Decimal('0.000001') and
                    abs(reconstructed['total_cost'] - position.total_cost) < Decimal('0.01')
                )

            all_valid = all(checks.values())

            return {
                'valid': all_valid,
                'checks': checks,
                'position': {
                    'currency': position.currency,
                    'quantity': str(position.quantity),
                    'avg_price': str(position.avg_price),
                    'total_cost': str(position.total_cost)
                }
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка валидации позиции {currency}: {e}")
            return {'valid': False, 'error': str(e)}

    def _reconstruct_from_trades(self, trades: List[Trade]) -> Dict[str, Decimal]:
        """🔄 Реконструкция позиции из сделок"""

        quantity = Decimal('0')
        total_cost = Decimal('0')

        for trade in trades:
            if trade.order_type == OrderType.BUY:
                quantity += trade.quantity
                total_cost += trade.total_cost
            elif trade.order_type == OrderType.SELL:
                sell_ratio = trade.quantity / quantity if quantity > 0 else Decimal('0')
                cost_reduction = total_cost * sell_ratio

                quantity -= trade.quantity
                total_cost -= cost_reduction

                # Корректируем отрицательные значения
                quantity = max(quantity, Decimal('0'))
                total_cost = max(total_cost, Decimal('0'))

        return {
            'quantity': quantity,
            'total_cost': total_cost
        }

    async def get_position_analytics(self, currency: str, days: int = 30) -> Dict[str, Any]:
        """📊 Аналитика позиции"""

        try:
            position = await self.get_position(currency)
            if not position:
                return {'error': 'Position not found'}

            history = await self.get_position_history(currency, days)

            # Базовая аналитика
            analytics = {
                'current_position': self._summary_to_dict(
                    await self._create_position_summary(
                        position,
                        await self._get_current_price(currency) or Price(Decimal('0'), TradingPair.from_string(f"{currency}_EUR"))
                    )
                ),
                'history_length': len(history),
                'trades_count': len(position.trades),
                'holding_period_days': 0,
                'avg_trade_size': Decimal('0'),
                'max_position_size': Decimal('0')
            }

            # Расчет периода удержания
            if position.trades:
                first_trade = min(position.trades, key=lambda t: t.timestamp)
                holding_period = datetime.now() - first_trade.timestamp
                analytics['holding_period_days'] = holding_period.days

            # Средний размер сделки
            if position.trades:
                total_volume = sum(trade.quantity for trade in position.trades)
                analytics['avg_trade_size'] = str(total_volume / len(position.trades))

            # Максимальный размер позиции
            if history:
                max_qty = max(pos.quantity for pos in history)
                analytics['max_position_size'] = str(max_qty)

            return analytics

        except Exception as e:
            self.logger.error(f"❌ Ошибка аналитики позиции {currency}: {e}")
            return {'error': str(e)}
