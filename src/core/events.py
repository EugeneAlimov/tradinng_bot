from typing import Dict, Any, List, Callable, Optional, Type, Set, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from abc import ABC, abstractmethod
from enum import Enum
import asyncio
import uuid
import weakref
import logging

# Импорт моделей с TYPE_CHECKING для избежания циклических импортов
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .models import EventType


# ================= БАЗОВЫЕ ТИПЫ =================

class EventPriority(Enum):
    """🎯 Приоритет события"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


# ================= БАЗОВЫЕ СОБЫТИЯ =================

@dataclass
class DomainEvent:
    """📡 Базовое доменное событие"""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = "unknown"
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = ""
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь"""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type,
            'timestamp': self.timestamp.isoformat(),
            'source': self.source,
            'correlation_id': self.correlation_id,
            'causation_id': self.causation_id,
            'metadata': self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DomainEvent':
        """Десериализация из словаря"""
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


# ================= ТИПЫ ОБРАБОТЧИКОВ =================

EventHandler = Callable[[DomainEvent], None]
AsyncEventHandler = Callable[[DomainEvent], asyncio.Task]


# ================= ИНТЕРФЕЙСЫ =================

class IEventBus(ABC):
    """📡 Интерфейс шины событий"""

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        """📤 Публикация события"""
        pass

    @abstractmethod
    async def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        priority: EventPriority = EventPriority.NORMAL,
        filter_func: Optional[Callable[[DomainEvent], bool]] = None
    ) -> str:
        """📥 Подписка на события"""
        pass

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> bool:
        """📤 Отписка от событий"""
        pass

    @abstractmethod
    async def clear_subscriptions(self) -> None:
        """🧹 Очистка всех подписок"""
        pass


class IEventStore(ABC):
    """🗄️ Интерфейс хранилища событий"""

    @abstractmethod
    async def save_event(self, event: DomainEvent) -> None:
        """💾 Сохранение события"""
        pass

    @abstractmethod
    async def get_events(
        self,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
        event_types: Optional[List[str]] = None
    ) -> List[DomainEvent]:
        """📋 Получение событий"""
        pass

    @abstractmethod
    async def get_events_for_aggregate(self, aggregate_id: str) -> List[DomainEvent]:
        """📦 Получение событий для агрегата"""
        pass


# ================= ПОДПИСКИ =================

@dataclass
class EventSubscription:
    """📋 Подписка на события"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    handler: Optional[EventHandler] = None
    async_handler: Optional[AsyncEventHandler] = None
    filter_func: Optional[Callable[[DomainEvent], bool]] = None
    priority: EventPriority = EventPriority.NORMAL
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_triggered: Optional[datetime] = None
    trigger_count: int = 0
    max_triggers: Optional[int] = None

    @property
    def is_expired(self) -> bool:
        """⏰ Проверка истечения подписки"""
        return (self.max_triggers is not None and
                self.trigger_count >= self.max_triggers)

    async def handle_event(self, event: DomainEvent) -> bool:
        """🔄 Обработка события"""
        if not self.is_active or self.is_expired:
            return False

        # Применяем фильтр если есть
        if self.filter_func and not self.filter_func(event):
            return False

        try:
            if self.async_handler:
                await self.async_handler(event)
            elif self.handler:
                self.handler(event)
            else:
                return False

            self.last_triggered = datetime.now()
            self.trigger_count += 1
            return True

        except Exception as e:
            logging.error(f"Error in event handler {self.id}: {e}")
            return False


# ================= EVENT BUS РЕАЛИЗАЦИЯ =================

class EventBus(IEventBus):
    """📡 Реализация шины событий"""

    def __init__(self, enable_persistence: bool = True, max_queue_size: int = 1000):
        self._subscriptions: Dict[str, List[EventSubscription]] = {}
        self._subscription_index: Dict[str, EventSubscription] = {}
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._processing_task: Optional[asyncio.Task] = None
        self._event_store: Optional[IEventStore] = None
        self._enable_persistence = enable_persistence
        self._is_running = False
        self._logger = logging.getLogger(__name__)

        # Статистика
        self._published_events = 0
        self._processed_events = 0
        self._failed_events = 0

    async def start(self) -> None:
        """🚀 Запуск шины событий"""
        if self._is_running:
            return

        self._is_running = True
        self._processing_task = asyncio.create_task(self._process_events())
        self._logger.info("📡 Event bus started")

    async def stop(self) -> None:
        """⏹️ Остановка шины событий"""
        if not self._is_running:
            return

        self._is_running = False

        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass

        self._logger.info("📡 Event bus stopped")

    def set_event_store(self, event_store: IEventStore) -> None:
        """🗄️ Установка хранилища событий"""
        self._event_store = event_store

    async def publish(self, event: DomainEvent) -> None:
        """📤 Публикация события"""
        if not self._is_running:
            await self.start()

        try:
            # Добавляем в очередь для обработки
            await self._event_queue.put(event)
            self._published_events += 1

            self._logger.debug(f"📤 Published event: {event.event_type} ({event.event_id})")

        except asyncio.QueueFull:
            self._failed_events += 1
            self._logger.error(f"❌ Event queue full, dropping event: {event.event_type}")

    async def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        priority: EventPriority = EventPriority.NORMAL,
        filter_func: Optional[Callable[[DomainEvent], bool]] = None,
        max_triggers: Optional[int] = None
    ) -> str:
        """📥 Подписка на события"""

        # Определяем тип обработчика
        async_handler = handler if asyncio.iscoroutinefunction(handler) else None
        sync_handler = handler if not asyncio.iscoroutinefunction(handler) else None

        subscription = EventSubscription(
            event_type=event_type,
            handler=sync_handler,
            async_handler=async_handler,
            filter_func=filter_func,
            priority=priority,
            max_triggers=max_triggers
        )

        # Добавляем в индекс
        self._subscription_index[subscription.id] = subscription

        # Добавляем в список подписок для типа события
        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []

        self._subscriptions[event_type].append(subscription)

        # Сортируем по приоритету (высокий приоритет первым)
        self._subscriptions[event_type].sort(
            key=lambda s: s.priority.value, reverse=True
        )

        self._logger.debug(f"📥 Subscribed to {event_type}: {subscription.id}")

        return subscription.id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """📤 Отписка от событий"""
        if subscription_id not in self._subscription_index:
            return False

        subscription = self._subscription_index[subscription_id]
        event_type = subscription.event_type

        # Удаляем из списка подписок
        if event_type in self._subscriptions:
            self._subscriptions[event_type] = [
                s for s in self._subscriptions[event_type]
                if s.id != subscription_id
            ]

        # Удаляем из индекса
        del self._subscription_index[subscription_id]

        self._logger.debug(f"📤 Unsubscribed from {event_type}: {subscription_id}")

        return True

    async def clear_subscriptions(self) -> None:
        """🧹 Очистка всех подписок"""
        self._subscriptions.clear()
        self._subscription_index.clear()
        self._logger.info("🧹 All subscriptions cleared")

    async def _process_events(self) -> None:
        """🔄 Обработка событий из очереди"""
        while self._is_running:
            try:
                # Получаем событие из очереди
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)

                # Сохраняем в хранилище если включено
                if self._enable_persistence and self._event_store:
                    await self._event_store.save_event(event)

                # Находим подписчиков
                subscriptions = self._subscriptions.get(event.event_type, [])

                # Обрабатываем событие всеми подписчиками
                for subscription in subscriptions:
                    try:
                        await subscription.handle_event(event)
                    except Exception as e:
                        self._failed_events += 1
                        self._logger.error(f"❌ Handler error for {event.event_type}: {e}")

                self._processed_events += 1

            except asyncio.TimeoutError:
                continue  # Нормальный timeout для проверки флага _is_running
            except Exception as e:
                self._failed_events += 1
                self._logger.error(f"❌ Error processing event: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """📊 Получение статистики шины событий"""
        return {
            'is_running': self._is_running,
            'published_events': self._published_events,
            'processed_events': self._processed_events,
            'failed_events': self._failed_events,
            'queue_size': self._event_queue.qsize(),
            'subscriptions_count': len(self._subscription_index),
            'subscription_types': list(self._subscriptions.keys())
        }


# ================= EVENT STORE РЕАЛИЗАЦИЯ =================

class MemoryEventStore(IEventStore):
    """🧠 In-memory хранилище событий"""

    def __init__(self, max_events: int = 10000):
        self._events: List[DomainEvent] = []
        self._max_events = max_events
        self._lock = asyncio.Lock()

    async def save_event(self, event: DomainEvent) -> None:
        """💾 Сохранение события"""
        async with self._lock:
            self._events.append(event)

            # Ограничиваем размер хранилища
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]

    async def get_events(
        self,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
        event_types: Optional[List[str]] = None
    ) -> List[DomainEvent]:
        """📋 Получение событий"""
        async with self._lock:
            filtered_events = self._events.copy()

            # Фильтрация по времени
            if from_timestamp:
                filtered_events = [e for e in filtered_events if e.timestamp >= from_timestamp]

            if to_timestamp:
                filtered_events = [e for e in filtered_events if e.timestamp <= to_timestamp]

            # Фильтрация по типам
            if event_types:
                filtered_events = [e for e in filtered_events if e.event_type in event_types]

            return filtered_events

    async def get_events_for_aggregate(self, aggregate_id: str) -> List[DomainEvent]:
        """📦 Получение событий для агрегата"""
        async with self._lock:
            return [
                event for event in self._events
                if event.correlation_id == aggregate_id
            ]


# ================= СПЕЦИАЛИЗИРОВАННЫЕ СОБЫТИЯ =================

@dataclass
class TradeExecutedEvent(DomainEvent):
    """📈 Событие выполнения торговой операции"""
    order_id: str = ""
    pair: str = ""
    order_type: str = ""
    quantity: str = ""
    price: str = ""
    total_cost: str = ""
    commission: str = ""
    success: bool = False

    def __post_init__(self):
        self.event_type = "trade_executed"
        if not self.source:
            self.source = "trading_service"


@dataclass
class PositionChangedEvent(DomainEvent):
    """📊 Событие изменения позиции"""
    currency: str = ""
    old_quantity: str = ""
    new_quantity: str = ""
    avg_price: str = ""
    change_reason: str = ""

    def __post_init__(self):
        self.event_type = "position_updated"
        if not self.source:
            self.source = "position_service"


@dataclass
class SignalGeneratedEvent(DomainEvent):
    """🎯 Событие генерации торгового сигнала"""
    signal_id: str = ""
    signal_type: str = ""
    strategy_name: str = ""
    pair: str = ""
    confidence: float = 0.0
    reason: str = ""

    def __post_init__(self):
        self.event_type = "signal_generated"
        if not self.source:
            self.source = "strategy_service"


@dataclass
class RiskAlertEvent(DomainEvent):
    """🚨 Событие риск-алерта"""
    risk_type: str = ""
    severity: str = ""
    current_value: str = ""
    threshold_value: str = ""
    affected_positions: List[str] = field(default_factory=list)
    action_required: bool = False

    def __post_init__(self):
        self.event_type = "risk_limit_exceeded"
        if not self.source:
            self.source = "risk_service"


# ================= EVENT DISPATCHER =================

class EventDispatcher:
    """📡 Диспетчер событий"""

    def __init__(self, event_bus: IEventBus):
        self.event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def dispatch_trade_executed(
        self,
        order_id: str,
        pair: str,
        order_type: str,
        quantity: str,
        price: str,
        total_cost: str,
        commission: str = "0",
        success: bool = True
    ) -> None:
        """📈 Диспетчеризация события торговой операции"""
        event = TradeExecutedEvent(
            order_id=order_id,
            pair=pair,
            order_type=order_type,
            quantity=quantity,
            price=price,
            total_cost=total_cost,
            commission=commission,
            success=success
        )

        await self.event_bus.publish(event)

    async def dispatch_position_changed(
        self,
        currency: str,
        old_quantity: str,
        new_quantity: str,
        avg_price: str,
        change_reason: str
    ) -> None:
        """📊 Диспетчеризация события изменения позиции"""
        event = PositionChangedEvent(
            currency=currency,
            old_quantity=old_quantity,
            new_quantity=new_quantity,
            avg_price=avg_price,
            change_reason=change_reason
        )

        await self.event_bus.publish(event)

    async def dispatch_signal_generated(
        self,
        signal_id: str,
        signal_type: str,
        strategy_name: str,
        pair: str,
        confidence: float,
        reason: str
    ) -> None:
        """🎯 Диспетчеризация события генерации сигнала"""
        event = SignalGeneratedEvent(
            signal_id=signal_id,
            signal_type=signal_type,
            strategy_name=strategy_name,
            pair=pair,
            confidence=confidence,
            reason=reason
        )

        await self.event_bus.publish(event)

    async def dispatch_risk_alert(
        self,
        risk_type: str,
        severity: str,
        current_value: str,
        threshold_value: str,
        affected_positions: List[str] = None,
        action_required: bool = False
    ) -> None:
        """🚨 Диспетчеризация риск-алерта"""
        event = RiskAlertEvent(
            risk_type=risk_type,
            severity=severity,
            current_value=current_value,
            threshold_value=threshold_value,
            affected_positions=affected_positions or [],
            action_required=action_required
        )

        await self.event_bus.publish(event)


# ================= ДЕКОРАТОРЫ =================

def event_handler(event_type: str, priority: EventPriority = EventPriority.NORMAL):
    """🎯 Декоратор для автоматической регистрации обработчика"""
    def decorator(func):
        func._event_type = event_type
        func._event_priority = priority
        func._is_event_handler = True
        return func
    return decorator


# ================= УТИЛИТЫ =================

class EventBusFactory:
    """🏭 Фабрика для создания Event Bus"""

    @staticmethod
    def create_default() -> EventBus:
        """🏭 Создание стандартной шины событий"""
        event_bus = EventBus(enable_persistence=True)
        event_store = MemoryEventStore()
        event_bus.set_event_store(event_store)
        return event_bus

    @staticmethod
    def create_high_performance() -> EventBus:
        """⚡ Создание высокопроизводительной шины"""
        return EventBus(enable_persistence=False, max_queue_size=5000)

    @staticmethod
    def create_persistent() -> EventBus:
        """💾 Создание шины с персистентностью"""
        event_bus = EventBus(enable_persistence=True, max_queue_size=2000)
        event_store = MemoryEventStore(max_events=50000)
        event_bus.set_event_store(event_store)
        return event_bus


# ================= ГЛОБАЛЬНЫЕ УТИЛИТЫ =================

_global_event_bus: Optional[EventBus] = None


async def get_global_event_bus() -> EventBus:
    """🌍 Получение глобальной шины событий"""
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBusFactory.create_default()
        await _global_event_bus.start()
    return _global_event_bus


async def publish_event(event: DomainEvent) -> None:
    """📤 Публикация события через глобальную шину"""
    event_bus = await get_global_event_bus()
    await event_bus.publish(event)


async def subscribe_to_events(
    event_type: str,
    handler: EventHandler,
    **kwargs
) -> str:
    """📥 Подписка на события через глобальную шину"""
    event_bus = await get_global_event_bus()
    return await event_bus.subscribe(event_type, handler, **kwargs)
