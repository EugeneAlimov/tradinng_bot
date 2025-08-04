#!/usr/bin/env python3
"""🎯 Основные интерфейсы торговой системы - Core слой"""

from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, Optional, List, Union, AsyncIterator
from decimal import Decimal
from datetime import datetime
from enum import Enum


# ================= БАЗОВЫЕ ТИПЫ =================

class OrderType(Enum):
    """Типы ордеров"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Статусы ордеров"""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class StrategySignalType(Enum):
    """Типы торговых сигналов"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    EMERGENCY_EXIT = "emergency_exit"


class RiskLevel(Enum):
    """Уровни риска"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ================= ОСНОВНЫЕ ИНТЕРФЕЙСЫ =================

class IExchangeAPI(Protocol):
    """🌐 Интерфейс API биржи"""
    
    async def get_balance(self, currency: str) -> Decimal:
        """💰 Получение баланса валюты"""
        ...
    
    async def get_current_price(self, pair: str) -> Decimal:
        """💱 Получение текущей цены торговой пары"""
        ...
    
    async def get_ticker(self, pair: str) -> Dict[str, Any]:
        """📊 Получение тикера торговой пары"""
        ...
    
    async def create_order(self, pair: str, order_type: OrderType, 
                          quantity: Decimal, price: Optional[Decimal] = None) -> Dict[str, Any]:
        """📋 Создание ордера"""
        ...
    
    async def cancel_order(self, order_id: str) -> bool:
        """❌ Отмена ордера"""
        ...
    
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """📊 Получение статуса ордера"""
        ...
    
    async def get_order_history(self, pair: str, limit: int = 100) -> List[Dict[str, Any]]:
        """📜 Получение истории ордеров"""
        ...
    
    async def get_trade_history(self, pair: str, limit: int = 100) -> List[Dict[str, Any]]:
        """📈 Получение истории торгов"""
        ...


class ITradingStrategy(ABC):
    """🎯 Абстрактная торговая стратегия"""
    
    @abstractmethod
    async def analyze(self, market_data: 'MarketData', 
                     position: Optional['Position'] = None) -> 'TradeSignal':
        """📈 Анализ рынка и генерация торгового сигнала"""
        pass
    
    @abstractmethod
    def get_strategy_name(self) -> str:
        """📛 Получение имени стратегии"""
        pass
    
    @abstractmethod
    def get_strategy_type(self) -> str:
        """🏷️ Получение типа стратегии (dca, pyramid, trailing, etc.)"""
        pass
    
    @abstractmethod
    def get_priority(self) -> int:
        """🎯 Получение приоритета стратегии (1-100, выше = важнее)"""
        pass
    
    @abstractmethod
    async def validate_signal(self, signal: 'TradeSignal') -> bool:
        """✅ Валидация торгового сигнала"""
        pass


class IRiskManager(Protocol):
    """🛡️ Интерфейс менеджера рисков"""
    
    async def assess_trade_risk(self, signal: 'TradeSignal', 
                               position: Optional['Position'] = None) -> Dict[str, Any]:
        """🔍 Оценка риска торговой операции"""
        ...
    
    async def should_block_trading(self, reason: Optional[str] = None) -> bool:
        """🚫 Проверка блокировки торговли"""
        ...
    
    async def calculate_position_size(self, signal: 'TradeSignal', 
                                    available_balance: Decimal) -> Decimal:
        """📐 Расчет размера позиции"""
        ...
    
    async def check_daily_limits(self) -> Dict[str, Any]:
        """📊 Проверка дневных лимитов"""
        ...
    
    async def get_risk_level(self, signal: 'TradeSignal') -> RiskLevel:
        """⚠️ Определение уровня риска"""
        ...
    
    async def emergency_stop_check(self) -> bool:
        """🚨 Проверка условий экстренной остановки"""
        ...


class IPositionManager(Protocol):
    """📊 Интерфейс менеджера позиций"""
    
    async def get_position(self, currency: str) -> Optional['Position']:
        """📋 Получение текущей позиции"""
        ...
    
    async def update_position(self, trade_result: Dict[str, Any]) -> None:
        """🔄 Обновление позиции после сделки"""
        ...
    
    async def calculate_profit_loss(self, position: 'Position', 
                                  current_price: Decimal) -> Decimal:
        """💹 Расчет прибыли/убытка"""
        ...
    
    async def get_position_value(self, position: 'Position', 
                               current_price: Decimal) -> Decimal:
        """💰 Расчет текущей стоимости позиции"""
        ...
    
    async def close_position(self, currency: str, reason: str) -> Dict[str, Any]:
        """🔚 Закрытие позиции"""
        ...
    
    async def get_all_positions(self) -> List['Position']:
        """📋 Получение всех открытых позиций"""
        ...


class ITradeExecutor(Protocol):
    """⚡ Интерфейс исполнителя торгов"""
    
    async def execute_trade(self, signal: 'TradeSignal') -> Dict[str, Any]:
        """🎯 Исполнение торгового сигнала"""
        ...
    
    async def execute_market_order(self, pair: str, order_type: OrderType, 
                                 quantity: Decimal) -> Dict[str, Any]:
        """⚡ Исполнение рыночного ордера"""
        ...
    
    async def execute_limit_order(self, pair: str, order_type: OrderType, 
                                quantity: Decimal, price: Decimal) -> Dict[str, Any]:
        """🎯 Исполнение лимитного ордера"""
        ...
    
    async def cancel_all_orders(self, pair: str) -> List[str]:
        """❌ Отмена всех ордеров по паре"""
        ...


class IMarketDataProvider(Protocol):
    """📊 Интерфейс провайдера рыночных данных"""
    
    async def get_market_data(self, pair: str) -> 'MarketData':
        """📈 Получение текущих рыночных данных"""
        ...
    
    async def get_historical_data(self, pair: str, period: str, 
                                limit: int = 100) -> List['MarketData']:
        """📜 Получение исторических данных"""
        ...
    
    async def subscribe_to_price_updates(self, pair: str) -> AsyncIterator['MarketData']:
        """🔔 Подписка на обновления цен"""
        ...
    
    async def get_order_book(self, pair: str, depth: int = 10) -> Dict[str, Any]:
        """📚 Получение стакана заявок"""
        ...


class IAnalyticsService(Protocol):
    """📊 Интерфейс сервиса аналитики"""
    
    async def record_trade(self, trade_data: Dict[str, Any]) -> None:
        """📝 Запись торговой операции"""
        ...
    
    async def record_signal(self, signal: 'TradeSignal') -> None:
        """📊 Запись торгового сигнала"""
        ...
    
    async def get_performance_metrics(self, period_days: int = 30) -> Dict[str, Any]:
        """📈 Получение метрик производительности"""
        ...
    
    async def get_trading_statistics(self) -> Dict[str, Any]:
        """📊 Получение торговой статистики"""
        ...
    
    async def generate_report(self, report_type: str) -> Dict[str, Any]:
        """📋 Генерация отчета"""
        ...


class INotificationService(Protocol):
    """📢 Интерфейс сервиса уведомлений"""
    
    async def send_trade_notification(self, trade_data: Dict[str, Any]) -> None:
        """📤 Отправка уведомления о торговой операции"""
        ...
    
    async def send_alert(self, message: str, level: str = "info") -> None:
        """🚨 Отправка алерта"""
        ...
    
    async def send_emergency_notification(self, message: str, 
                                        context: Dict[str, Any]) -> None:
        """🚨 Отправка экстренного уведомления"""
        ...


class IRateLimiter(Protocol):
    """⏱️ Интерфейс ограничителя частоты запросов"""
    
    async def wait_if_needed(self, endpoint: str) -> float:
        """⏳ Ожидание при необходимости соблюдения лимитов"""
        ...
    
    def register_api_call(self, endpoint: str, duration: float) -> None:
        """📊 Регистрация API вызова"""
        ...
    
    def register_api_error(self, endpoint: str, error_type: str) -> None:
        """❌ Регистрация ошибки API"""
        ...
    
    def get_rate_limit_status(self) -> Dict[str, Any]:
        """📊 Получение статуса rate limiting"""
        ...


# ================= ИНТЕРФЕЙСЫ РЕПОЗИТОРИЕВ =================

class IRepository(Protocol):
    """🗄️ Базовый интерфейс репозитория"""
    
    async def save(self, entity: Any) -> Any:
        """💾 Сохранение сущности"""
        ...
    
    async def find_by_id(self, entity_id: str) -> Optional[Any]:
        """🔍 Поиск по ID"""
        ...
    
    async def find_all(self) -> List[Any]:
        """📋 Получение всех сущностей"""
        ...
    
    async def delete(self, entity_id: str) -> bool:
        """🗑️ Удаление сущности"""
        ...


class IPositionRepository(IRepository):
    """📊 Интерфейс репозитория позиций"""
    
    async def find_by_currency(self, currency: str) -> Optional['Position']:
        """🔍 Поиск позиции по валюте"""
        ...
    
    async def find_active_positions(self) -> List['Position']:
        """📋 Получение активных позиций"""
        ...


class ITradeHistoryRepository(IRepository):
    """📈 Интерфейс репозитория истории торгов"""
    
    async def find_by_pair(self, pair: str, limit: int = 100) -> List[Dict[str, Any]]:
        """🔍 Поиск торгов по паре"""
        ...
    
    async def find_by_date_range(self, start_date: datetime, 
                               end_date: datetime) -> List[Dict[str, Any]]:
        """📅 Поиск торгов по периоду"""
        ...


class IConfigRepository(IRepository):
    """⚙️ Интерфейс репозитория конфигурации"""
    
    async def get_config_value(self, key: str, default: Any = None) -> Any:
        """🔧 Получение значения конфигурации"""
        ...
    
    async def set_config_value(self, key: str, value: Any) -> None:
        """🔧 Установка значения конфигурации"""
        ...
    
    async def get_trading_config(self) -> Dict[str, Any]:
        """📊 Получение торговой конфигурации"""
        ...


# ================= ИНТЕРФЕЙСЫ СОБЫТИЙ =================

class IEventBus(Protocol):
    """📡 Интерфейс шины событий"""
    
    async def publish(self, event: 'DomainEvent') -> None:
        """📤 Публикация события"""
        ...
    
    async def subscribe(self, event_type: str, handler: callable) -> None:
        """📥 Подписка на события"""
        ...
    
    async def unsubscribe(self, event_type: str, handler: callable) -> None:
        """📤 Отписка от событий"""
        ...


class IEventHandler(Protocol):
    """🎯 Интерфейс обработчика событий"""
    
    async def handle(self, event: 'DomainEvent') -> None:
        """🔄 Обработка события"""
        ...
    
    def can_handle(self, event_type: str) -> bool:
        """✅ Проверка возможности обработки события"""
        ...


# ================= ИНТЕРФЕЙСЫ ВАЛИДАЦИИ =================

class IValidator(Protocol):
    """✅ Базовый интерфейс валидатора"""
    
    async def validate(self, data: Any) -> bool:
        """✅ Валидация данных"""
        ...
    
    async def validate_with_errors(self, data: Any) -> tuple[bool, List[str]]:
        """✅ Валидация с получением списка ошибок"""
        ...


class ITradeValidator(IValidator):
    """✅ Интерфейс валидатора торговых операций"""
    
    async def validate_trade_signal(self, signal: 'TradeSignal') -> bool:
        """✅ Валидация торгового сигнала"""
        ...
    
    async def validate_order_parameters(self, pair: str, quantity: Decimal, 
                                      price: Optional[Decimal] = None) -> bool:
        """✅ Валидация параметров ордера"""
        ...
    
    async def validate_balance_sufficient(self, currency: str, 
                                        required_amount: Decimal) -> bool:
        """✅ Валидация достаточности баланса"""
        ...


# ================= ИНТЕРФЕЙСЫ ИНФРАСТРУКТУРЫ =================

class ILogger(Protocol):
    """📝 Интерфейс логгера"""
    
    def debug(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """🐛 Отладочное сообщение"""
        ...
    
    def info(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """ℹ️ Информационное сообщение"""
        ...
    
    def warning(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """⚠️ Предупреждение"""
        ...
    
    def error(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """❌ Ошибка"""
        ...
    
    def critical(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """🚨 Критическая ошибка"""
        ...


class ICacheService(Protocol):
    """💾 Интерфейс сервиса кэширования"""
    
    async def get(self, key: str, default: Any = None) -> Any:
        """🔍 Получение значения из кэша"""
        ...
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """💾 Сохранение значения в кэш"""
        ...
    
    async def delete(self, key: str) -> bool:
        """🗑️ Удаление значения из кэша"""
        ...
    
    async def clear(self) -> None:
        """🧹 Очистка кэша"""
        ...
    
    async def exists(self, key: str) -> bool:
        """✅ Проверка существования ключа"""
        ...


class IConfigProvider(Protocol):
    """⚙️ Интерфейс провайдера конфигурации"""
    
    def get(self, key: str, default: Any = None) -> Any:
        """🔧 Получение значения конфигурации"""
        ...
    
    def set(self, key: str, value: Any) -> None:
        """🔧 Установка значения конфигурации"""
        ...
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """📊 Получение секции конфигурации"""
        ...
    
    def validate(self) -> bool:
        """✅ Валидация конфигурации"""
        ...
    
    def reload(self) -> None:
        """🔄 Перезагрузка конфигурации"""
        ...


# ================= ИНТЕРФЕЙСЫ МОНИТОРИНГА =================

class IHealthChecker(Protocol):
    """🏥 Интерфейс проверки здоровья системы"""
    
    async def check_health(self) -> Dict[str, Any]:
        """🔍 Проверка общего состояния системы"""
        ...
    
    async def check_api_connectivity(self) -> bool:
        """🌐 Проверка подключения к API"""
        ...
    
    async def check_database_connectivity(self) -> bool:
        """🗄️ Проверка подключения к базе данных"""
        ...
    
    async def get_system_metrics(self) -> Dict[str, Any]:
        """📊 Получение системных метрик"""
        ...


class IMetricsCollector(Protocol):
    """📊 Интерфейс сборщика метрик"""
    
    async def record_metric(self, name: str, value: Union[int, float], 
                          tags: Optional[Dict[str, str]] = None) -> None:
        """📝 Запись метрики"""
        ...
    
    async def increment_counter(self, name: str, 
                              tags: Optional[Dict[str, str]] = None) -> None:
        """➕ Увеличение счетчика"""
        ...
    
    async def record_timing(self, name: str, duration: float,
                          tags: Optional[Dict[str, str]] = None) -> None:
        """⏱️ Запись времени выполнения"""
        ...
    
    async def get_metrics(self) -> Dict[str, Any]:
        """📊 Получение всех метрик"""
        ...


# ================= ИНТЕРФЕЙС DEPENDENCY INJECTION =================

class IDependencyContainer(ABC):
    """🏗️ Интерфейс контейнера зависимостей"""
    
    @abstractmethod
    def register_singleton(self, service_type: type, 
                          implementation_type: type) -> None:
        """📌 Регистрация singleton сервиса"""
        pass
    
    @abstractmethod
    def register_transient(self, service_type: type, 
                          implementation_type: type) -> None:
        """🔄 Регистрация transient сервиса"""
        pass
    
    @abstractmethod
    def register_instance(self, service_type: type, instance: Any) -> None:
        """📦 Регистрация экземпляра"""
        pass
    
    @abstractmethod
    def resolve(self, service_type: type) -> Any:
        """🔍 Разрешение зависимости"""
        pass
    
    @abstractmethod
    def is_registered(self, service_type: type) -> bool:
        """✅ Проверка регистрации сервиса"""
        pass
    
    @abstractmethod
    def get_all_registrations(self) -> List[Dict[str, Any]]:
        """📋 Получение всех регистраций"""
        pass


# ================= FORWARD DECLARATIONS =================

# Эти интерфейсы будут определены в models.py
class MarketData: pass
class Position: pass
class TradeSignal: pass
class DomainEvent: pass