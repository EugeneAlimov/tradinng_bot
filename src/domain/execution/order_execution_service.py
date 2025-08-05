from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass, field
from enum import Enum
import asyncio

# Импорты из Core слоя
try:
    from ...core.interfaces import ITradeExecutor, IExchangeAPI
    from ...core.models import (
        TradeSignal, OrderResult, TradingPair,
        OrderType, OrderStatus, StrategySignalType
    )
    from ...core.exceptions import (
        TradingError, OrderExecutionError, InsufficientBalanceError,
        ExchangeError, RateLimitExceededError, ValidationError
    )
    from ...core.events import DomainEvent, publish_event
    from ...config.settings import get_current_config
except ImportError:
    # Fallback для случая если Core слой еще не готов
    class ITradeExecutor: pass
    class IExchangeAPI: pass
    class TradeSignal: pass
    class OrderResult: pass
    class TradingPair: pass
    class OrderType: pass
    class OrderStatus: pass
    class StrategySignalType: pass
    class TradingError(Exception): pass
    class OrderExecutionError(Exception): pass
    class InsufficientBalanceError(Exception): pass
    class ExchangeError(Exception): pass
    class RateLimitExceededError(Exception): pass
    class ValidationError(Exception): pass
    class DomainEvent: pass
    def publish_event(event): pass
    def get_current_config(): return None


# ================= ТИПЫ ИСПОЛНЕНИЯ =================

class ExecutionMode(Enum):
    """⚡ Режимы исполнения"""
    SIMULATION = "simulation"      # Симуляция
    PAPER = "paper"               # Бумажная торговля
    LIVE = "live"                 # Реальная торговля


class OrderPriority(Enum):
    """🎯 Приоритеты ордеров"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4
    EMERGENCY = 5


@dataclass
class ExecutionConfig:
    """⚙️ Конфигурация исполнения"""
    mode: ExecutionMode = ExecutionMode.SIMULATION
    max_slippage_percent: Decimal = Decimal('0.5')
    timeout_seconds: int = 30
    retry_attempts: int = 3
    retry_delay_seconds: float = 1.0
    rate_limit_requests_per_minute: int = 60
    min_order_value_eur: Decimal = Decimal('5.0')
    emergency_stop_enabled: bool = True

    def validate(self) -> bool:
        """✅ Валидация конфигурации"""
        return (
            self.max_slippage_percent >= 0 and
            self.timeout_seconds > 0 and
            self.retry_attempts >= 0 and
            self.min_order_value_eur > 0
        )


@dataclass
class ExecutionRequest:
    """📋 Запрос на исполнение"""
    id: str
    signal: TradeSignal
    priority: OrderPriority = OrderPriority.NORMAL
    max_slippage: Optional[Decimal] = None
    timeout: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.now)
    attempts: int = 0
    last_error: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        """Истек ли запрос"""
        timeout_minutes = 15  # По умолчанию 15 минут
        return (datetime.now() - self.created_at).total_seconds() > timeout_minutes * 60


@dataclass
class ExecutionMetrics:
    """📊 Метрики исполнения"""
    total_requests: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    total_slippage: Decimal = Decimal('0')
    average_execution_time: float = 0.0
    rate_limit_hits: int = 0
    api_errors: int = 0
    network_errors: int = 0

    @property
    def success_rate(self) -> float:
        """Процент успешных исполнений"""
        return (self.successful_executions / self.total_requests * 100) if self.total_requests > 0 else 0.0

    @property
    def average_slippage(self) -> Decimal:
        """Средний слиппаж"""
        return self.total_slippage / self.successful_executions if self.successful_executions > 0 else Decimal('0')


# ================= ОСНОВНОЙ СЕРВИС =================

class OrderExecutionService(ITradeExecutor):
    """⚡ Сервис исполнения ордеров"""

    def __init__(
        self,
        exchange_api: Optional[IExchangeAPI] = None,
        config: Optional[ExecutionConfig] = None
    ):
        self.exchange_api = exchange_api
        self.config = config or ExecutionConfig()

        # Очередь запросов
        self.execution_queue: List[ExecutionRequest] = []
        self.active_orders: Dict[str, Dict[str, Any]] = {}

        # Rate limiting
        self.request_times: List[datetime] = []

        # Метрики
        self.metrics = ExecutionMetrics()

        # Логирование
        self.logger = logging.getLogger(__name__)

        # Валидация
        if not self.config.validate():
            raise ValidationError("Некорректная конфигурация ExecutionService")

        self.logger.info(f"⚡ OrderExecutionService инициализирован в режиме {self.config.mode.value}")

    # ================= ОСНОВНЫЕ МЕТОДЫ ИНТЕРФЕЙСА =================

    async def execute_signal(self, signal: TradeSignal) -> OrderResult:
        """⚡ Выполнение торгового сигнала"""

        try:
            # Валидация сигнала
            self._validate_signal(signal)

            # Создаем запрос на исполнение
            request = ExecutionRequest(
                id=f"exec_{datetime.now().timestamp()}",
                signal=signal,
                priority=self._determine_priority(signal)
            )

            self.metrics.total_requests += 1

            # Выбираем способ исполнения в зависимости от типа сигнала
            if signal.signal_type == StrategySignalType.BUY:
                if signal.price:
                    return await self._execute_limit_buy(request)
                else:
                    return await self._execute_market_buy(request)

            elif signal.signal_type == StrategySignalType.SELL:
                if signal.price:
                    return await self._execute_limit_sell(request)
                else:
                    return await self._execute_market_sell(request)

            elif signal.signal_type == StrategySignalType.EMERGENCY_EXIT:
                return await self._execute_emergency_sell(request)

            else:
                # HOLD или другие типы
                return self._create_hold_result(request)

        except Exception as e:
            self.metrics.failed_executions += 1
            self.logger.error(f"❌ Ошибка исполнения сигнала: {e}")
            return self._create_error_result(signal, str(e))

    async def execute_market_order(
        self,
        pair: str,
        order_type: str,
        quantity: Decimal
    ) -> OrderResult:
        """🏪 Выполнение рыночного ордера"""

        try:
            # Создаем сигнал для внутреннего использования
            signal = TradeSignal(
                signal_type=StrategySignalType.BUY if order_type.lower() == 'buy' else StrategySignalType.SELL,
                pair=TradingPair.from_string(pair),
                quantity=quantity,
                strategy_name="manual_order"
            )

            return await self.execute_signal(signal)

        except Exception as e:
            self.logger.error(f"❌ Ошибка исполнения рыночного ордера: {e}")
            raise OrderExecutionError(f"Market order failed: {e}")

    async def execute_limit_order(
        self,
        pair: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal
    ) -> OrderResult:
        """📊 Выполнение лимитного ордера"""

        try:
            # Создаем сигнал с указанной ценой
            signal = TradeSignal(
                signal_type=StrategySignalType.BUY if order_type.lower() == 'buy' else StrategySignalType.SELL,
                pair=TradingPair.from_string(pair),
                quantity=quantity,
                price=price,
                strategy_name="manual_limit_order"
            )

            return await self.execute_signal(signal)

        except Exception as e:
            self.logger.error(f"❌ Ошибка исполнения лимитного ордера: {e}")
            raise OrderExecutionError(f"Limit order failed: {e}")

    async def cancel_order(self, order_id: str) -> bool:
        """❌ Отмена ордера"""

        try:
            if self.config.mode == ExecutionMode.SIMULATION:
                # В режиме симуляции просто удаляем из активных
                if order_id in self.active_orders:
                    del self.active_orders[order_id]
                    self.logger.info(f"📄 Симуляция отмены ордера: {order_id}")
                    return True
                return False

            elif self.exchange_api:
                # Проверяем rate limit
                if not await self._check_rate_limit():
                    raise RateLimitExceededError("Rate limit exceeded for cancel order")

                # Отменяем через API
                success = await self.exchange_api.cancel_order(order_id)

                if success and order_id in self.active_orders:
                    del self.active_orders[order_id]

                return success

            else:
                self.logger.warning("⚠️ Нет API для отмены ордера")
                return False

        except Exception as e:
            self.logger.error(f"❌ Ошибка отмены ордера {order_id}: {e}")
            return False

    async def get_active_orders(self) -> List[Dict[str, Any]]:
        """📋 Получение активных ордеров"""

        try:
            if self.config.mode == ExecutionMode.SIMULATION:
                return list(self.active_orders.values())

            elif self.exchange_api:
                if not await self._check_rate_limit():
                    raise RateLimitExceededError("Rate limit exceeded for get active orders")

                # Получаем через API (нужно адаптировать под конкретную биржу)
                return []  # Заглушка

            else:
                return []

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения активных ордеров: {e}")
            return []

    # ================= ПРИВАТНЫЕ МЕТОДЫ ИСПОЛНЕНИЯ =================

    async def _execute_market_buy(self, request: ExecutionRequest) -> OrderResult:
        """🛒 Исполнение рыночной покупки"""

        signal = request.signal
        start_time = datetime.now()

        try:
            if self.config.mode == ExecutionMode.SIMULATION:
                return await self._simulate_market_buy(request)

            elif self.exchange_api:
                # Проверяем rate limit
                if not await self._check_rate_limit():
                    raise RateLimitExceededError("Rate limit exceeded")

                # Исполняем через API
                order_data = await self.exchange_api.create_order(
                    pair=str(signal.pair),
                    order_type="buy",
                    quantity=signal.quantity
                )

                # Создаем результат
                result = self._create_success_result(signal, order_data, start_time)

                self.metrics.successful_executions += 1
                await self._publish_execution_event(result, "market_buy_executed")

                return result

            else:
                raise OrderExecutionError("No exchange API available")

        except Exception as e:
            self.metrics.failed_executions += 1
            self.logger.error(f"❌ Ошибка market buy: {e}")
            return self._create_error_result(signal, str(e))

    async def _execute_limit_buy(self, request: ExecutionRequest) -> OrderResult:
        """📊 Исполнение лимитной покупки"""

        signal = request.signal
        start_time = datetime.now()

        try:
            if self.config.mode == ExecutionMode.SIMULATION:
                return await self._simulate_limit_buy(request)

            elif self.exchange_api:
                if not await self._check_rate_limit():
                    raise RateLimitExceededError("Rate limit exceeded")

                order_data = await self.exchange_api.create_order(
                    pair=str(signal.pair),
                    order_type="buy",
                    quantity=signal.quantity,
                    price=signal.price
                )

                result = self._create_success_result(signal, order_data, start_time)

                self.metrics.successful_executions += 1
                await self._publish_execution_event(result, "limit_buy_executed")

                return result

            else:
                raise OrderExecutionError("No exchange API available")

        except Exception as e:
            self.metrics.failed_executions += 1
            return self._create_error_result(signal, str(e))

    async def _execute_market_sell(self, request: ExecutionRequest) -> OrderResult:
        """💎 Исполнение рыночной продажи"""

        signal = request.signal
        start_time = datetime.now()

        try:
            if self.config.mode == ExecutionMode.SIMULATION:
                return await self._simulate_market_sell(request)

            elif self.exchange_api:
                if not await self._check_rate_limit():
                    raise RateLimitExceededError("Rate limit exceeded")

                order_data = await self.exchange_api.create_order(
                    pair=str(signal.pair),
                    order_type="sell",
                    quantity=signal.quantity
                )

                result = self._create_success_result(signal, order_data, start_time)

                self.metrics.successful_executions += 1
                await self._publish_execution_event(result, "market_sell_executed")

                return result

            else:
                raise OrderExecutionError("No exchange API available")

        except Exception as e:
            self.metrics.failed_executions += 1
            return self._create_error_result(signal, str(e))

    async def _execute_emergency_sell(self, request: ExecutionRequest) -> OrderResult:
        """🚨 Исполнение аварийной продажи"""

        signal = request.signal
        start_time = datetime.now()

        try:
            self.logger.warning(f"🚨 Аварийная продажа: {signal.pair} {signal.quantity}")

            # Аварийная продажа всегда по рынку с максимальным приоритетом
            request.priority = OrderPriority.EMERGENCY

            if self.config.mode == ExecutionMode.SIMULATION:
                result = await self._simulate_market_sell(request)
                result.metadata = result.metadata or {}
                result.metadata['emergency'] = True
                return result

            elif self.exchange_api:
                if not await self._check_rate_limit():
                    # Для аварийной продажи игнорируем rate limit
                    self.logger.warning("⚠️ Игнорируем rate limit для аварийной продажи")

                order_data = await self.exchange_api.create_order(
                    pair=str(signal.pair),
                    order_type="sell",
                    quantity=signal.quantity
                )

                result = self._create_success_result(signal, order_data, start_time)
                result.metadata = result.metadata or {}
                result.metadata['emergency'] = True

                self.metrics.successful_executions += 1
                await self._publish_execution_event(result, "emergency_sell_executed")

                return result

            else:
                raise OrderExecutionError("No exchange API for emergency sell")

        except Exception as e:
            self.metrics.failed_executions += 1
            self.logger.critical(f"🚨 КРИТИЧЕСКАЯ ОШИБКА аварийной продажи: {e}")
            return self._create_error_result(signal, str(e))

    # ================= СИМУЛЯЦИЯ =================

    async def _simulate_market_buy(self, request: ExecutionRequest) -> OrderResult:
        """📄 Симуляция рыночной покупки"""

        signal = request.signal

        # Имитируем получение текущей цены
        simulated_price = signal.price or Decimal('0.1')  # Заглушка

        # Имитируем небольшой слиппаж
        slippage = Decimal('0.001')  # 0.1%
        executed_price = simulated_price * (Decimal('1') + slippage)

        total_cost = signal.quantity * executed_price
        commission = total_cost * Decimal('0.003')  # 0.3% комиссия

        return OrderResult(
            order_id=f"sim_buy_{datetime.now().timestamp()}",
            pair=signal.pair,
            order_type=OrderType.BUY,
            status=OrderStatus.FILLED,
            requested_quantity=signal.quantity,
            executed_quantity=signal.quantity,
            requested_price=signal.price,
            executed_price=executed_price,
            total_cost=total_cost,
            commission=commission,
            timestamp=datetime.now()
        )

    async def _simulate_market_sell(self, request: ExecutionRequest) -> OrderResult:
        """📄 Симуляция рыночной продажи"""

        signal = request.signal

        # Имитируем получение текущей цены
        simulated_price = signal.price or Decimal('0.1')  # Заглушка

        # Имитируем небольшой слиппаж (для продажи в минус)
        slippage = Decimal('0.001')  # 0.1%
        executed_price = simulated_price * (Decimal('1') - slippage)

        total_cost = signal.quantity * executed_price
        commission = total_cost * Decimal('0.003')  # 0.3% комиссия

        return OrderResult(
            order_id=f"sim_sell_{datetime.now().timestamp()}",
            pair=signal.pair,
            order_type=OrderType.SELL,
            status=OrderStatus.FILLED,
            requested_quantity=signal.quantity,
            executed_quantity=signal.quantity,
            requested_price=signal.price,
            executed_price=executed_price,
            total_cost=total_cost,
            commission=commission,
            timestamp=datetime.now()
        )

    async def _simulate_limit_buy(self, request: ExecutionRequest) -> OrderResult:
        """📄 Симуляция лимитной покупки"""

        # Для лимитных ордеров в симуляции считаем, что они исполняются по указанной цене
        signal = request.signal

        total_cost = signal.quantity * signal.price
        commission = total_cost * Decimal('0.002')  # 0.2% комиссия для лимитных

        return OrderResult(
            order_id=f"sim_limit_buy_{datetime.now().timestamp()}",
            pair=signal.pair,
            order_type=OrderType.BUY,
            status=OrderStatus.FILLED,
            requested_quantity=signal.quantity,
            executed_quantity=signal.quantity,
            requested_price=signal.price,
            executed_price=signal.price,
            total_cost=total_cost,
            commission=commission,
            timestamp=datetime.now()
        )

    # ================= ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =================

    def _validate_signal(self, signal: TradeSignal) -> None:
        """✅ Валидация торгового сигнала"""

        if not signal.pair:
            raise ValidationError("Trading pair is required")

        if signal.quantity <= 0:
            raise ValidationError("Quantity must be positive")

        if signal.price and signal.price <= 0:
            raise ValidationError("Price must be positive")

        # Проверяем минимальный размер ордера
        if signal.price:
            order_value = signal.quantity * signal.price
            if order_value < self.config.min_order_value_eur:
                raise ValidationError(f"Order value {order_value} below minimum {self.config.min_order_value_eur}")

    def _determine_priority(self, signal: TradeSignal) -> OrderPriority:
        """🎯 Определение приоритета ордера"""

        if signal.signal_type == StrategySignalType.EMERGENCY_EXIT:
            return OrderPriority.EMERGENCY

        if signal.risk_level and signal.risk_level.value == "high":
            return OrderPriority.HIGH

        return OrderPriority.NORMAL

    async def _check_rate_limit(self) -> bool:
        """⏱️ Проверка rate limit"""

        now = datetime.now()

        # Удаляем старые запросы (старше минуты)
        self.request_times = [
            req_time for req_time in self.request_times
            if (now - req_time).total_seconds() < 60
        ]

        # Проверяем лимит
        if len(self.request_times) >= self.config.rate_limit_requests_per_minute:
            self.metrics.rate_limit_hits += 1
            return False

        # Добавляем текущий запрос
        self.request_times.append(now)
        return True

    def _create_success_result(
        self,
        signal: TradeSignal,
        order_data: Dict[str, Any],
        start_time: datetime
    ) -> OrderResult:
        """✅ Создание результата успешного исполнения"""

        execution_time = (datetime.now() - start_time).total_seconds()
        self._update_execution_time(execution_time)

        return OrderResult(
            order_id=order_data.get('order_id', f"order_{datetime.now().timestamp()}"),
            pair=signal.pair,
            order_type=OrderType.BUY if signal.signal_type == StrategySignalType.BUY else OrderType.SELL,
            status=OrderStatus.FILLED,
            requested_quantity=signal.quantity,
            executed_quantity=Decimal(str(order_data.get('quantity', signal.quantity))),
            requested_price=signal.price,
            executed_price=Decimal(str(order_data.get('price', signal.price or 0))),
            total_cost=Decimal(str(order_data.get('total', 0))),
            commission=Decimal(str(order_data.get('commission', 0))),
            timestamp=datetime.now()
        )

    def _create_error_result(self, signal: TradeSignal, error_message: str) -> OrderResult:
        """❌ Создание результата с ошибкой"""

        return OrderResult(
            order_id=f"error_{datetime.now().timestamp()}",
            pair=signal.pair,
            order_type=OrderType.BUY if signal.signal_type == StrategySignalType.BUY else OrderType.SELL,
            status=OrderStatus.FAILED,
            requested_quantity=signal.quantity,
            executed_quantity=Decimal('0'),
            requested_price=signal.price,
            executed_price=None,
            total_cost=Decimal('0'),
            commission=Decimal('0'),
            timestamp=datetime.now(),
            error_message=error_message
        )

    def _create_hold_result(self, request: ExecutionRequest) -> OrderResult:
        """🔄 Создание результата для HOLD сигнала"""

        signal = request.signal

        return OrderResult(
            order_id=f"hold_{datetime.now().timestamp()}",
            pair=signal.pair,
            order_type=OrderType.BUY,  # Формальное значение
            status=OrderStatus.FILLED,
            requested_quantity=Decimal('0'),
            executed_quantity=Decimal('0'),
            requested_price=None,
            executed_price=None,
            total_cost=Decimal('0'),
            commission=Decimal('0'),
            timestamp=datetime.now()
        )

    def _update_execution_time(self, execution_time: float) -> None:
        """⏱️ Обновление среднего времени исполнения"""

        if self.metrics.average_execution_time == 0:
            self.metrics.average_execution_time = execution_time
        else:
            # Экспоненциальное сглаживание
            alpha = 0.1
            self.metrics.average_execution_time = (
                alpha * execution_time +
                (1 - alpha) * self.metrics.average_execution_time
            )

    async def _publish_execution_event(
        self,
        result: OrderResult,
        event_type: str
    ) -> None:
        """📡 Публикация события исполнения"""

        try:
            event = DomainEvent()
            event.event_type = event_type
            event.source = "order_execution_service"
            event.metadata = {
                'order_id': result.order_id,
                'pair': str(result.pair),
                'order_type': result.order_type.value,
                'status': result.status.value,
                'executed_quantity': str(result.executed_quantity),
                'total_cost': str(result.total_cost),
                'execution_mode': self.config.mode.value
            }

            await publish_event(event)

        except Exception as e:
            self.logger.error(f"❌ Ошибка публикации события исполнения: {e}")

    # ================= УПРАВЛЕНИЕ И МОНИТОРИНГ =================

    def get_execution_statistics(self) -> Dict[str, Any]:
        """📊 Статистика исполнения"""

        return {
            'execution_mode': self.config.mode.value,
            'metrics': {
                'total_requests': self.metrics.total_requests,
                'successful_executions': self.metrics.successful_executions,
                'failed_executions': self.metrics.failed_executions,
                'success_rate': self.metrics.success_rate,
                'average_execution_time': self.metrics.average_execution_time,
                'average_slippage': float(self.metrics.average_slippage),
                'rate_limit_hits': self.metrics.rate_limit_hits,
                'api_errors': self.metrics.api_errors
            },
            'config': {
                'max_slippage_percent': float(self.config.max_slippage_percent),
                'timeout_seconds': self.config.timeout_seconds,
                'min_order_value_eur': float(self.config.min_order_value_eur),
                'rate_limit_per_minute': self.config.rate_limit_requests_per_minute
            },
            'active_orders_count': len(self.active_orders),
            'queue_size': len(self.execution_queue)
        }

    def set_execution_mode(self, mode: ExecutionMode) -> None:
        """🔧 Установка режима исполнения"""

        old_mode = self.config.mode
        self.config.mode = mode

        self.logger.info(f"🔧 Режим исполнения изменен: {old_mode.value} -> {mode.value}")

    def update_config(self, new_config: ExecutionConfig) -> bool:
        """⚙️ Обновление конфигурации"""

        try:
            if not new_config.validate():
                self.logger.error("❌ Некорректная новая конфигурация")
                return False

            self.config = new_config
            self.logger.info("⚙️ Конфигурация обновлена")
            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления конфигурации: {e}")
            return False
