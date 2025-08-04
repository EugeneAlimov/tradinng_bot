#!/usr/bin/env python3
"""🔌 Миграция Part 1 - Core интерфейсы"""

import logging
from pathlib import Path


class Migration:
    """🔌 Миграция основных интерфейсов"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.src_dir = project_root / "src"
        self.core_dir = self.src_dir / "core"
        self.logger = logging.getLogger(__name__)

    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("🔌 Создание Core интерфейсов...")
            
            # Создаем структуру директорий
            self._create_directory_structure()
            
            # Создаем основные интерфейсы
            self._create_interfaces()
            
            self.logger.info("✅ Core интерфейсы созданы")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания интерфейсов: {e}")
            return False

    def _create_directory_structure(self):
        """📁 Создание структуры директорий"""
        dirs_to_create = [
            self.src_dir,
            self.core_dir,
        ]
        
        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
            
            # Создаем __init__.py
            init_file = dir_path / "__init__.py"
            if not init_file.exists():
                init_file.write_text('"""📦 Модуль торговой системы"""\n')

    def _create_interfaces(self):
        """🔌 Создание основных интерфейсов"""
        interfaces_content = '''#!/usr/bin/env python3
"""🔌 Основные интерфейсы торговой системы"""

from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, Optional, List
from decimal import Decimal
from datetime import datetime


class IExchangeAPI(Protocol):
    """🌐 Интерфейс API биржи"""
    
    async def get_balance(self, currency: str) -> Decimal:
        """💰 Получение баланса валюты"""
        ...
    
    async def get_current_price(self, pair: str) -> Decimal:
        """💱 Получение текущей цены пары"""
        ...
    
    async def create_order(self, pair: str, quantity: Decimal, price: Decimal, 
                          order_type: str) -> Dict[str, Any]:
        """📋 Создание ордера"""
        ...
    
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """📊 Получение статуса ордера"""
        ...


class ITradingStrategy(ABC):
    """🎯 Абстрактная торговая стратегия"""
    
    @abstractmethod
    async def analyze(self, market_data: 'MarketData', 
                     position: Optional['Position'] = None) -> 'TradeSignal':
        """📈 Анализ рынка и генерация сигнала"""
        pass
    
    @abstractmethod
    def get_strategy_name(self) -> str:
        """📛 Получение имени стратегии"""
        pass


class IRiskManager(Protocol):
    """🛡️ Интерфейс менеджера рисков"""
    
    async def assess_risk(self, signal: 'TradeSignal', 
                         position: Optional['Position']) -> Dict[str, Any]:
        """🔍 Оценка риска сигнала"""
        ...
    
    async def should_block_trading(self, reason: str = None) -> bool:
        """🚫 Проверка блокировки торговли"""
        ...


class IPositionManager(Protocol):
    """📊 Интерфейс менеджера позиций"""
    
    async def get_position(self, currency: str) -> Optional['Position']:
        """📋 Получение текущей позиции"""
        ...
    
    async def update_position(self, trade: Dict[str, Any]) -> None:
        """🔄 Обновление позиции после сделки"""
        ...
    
    async def calculate_profit_loss(self, position: 'Position', 
                                  current_price: Decimal) -> Decimal:
        """💹 Расчет прибыли/убытка"""
        ...


class ITradeExecutor(Protocol):
    """⚡ Интерфейс исполнителя сделок"""
    
    async def execute_trade(self, signal: 'TradeSignal') -> Dict[str, Any]:
        """🎯 Исполнение торгового сигнала"""
        ...
    
    async def cancel_order(self, order_id: str) -> bool:
        """❌ Отмена ордера"""
        ...


class IMarketDataProvider(Protocol):
    """📊 Интерфейс провайдера рыночных данных"""
    
    async def get_market_data(self, pair: 'TradingPair') -> 'MarketData':
        """📈 Получение рыночных данных"""
        ...
    
    async def get_historical_data(self, pair: 'TradingPair', 
                                 period: str, limit: int) -> List[Dict[str, Any]]:
        """📜 Получение исторических данных"""
        ...


class IEventBus(Protocol):
    """📡 Интерфейс шины событий"""
    
    async def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """📤 Публикация события"""
        ...
    
    async def subscribe(self, event_type: str, handler: callable) -> None:
        """📥 Подписка на события"""
        ...


class ILogger(Protocol):
    """📝 Интерфейс логгера"""
    
    def info(self, message: str, extra: Dict[str, Any] = None) -> None:
        """ℹ️ Информационное сообщение"""
        ...
    
    def warning(self, message: str, extra: Dict[str, Any] = None) -> None:
        """⚠️ Предупреждение"""
        ...
    
    def error(self, message: str, extra: Dict[str, Any] = None) -> None:
        """❌ Ошибка"""
        ...


class IConfigProvider(Protocol):
    """⚙️ Интерфейс провайдера конфигурации"""
    
    def get(self, key: str, default: Any = None) -> Any:
        """🔧 Получение значения конфигурации"""
        ...
    
    def set(self, key: str, value: Any) -> None:
        """🔧 Установка значения конфигурации"""
        ...
    
    def validate(self) -> bool:
        """✅ Валидация конфигурации"""
        ...


class IDependencyContainer(ABC):
    """🏗️ Интерфейс контейнера зависимостей"""
    
    @abstractmethod
    def register_singleton(self, service_type: type, implementation_type: type) -> None:
        """📌 Регистрация singleton сервиса"""
        pass
    
    @abstractmethod
    def register_transient(self, service_type: type, implementation_type: type) -> None:
        """🔄 Регистрация transient сервиса"""
        pass
    
    @abstractmethod
    def resolve(self, service_type: type) -> Any:
        """🔍 Разрешение зависимости"""
        pass
    
    @abstractmethod
    def is_registered(self, service_type: type) -> bool:
        """✅ Проверка регистрации сервиса"""
        pass


class IHealthChecker(Protocol):
    """🏥 Интерфейс проверки здоровья системы"""
    
    async def check_health(self) -> Dict[str, Any]:
        """🔍 Проверка состояния системы"""
        ...
    
    async def check_api_connectivity(self) -> bool:
        """🌐 Проверка подключения к API"""
        ...


class INotificationService(Protocol):
    """📢 Интерфейс сервиса уведомлений"""
    
    async def send_notification(self, message: str, level: str = "info") -> None:
        """📤 Отправка уведомления"""
        ...
    
    async def send_emergency_alert(self, message: str, context: Dict[str, Any]) -> None:
        """🚨 Отправка экстренного уведомления"""
        ...


# Базовые интерфейсы для адаптеров

class ILegacyBotAdapter(Protocol):
    """🔄 Интерфейс адаптера старого бота"""
    
    def get_legacy_bot(self) -> Any:
        """🤖 Получение экземпляра старого бота"""
        ...
    
    def adapt_strategy_call(self, method_name: str, *args, **kwargs) -> Any:
        """🔄 Адаптация вызова стратегии"""
        ...


class IStrategyAdapter(Protocol):
    """🎯 Интерфейс адаптера стратегий"""
    
    def adapt_legacy_strategy(self, strategy: Any) -> ITradingStrategy:
        """🔄 Адаптация старой стратегии к новому интерфейсу"""
        ...
    
    def get_adapted_strategies(self) -> List[ITradingStrategy]:
        """📋 Получение всех адаптированных стратегий"""
        ...


# Интерфейсы для валидации

class IValidator(Protocol):
    """✅ Базовый интерфейс валидатора"""
    
    def validate(self, data: Any) -> bool:
        """✅ Валидация данных"""
        ...
    
    def validate_with_errors(self, data: Any) -> tuple[bool, List[str]]:
        """✅ Валидация с получением списка ошибок"""
        ...


class ITradeValidator(IValidator):
    """✅ Интерфейс валидатора торговых операций"""
    
    def validate_trade_signal(self, signal: 'TradeSignal') -> bool:
        """✅ Валидация торгового сигнала"""
        ...
    
    def validate_dca_trade(self, current_price: Decimal, purchase_amount: Decimal, 
                          position: Optional['Position'] = None) -> bool:
        """✅ Валидация DCA сделки"""
        ...


# Интерфейсы для аналитики

class IAnalyticsService(Protocol):
    """📊 Интерфейс сервиса аналитики"""
    
    def record_trade(self, trade_data: Dict[str, Any]) -> None:
        """📝 Запись сделки"""
        ...
    
    def get_session_summary(self) -> Dict[str, Any]:
        """📊 Сводка текущей сессии"""
        ...
    
    def get_strategy_performance(self, strategy_name: str = None) -> Dict[str, Any]:
        """📈 Производительность стратегий"""
        ...


class IReportGenerator(Protocol):
    """📊 Интерфейс генератора отчетов"""
    
    async def generate_daily_report(self, date: datetime) -> Dict[str, Any]:
        """📅 Генерация дневного отчета"""
        ...
    
    async def generate_weekly_report(self) -> Dict[str, Any]:
        """📊 Генерация недельного отчета"""
        ...


# Интерфейсы для персистентности

class IRepository(Protocol):
    """💾 Базовый интерфейс репозитория"""
    
    async def save(self, entity: Any) -> None:
        """💾 Сохранение сущности"""
        ...
    
    async def load(self, key: str) -> Optional[Any]:
        """📥 Загрузка сущности"""
        ...
    
    async def delete(self, key: str) -> None:
        """🗑️ Удаление сущности"""
        ...


class IPositionRepository(IRepository):
    """📊 Интерфейс репозитория позиций"""
    
    async def save_position(self, position: 'Position') -> None:
        """💾 Сохранение позиции"""
        ...
    
    async def load_position(self, currency: str) -> Optional['Position']:
        """📥 Загрузка позиции"""
        ...
    
    async def get_all_positions(self) -> List['Position']:
        """📋 Получение всех позиций"""
        ...


class ITradeRepository(IRepository):
    """💱 Интерфейс репозитория сделок"""
    
    async def save_trade(self, trade: 'Trade') -> None:
        """💾 Сохранение сделки"""
        ...
    
    async def get_trades_history(self, limit: int = 100) -> List['Trade']:
        """📜 Получение истории сделок"""
        ...
    
    async def get_trades_by_currency(self, currency: str, days: int = 30) -> List['Trade']:
        """📊 Получение сделок по валюте"""
        ...


# Forward declarations для типизации
if False:  # TYPE_CHECKING
    from .models import MarketData, Position, TradeSignal, TradingPair, Trade
'''

        interfaces_file = self.core_dir / "interfaces.py"
        interfaces_file.write_text(interfaces_content)
        self.logger.info("  ✅ Создан interfaces.py")