from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, Optional, List, Union, AsyncIterator
from decimal import Decimal
from datetime import datetime

# Импорты моделей - используем TYPE_CHECKING для избежания циклических импортов
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .models import (
        TradeSignal, Position, Trade, MarketData, OrderResult,
        TradingPair, Money, Price, TradingSession
    )


# ================= ОСНОВНЫЕ ПРОТОКОЛЫ СИСТЕМЫ =================

class IExchangeAPI(Protocol):
    """🌐 Интерфейс API биржи"""

    async def get_balance(self, currency: str) -> Decimal:
        """💰 Получение баланса валюты"""
        ...

    async def get_balances(self) -> Dict[str, Decimal]:
        """💰 Получение всех балансов"""
        ...

    async def get_current_price(self, pair: str) -> Decimal:
        """💱 Получение текущей цены торговой пары"""
        ...

    async def get_ticker(self, pair: str) -> Dict[str, Any]:
        """📊 Получение тикера торговой пары"""
        ...

    async def create_order(
        self,
        pair: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal] = None
    ) -> Dict[str, Any]:
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

    async def get_market_depth(self, pair: str, limit: int = 50) -> Dict[str, Any]:
        """📊 Получение стакана цен"""
        ...


class ITradingStrategy(ABC):
    """🎯 Абстрактная торговая стратегия"""

    @abstractmethod
    async def analyze(
        self,
        market_data: 'MarketData',
        position: Optional['Position'] = None
    ) -> 'TradeSignal':
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

    @abstractmethod
    def can_execute(self, market_conditions: Dict[str, Any]) -> bool:
        """✅ Проверка возможности выполнения стратегии"""
        pass

    @abstractmethod
    def get_required_balance(self, signal: 'TradeSignal') -> Decimal:
        """💰 Получение требуемого баланса для выполнения сигнала"""
        pass


class IRiskManager(Protocol):
    """🛡️ Интерфейс менеджера рисков"""

    async def assess_trade_risk(
        self,
        signal: 'TradeSignal',
        position: Optional['Position'] = None
    ) -> Dict[str, Any]:
        """🔍 Оценка риска торговой операции"""
        ...

    async def should_block_trading(self, reason: Optional[str] = None) -> bool:
        """🚫 Проверка блокировки торговли"""
        ...

    async def calculate_position_size(
        self,
        signal: 'TradeSignal',
        available_balance: Decimal
    ) -> Decimal:
        """📐 Расчет размера позиции"""
        ...

    async def check_daily_limits(self) -> Dict[str, Any]:
        """📊 Проверка дневных лимитов"""
        ...

    async def get_risk_level(self, signal: 'TradeSignal') -> str:
        """⚠️ Определение уровня риска"""
        ...

    async def emergency_stop_check(self) -> bool:
        """🚨 Проверка условий экстренной остановки"""
        ...

    async def check_position_limits(
        self,
        new_position_size: Decimal,
        current_balance: Decimal
    ) -> bool:
        """📏 Проверка лимитов позиции"""
        ...

    async def should_emergency_exit(
        self,
        position: 'Position',
        current_price: Decimal
    ) -> tuple[bool, str]:
        """🚨 Проверка необходимости аварийного выхода"""
        ...


class IPositionManager(Protocol):
    """📊 Интерфейс управления позициями"""

    async def get_position(self, currency: str) -> Optional['Position']:
        """📋 Получение текущей позиции"""
        ...

    async def get_all_positions(self) -> List['Position']:
        """📋 Получение всех позиций"""
        ...

    async def update_position(self, trade: 'Trade') -> 'Position':
        """🔄 Обновление позиции после сделки"""
        ...

    async def close_position(self, currency: str, reason: str) -> None:
        """🔒 Закрытие позиции"""
        ...

    async def get_portfolio_summary(self) -> Dict[str, Any]:
        """📈 Сводка портфеля"""
        ...

    async def calculate_total_value(self, prices: Dict[str, Decimal]) -> Decimal:
        """💰 Расчет общей стоимости портфеля"""
        ...

    async def get_position_history(self, currency: str, days: int = 30) -> List['Position']:
        """📜 История позиций"""
        ...


class ITradeExecutor(Protocol):
    """⚡ Интерфейс исполнения торгов"""

    async def execute_signal(self, signal: 'TradeSignal') -> 'OrderResult':
        """⚡ Выполнение торгового сигнала"""
        ...

    async def execute_market_order(
        self,
        pair: str,
        order_type: str,
        quantity: Decimal
    ) -> 'OrderResult':
        """🏪 Выполнение рыночного ордера"""
        ...

    async def execute_limit_order(
        self,
        pair: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal
    ) -> 'OrderResult':
        """📊 Выполнение лимитного ордера"""
        ...

    async def cancel_order(self, order_id: str) -> bool:
        """❌ Отмена ордера"""
        ...

    async def get_active_orders(self) -> List[Dict[str, Any]]:
        """📋 Получение активных ордеров"""
        ...


class IMarketDataProvider(Protocol):
    """📊 Интерфейс поставщика рыночных данных"""

    async def get_market_data(self, pair: str) -> 'MarketData':
        """📈 Получение рыночных данных"""
        ...

    async def get_historical_data(
        self,
        pair: str,
        period: str,
        limit: int = 100
    ) -> List['MarketData']:
        """📜 Исторические данные"""
        ...

    async def subscribe_to_price_updates(
        self,
        pair: str,
        callback: callable
    ) -> None:
        """🔔 Подписка на обновления цен"""
        ...

    async def get_price_stream(self, pair: str) -> AsyncIterator['Price']:
        """🌊 Поток цен в реальном времени"""
        ...


# ================= СПЕЦИАЛИЗИРОВАННЫЕ СТРАТЕГИИ =================

class IDCAStrategy(ITradingStrategy):
    """📈 Интерфейс DCA стратегии"""

    @abstractmethod
    async def should_buy_more(
        self,
        current_price: Decimal,
        position: 'Position',
        market_data: 'MarketData'
    ) -> tuple[bool, Decimal]:
        """🔍 Определение необходимости докупки"""
        pass

    @abstractmethod
    async def calculate_dca_amount(
        self,
        position: 'Position',
        available_balance: Decimal
    ) -> Decimal:
        """💰 Расчет суммы для DCA"""
        pass


class IPyramidStrategy(ITradingStrategy):
    """🏗️ Интерфейс пирамидальной стратегии"""

    @abstractmethod
    async def get_sell_levels(
        self,
        position: 'Position',
        current_price: Decimal
    ) -> List[tuple[Decimal, Decimal]]:  # [(price, quantity), ...]
        """📊 Получение уровней продажи"""
        pass

    @abstractmethod
    async def calculate_pyramid_sizes(
        self,
        position: 'Position',
        target_profit: Decimal
    ) -> List[Decimal]:
        """📐 Расчет размеров пирамиды"""
        pass


class IEmergencyExitStrategy(ITradingStrategy):
    """🚨 Интерфейс аварийного выхода"""

    @abstractmethod
    async def assess_emergency_conditions(
        self,
        position: 'Position',
        current_price: Decimal,
        market_data: 'MarketData'
    ) -> tuple[bool, str, float]:  # (should_exit, reason, sell_percentage)
        """🔍 Оценка аварийных условий"""
        pass

    @abstractmethod
    async def get_exit_price(
        self,
        position: 'Position',
        current_price: Decimal
    ) -> Decimal:
        """💰 Получение цены выхода"""
        pass


# ================= СЕРВИСЫ ИНФРАСТРУКТУРЫ =================

class IAnalyticsService(Protocol):
    """📊 Интерфейс сервиса аналитики"""

    async def record_trade(self, trade: 'Trade') -> None:
        """📝 Запись сделки"""
        ...

    async def calculate_performance(
        self,
        period_days: int = 30
    ) -> Dict[str, Union[float, int]]:
        """📈 Расчет производительности"""
        ...

    async def generate_report(
        self,
        report_type: str,
        period_days: int = 7
    ) -> Dict[str, Any]:
        """📋 Генерация отчета"""
        ...

    async def get_trading_statistics(self) -> Dict[str, Any]:
        """📊 Получение торговой статистики"""
        ...

    async def export_data(
        self,
        format_type: str,
        date_from: datetime,
        date_to: datetime
    ) -> str:
        """💾 Экспорт данных"""
        ...


class INotificationService(Protocol):
    """📢 Интерфейс сервиса уведомлений"""

    async def send_trade_notification(
        self,
        trade: 'Trade',
        notification_type: str = "trade_executed"
    ) -> None:
        """📱 Отправка уведомления о сделке"""
        ...

    async def send_emergency_notification(
        self,
        message: str,
        severity: str = "high"
    ) -> None:
        """🚨 Отправка экстренного уведомления"""
        ...

    async def send_daily_report(self, report_data: Dict[str, Any]) -> None:
        """📊 Отправка дневного отчета"""
        ...


class ICacheService(Protocol):
    """🗄️ Интерфейс сервиса кэширования"""

    async def get(self, key: str) -> Optional[Any]:
        """📖 Получение из кэша"""
        ...

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int = 300
    ) -> None:
        """💾 Сохранение в кэш"""
        ...

    async def delete(self, key: str) -> None:
        """🗑️ Удаление из кэша"""
        ...

    async def clear(self) -> None:
        """🧹 Очистка кэша"""
        ...


class IPersistenceService(Protocol):
    """💾 Интерфейс сервиса персистентности"""

    async def save_position(self, position: 'Position') -> None:
        """💾 Сохранение позиции"""
        ...

    async def load_position(self, currency: str) -> Optional['Position']:
        """📖 Загрузка позиции"""
        ...

    async def save_trade(self, trade: 'Trade') -> None:
        """💾 Сохранение сделки"""
        ...

    async def load_trades(
        self,
        currency: str,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List['Trade']:
        """📖 Загрузка сделок"""
        ...

    async def save_trading_session(self, session: 'TradingSession') -> None:
        """💾 Сохранение торговой сессии"""
        ...

    async def load_trading_session(self, session_id: str) -> Optional['TradingSession']:
        """📖 Загрузка торговой сессии"""
        ...


# ================= СЛУЖЕБНЫЕ ИНТЕРФЕЙСЫ =================

class IConfigurationService(Protocol):
    """⚙️ Интерфейс сервиса конфигурации"""

    def get_config(self, key: str, default: Any = None) -> Any:
        """📖 Получение конфигурации"""
        ...

    def set_config(self, key: str, value: Any) -> None:
        """📝 Установка конфигурации"""
        ...

    def reload_config(self) -> None:
        """🔄 Перезагрузка конфигурации"""
        ...

    def validate_config(self) -> Dict[str, Any]:
        """✅ Валидация конфигурации"""
        ...


class ILoggingService(Protocol):
    """📝 Интерфейс сервиса логирования"""

    def log_trade(self, trade: 'Trade') -> None:
        """📝 Логирование сделки"""
        ...

    def log_signal(self, signal: 'TradeSignal') -> None:
        """📝 Логирование сигнала"""
        ...

    def log_error(self, error: Exception, context: Dict[str, Any]) -> None:
        """❌ Логирование ошибки"""
        ...

    def log_system_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """📝 Логирование системного события"""
        ...


class IHealthCheckService(Protocol):
    """🏥 Интерфейс сервиса проверки здоровья системы"""

    async def check_api_health(self) -> Dict[str, Any]:
        """🌐 Проверка здоровья API"""
        ...

    async def check_database_health(self) -> Dict[str, Any]:
        """💾 Проверка здоровья БД"""
        ...

    async def check_trading_health(self) -> Dict[str, Any]:
        """📈 Проверка здоровья торговой системы"""
        ...

    async def get_system_status(self) -> Dict[str, Any]:
        """📊 Получение статуса системы"""
        ...


# ================= ФАБРИЧНЫЕ ИНТЕРФЕЙСЫ =================

class IServiceFactory(Protocol):
    """🏭 Интерфейс фабрики сервисов"""

    def create_trading_strategy(self, strategy_type: str) -> ITradingStrategy:
        """🎯 Создание торговой стратегии"""
        ...

    def create_risk_manager(self, risk_profile: str) -> IRiskManager:
        """🛡️ Создание риск-менеджера"""
        ...

    def create_position_manager(self) -> IPositionManager:
        """📊 Создание менеджера позиций"""
        ...


class IRepositoryFactory(Protocol):
    """🗄️ Интерфейс фабрики репозиториев"""

    def create_position_repository(self) -> IPersistenceService:
        """📊 Создание репозитория позиций"""
        ...

    def create_trade_repository(self) -> IPersistenceService:
        """💱 Создание репозитория сделок"""
        ...
