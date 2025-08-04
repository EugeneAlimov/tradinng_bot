#!/usr/bin/env python3
"""🎯 Основные интерфейсы и протоколы торговой системы"""

from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, List, Optional, Union
from datetime import datetime
from decimal import Decimal

from .models import (
    TradeSignal, Position, Trade, MarketData, 
    OrderResult, RiskAssessment, TradingPair
)


class IExchangeAPI(Protocol):
    """🌐 Интерфейс для взаимодействия с биржей"""
    
    async def get_balance(self, currency: str) -> Decimal:
        """💰 Получение баланса валюты"""
        ...
    
    async def get_current_price(self, pair: TradingPair) -> Decimal:
        """💱 Получение текущей цены"""
        ...
    
    async def create_order(
        self, 
        pair: TradingPair, 
        quantity: Decimal, 
        price: Decimal, 
        order_type: str
    ) -> OrderResult:
        """📝 Создание ордера"""
        ...
    
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """📋 Статус ордера"""
        ...


class ITradingStrategy(ABC):
    """🎯 Базовый интерфейс для торговых стратегий"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Название стратегии"""
        pass
    
    @property
    @abstractmethod
    def priority(self) -> int:
        """Приоритет стратегии (выше = важнее)"""
        pass
    
    @abstractmethod
    async def analyze(
        self, 
        market_data: MarketData, 
        position: Optional[Position] = None
    ) -> TradeSignal:
        """📊 Анализ рынка и генерация сигнала"""
        pass
    
    @abstractmethod
    def can_execute(self, market_conditions: Dict[str, Any]) -> bool:
        """✅ Проверка возможности выполнения стратегии"""
        pass


class IRiskManager(Protocol):
    """🛡️ Интерфейс риск-менеджера"""
    
    async def assess_risk(
        self, 
        signal: TradeSignal, 
        position: Optional[Position],
        portfolio_state: Dict[str, Any]
    ) -> RiskAssessment:
        """🔍 Оценка рисков сигнала"""
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
        position: Position, 
        current_price: Decimal
    ) -> tuple[bool, str]:
        """🚨 Проверка необходимости аварийного выхода"""
        ...


class IPositionManager(Protocol):
    """📊 Интерфейс управления позициями"""
    
    async def get_position(self, currency: str) -> Optional[Position]:
        """📋 Получение текущей позиции"""
        ...
    
    async def update_position(self, trade: Trade) -> Position:
        """🔄 Обновление позиции после сделки"""
        ...
    
    async def close_position(self, currency: str, reason: str) -> None:
        """🔒 Закрытие позиции"""
        ...
    
    async def get_portfolio_summary(self) -> Dict[str, Any]:
        """📈 Сводка портфеля"""
        ...


class IAnalytics(Protocol):
    """📊 Интерфейс аналитики"""
    
    async def record_trade(self, trade: Trade) -> None:
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
    
    async def export_data(
        self, 
        format_type: str,
        date_from: datetime,
        date_to: datetime
    ) -> str:
        """💾 Экспорт данных"""
        ...


class ICache(Protocol):
    """🗄️ Интерфейс кэширования"""
    
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


class IRateLimiter(Protocol):
    """⚡ Интерфейс ограничения частоты запросов"""
    
    async def acquire(self, endpoint: str) -> None:
        """🎫 Получение разрешения на запрос"""
        ...
    
    async def get_stats(self) -> Dict[str, Any]:
        """📊 Статистика использования"""
        ...


class INotificationService(Protocol):
    """📢 Интерфейс уведомлений"""
    
    async def send_trade_notification(self, trade: Trade) -> None:
        """📈 Уведомление о сделке"""
        ...
    
    async def send_emergency_alert(self, message: str, urgency: str) -> None:
        """🚨 Экстренное уведомление"""
        ...
    
    async def send_daily_report(self, report: Dict[str, Any]) -> None:
        """📊 Дневной отчет"""
        ...


class ILogger(Protocol):
    """📝 Интерфейс логирования"""
    
    def info(self, message: str, **context) -> None:
        """ℹ️ Информационное сообщение"""
        ...
    
    def warning(self, message: str, **context) -> None:
        """⚠️ Предупреждение"""
        ...
    
    def error(self, message: str, **context) -> None:
        """❌ Ошибка"""
        ...
    
    def critical(self, message: str, **context) -> None:
        """🚨 Критическая ошибка"""
        ...


class IEventBus(Protocol):
    """🚌 Интерфейс шины событий"""
    
    async def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """📡 Публикация события"""
        ...
    
    async def subscribe(
        self, 
        event_type: str, 
        handler: callable
    ) -> None:
        """👂 Подписка на событие"""
        ...
    
    async def unsubscribe(
        self, 
        event_type: str, 
        handler: callable
    ) -> None:
        """🔇 Отписка от события"""
        ...


# Специфичные интерфейсы для торговых стратегий

class IDCAStrategy(ITradingStrategy):
    """🛒 Интерфейс DCA стратегии"""
    
    @abstractmethod
    async def should_buy_more(
        self, 
        current_price: Decimal,
        position: Position,
        market_data: MarketData
    ) -> tuple[bool, Decimal]:
        """🔍 Определение необходимости докупки"""
        pass


class IPyramidStrategy(ITradingStrategy):
    """🏗️ Интерфейс пирамидальной стратегии"""
    
    @abstractmethod
    async def get_sell_levels(
        self, 
        position: Position,
        current_price: Decimal
    ) -> List[tuple[Decimal, Decimal]]:  # [(price, quantity), ...]
        """📊 Получение уровней продажи"""
        pass


class IEmergencyExitStrategy(ITradingStrategy):
    """🚨 Интерфейс аварийного выхода"""
    
    @abstractmethod
    async def assess_emergency_conditions(
        self, 
        position: Position,
        current_price: Decimal,
        market_data: MarketData
    ) -> tuple[bool, str, float]:  # (should_exit, reason, sell_percentage)
        """🔍 Оценка аварийных условий"""
        pass


# Интерфейсы для внешних сервисов

class IMarketDataProvider(Protocol):
    """📊 Интерфейс поставщика рыночных данных"""
    
    async def get_market_data(self, pair: TradingPair) -> MarketData:
        """📈 Получение рыночных данных"""
        ...
    
    async def get_historical_data(
        self, 
        pair: TradingPair,
        period: str,
        limit: int = 100
    ) -> List[MarketData]:
        """📜 Исторические данные"""
        ...


class IPersistenceService(Protocol):
    """💾 Интерфейс сервиса персистентности"""
    
    async def save_position(self, position: Position) -> None:
        """💾 Сохранение позиции"""
        ...
    
    async def load_position(self, currency: str) -> Optional[Position]:
        """📖 Загрузка позиции"""
        ...
    
    async def save_trade(self, trade: Trade) -> None:
        """💾 Сохранение сделки"""
        ...
    
    async def load_trades(
        self, 
        currency: str,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> List[Trade]:
        """📖 Загрузка сделок"""
        ...
