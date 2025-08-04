#!/usr/bin/env python3
"""🎯 Модели данных торговой системы"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Any
import uuid


class TradeAction(Enum):
    """🎯 Действия торговли"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderType(Enum):
    """📝 Типы ордеров"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"


class OrderStatus(Enum):
    """📋 Статусы ордеров"""
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RiskLevel(Enum):
    """🛡️ Уровни риска"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class StrategyType(Enum):
    """🎯 Типы стратегий"""
    DCA = "dca"
    PYRAMID = "pyramid"
    TRAILING_STOP = "trailing_stop"
    EMERGENCY_EXIT = "emergency_exit"
    ARBITRAGE = "arbitrage"


@dataclass(frozen=True)
class TradingPair:
    """💱 Торговая пара"""
    base: str  # DOGE
    quote: str  # EUR
    
    def __str__(self) -> str:
        return f"{self.base}_{self.quote}"
    
    @classmethod
    def from_string(cls, pair_str: str) -> 'TradingPair':
        """📝 Создание из строки типа 'DOGE_EUR'"""
        base, quote = pair_str.split('_')
        return cls(base=base, quote=quote)


@dataclass
class MarketData:
    """📊 Рыночные данные"""
    pair: TradingPair
    timestamp: datetime
    current_price: Decimal
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    volume_24h: Optional[Decimal] = None
    high_24h: Optional[Decimal] = None
    low_24h: Optional[Decimal] = None
    volatility: Optional[float] = None
    
    # Технические индикаторы
    rsi: Optional[float] = None
    macd: Optional[float] = None
    bollinger_upper: Optional[Decimal] = None
    bollinger_lower: Optional[Decimal] = None
    
    def __post_init__(self):
        """Валидация данных"""
        if self.current_price <= 0:
            raise ValueError("Цена должна быть положительной")


@dataclass
class TradeSignal:
    """📊 Торговый сигнал"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    strategy_name: str = ""
    strategy_type: StrategyType = StrategyType.DCA
    action: TradeAction = TradeAction.HOLD
    pair: Optional[TradingPair] = None
    quantity: Decimal = Decimal('0')
    price: Optional[Decimal] = None
    confidence: float = 0.0  # 0.0 - 1.0
    reason: str = ""
    priority: int = 1
    
    # Дополнительные параметры
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Валидация сигнала"""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Уверенность должна быть от 0.0 до 1.0")
        
        if self.action != TradeAction.HOLD and self.quantity <= 0:
            raise ValueError("Количество должно быть положительным для торговых действий")


@dataclass
class Position:
    """📊 Торговая позиция"""
    currency: str
    quantity: Decimal
    avg_price: Decimal
    total_cost: Decimal
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # История сделок позиции
    trades: List['Trade'] = field(default_factory=list)
    
    # Метаданные
    strategy_source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_empty(self) -> bool:
        """Пустая ли позиция"""
        return self.quantity <= 0
    
    def calculate_pnl(self, current_price: Decimal) -> Decimal:
        """💰 Расчет прибыли/убытка"""
        if self.is_empty:
            return Decimal('0')
        
        current_value = self.quantity * current_price
        return current_value - self.total_cost
    
    def calculate_pnl_percentage(self, current_price: Decimal) -> float:
        """📈 Расчет P&L в процентах"""
        if self.is_empty or self.total_cost <= 0:
            return 0.0
        
        pnl = self.calculate_pnl(current_price)
        return float(pnl / self.total_cost * 100)
    
    def update_after_trade(self, trade: 'Trade') -> None:
        """🔄 Обновление позиции после сделки"""
        self.updated_at = datetime.now()
        self.trades.append(trade)
        
        if trade.action == TradeAction.BUY:
            # Покупка - увеличиваем позицию
            new_quantity = self.quantity + trade.quantity
            new_cost = self.total_cost + (trade.quantity * trade.price)
            
            self.quantity = new_quantity
            self.total_cost = new_cost
            self.avg_price = new_cost / new_quantity if new_quantity > 0 else Decimal('0')
            
        elif trade.action == TradeAction.SELL:
            # Продажа - уменьшаем позицию
            self.quantity = max(Decimal('0'), self.quantity - trade.quantity)
            
            if self.quantity > 0:
                # Частичная продажа - пропорционально уменьшаем стоимость
                ratio = self.quantity / (self.quantity + trade.quantity)
                self.total_cost = self.total_cost * ratio
            else:
                # Полная продажа
                self.total_cost = Decimal('0')
                self.avg_price = Decimal('0')


@dataclass
class Trade:
    """💱 Торговая сделка"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    pair: TradingPair = field(default_factory=lambda: TradingPair("DOGE", "EUR"))
    action: TradeAction = TradeAction.HOLD
    quantity: Decimal = Decimal('0')
    price: Decimal = Decimal('0')
    commission: Decimal = Decimal('0')
    commission_currency: str = "EUR"
    
    # Связанные данные
    order_id: Optional[str] = None
    strategy_name: Optional[str] = None
    signal_id: Optional[str] = None
    
    # Результаты
    pnl: Optional[Decimal] = None
    pnl_percentage: Optional[float] = None
    
    # Метаданные
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def total_amount(self) -> Decimal:
        """💰 Общая сумма сделки"""
        return self.quantity * self.price
    
    @property
    def net_amount(self) -> Decimal:
        """💸 Сумма с учетом комиссии"""
        base_amount = self.total_amount
        if self.action == TradeAction.BUY:
            return base_amount + self.commission
        else:
            return base_amount - self.commission


@dataclass
class OrderResult:
    """📝 Результат создания ордера"""
    success: bool
    order_id: Optional[str] = None
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    filled_quantity: Decimal = Decimal('0')
    filled_price: Optional[Decimal] = None
    status: OrderStatus = OrderStatus.PENDING
    
    # Дополнительная информация
    exchange_response: Dict[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None


@dataclass
class RiskAssessment:
    """🛡️ Оценка рисков"""
    level: RiskLevel
    score: float  # 0.0 - 1.0
    max_position_size: Decimal
    recommended_action: TradeAction
    warnings: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    
    # Специфичные проверки
    position_size_ok: bool = True
    daily_loss_limit_ok: bool = True
    volatility_ok: bool = True
    correlation_ok: bool = True
    
    def is_acceptable(self) -> bool:
        """✅ Приемлемый ли риск"""
        return self.level in [RiskLevel.LOW, RiskLevel.MEDIUM]


@dataclass
class Portfolio:
    """📈 Портфель"""
    timestamp: datetime = field(default_factory=datetime.now)
    positions: Dict[str, Position] = field(default_factory=dict)
    cash_balance: Dict[str, Decimal] = field(default_factory=dict)
    
    # Метрики производительности
    total_value: Decimal = Decimal('0')
    total_pnl: Decimal = Decimal('0')
    daily_pnl: Decimal = Decimal('0')
    max_drawdown: float = 0.0
    
    def get_position(self, currency: str) -> Optional[Position]:
        """📊 Получение позиции"""
        return self.positions.get(currency)
    
    def calculate_total_value(self, prices: Dict[str, Decimal]) -> Decimal:
        """💰 Расчет общей стоимости портфеля"""
        total = Decimal('0')
        
        # Добавляем денежные балансы
        for currency, balance in self.cash_balance.items():
            if currency in prices:
                total += balance * prices[currency]
            else:
                total += balance  # Предполагаем базовую валюту
        
        # Добавляем стоимость позиций
        for currency, position in self.positions.items():
            if not position.is_empty and currency in prices:
                total += position.quantity * prices[currency]
        
        self.total_value = total
        return total


@dataclass
class PerformanceMetrics:
    """📊 Метрики производительности"""
    period_days: int
    total_trades: int
    profitable_trades: int
    total_pnl: Decimal
    total_return_pct: float
    
    # Статистики
    win_rate: float
    avg_profit_per_trade: Decimal
    best_trade: Decimal
    worst_trade: Decimal
    
    # Риск-метрики
    max_drawdown_pct: float
    sharpe_ratio: Optional[float] = None
    volatility: Optional[float] = None
    
    # Временные метрики
    avg_trade_duration_hours: Optional[float] = None
    trades_per_day: float = 0.0
    
    @property
    def loss_rate(self) -> float:
        """📉 Процент убыточных сделок"""
        return 100.0 - self.win_rate if self.total_trades > 0 else 0.0


@dataclass
class SystemHealth:
    """🏥 Здоровье системы"""
    timestamp: datetime = field(default_factory=datetime.now)
    uptime_hours: float = 0.0
    
    # Статистики API
    api_calls_total: int = 0
    api_calls_failed: int = 0
    api_success_rate: float = 100.0
    avg_response_time_ms: float = 0.0
    
    # Статистики торговли
    cycles_completed: int = 0
    last_trade_time: Optional[datetime] = None
    
    # Ошибки и предупреждения
    errors_count: int = 0
    warnings_count: int = 0
    last_error: Optional[str] = None
    
    # Ресурсы
    memory_usage_mb: Optional[float] = None
    cpu_usage_pct: Optional[float] = None
    
    @property
    def is_healthy(self) -> bool:
        """💚 Здорова ли система"""
        return (
            self.api_success_rate > 95.0 and
            self.errors_count < 10 and
            (self.last_error is None or 
             (datetime.now() - self.timestamp).total_seconds() > 3600)
        )


@dataclass
class ConfigProfile:
    """⚙️ Профиль конфигурации"""
    name: str
    description: str
    
    # Основные торговые параметры
    position_size_pct: float = 6.0  # 6% депозита
    min_profit_pct: float = 0.8     # 0.8% минимальная прибыль
    stop_loss_pct: float = 8.0      # 8% стоп-лосс
    
    # DCA параметры
    dca_enabled: bool = True
    dca_drop_threshold_pct: float = 1.5    # 1.5% падение для DCA
    dca_purchase_size_pct: float = 3.0     # 3% депозита на DCA
    dca_max_purchases: int = 5
    dca_cooldown_minutes: int = 20
    
    # Пирамидальные уровни
    pyramid_levels: List[Dict[str, float]] = field(default_factory=lambda: [
        {'profit_pct': 0.8, 'sell_pct': 25.0, 'min_eur': 0.08},
        {'profit_pct': 2.0, 'sell_pct': 35.0, 'min_eur': 0.15},
        {'profit_pct': 4.0, 'sell_pct': 25.0, 'min_eur': 0.25},
        {'profit_pct': 7.0, 'sell_pct': 15.0, 'min_eur': 0.40},
    ])
    
    # Система безопасности
    emergency_exit_enabled: bool = True
    emergency_critical_loss_pct: float = 15.0
    emergency_major_loss_pct: float = 12.0
    
    # Rate limiting
    api_calls_per_minute: int = 25
    api_calls_per_hour: int = 250
    
    # Интервалы обновления
    update_interval_seconds: int = 6
    
    @classmethod
    def create_conservative(cls) -> 'ConfigProfile':
        """🛡️ Консервативный профиль"""
        return cls(
            name="conservative",
            description="Консервативные настройки для минимизации рисков",
            position_size_pct=4.0,
            min_profit_pct=1.2,
            stop_loss_pct=6.0,
            dca_purchase_size_pct=2.0,
            dca_max_purchases=3,
            emergency_critical_loss_pct=10.0
        )
    
    @classmethod
    def create_aggressive(cls) -> 'ConfigProfile':
        """⚡ Агрессивный профиль"""
        return cls(
            name="aggressive", 
            description="Агрессивные настройки для максимизации прибыли",
            position_size_pct=10.0,
            min_profit_pct=0.6,
            stop_loss_pct=12.0,
            dca_purchase_size_pct=5.0,
            dca_max_purchases=7,
            update_interval_seconds=4
        )
    
    @classmethod
    def create_balanced(cls) -> 'ConfigProfile':
        """⚖️ Сбалансированный профиль (по умолчанию)"""
        return cls(
            name="balanced",
            description="Сбалансированные настройки риска и доходности"
        )


@dataclass
class Event:
    """📡 Событие системы"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    type: str = ""
    source: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    priority: int = 1  # 1 = низкий, 5 = критический
    
    # Обработка
    processed: bool = False
    processed_at: Optional[datetime] = None
    error: Optional[str] = None


# События торговой системы
@dataclass
class TradeExecutedEvent(Event):
    """💱 Событие выполнения сделки"""
    type: str = "trade_executed"
    trade: Optional[Trade] = None
    
    def __post_init__(self):
        if self.trade:
            self.data = {
                'trade_id': self.trade.id,
                'action': self.trade.action.value,
                'quantity': str(self.trade.quantity),
                'price': str(self.trade.price),
                'pair': str(self.trade.pair)
            }


@dataclass
class EmergencyExitEvent(Event):
    """🚨 Событие аварийного выхода"""
    type: str = "emergency_exit"
    priority: int = 5
    position: Optional[Position] = None
    reason: str = ""
    
    def __post_init__(self):
        self.data = {
            'reason': self.reason,
            'currency': self.position.currency if self.position else '',
            'quantity': str(self.position.quantity) if self.position else '0'
        }


@dataclass
class RiskLimitExceededEvent(Event):
    """⚠️ Событие превышения риск-лимитов"""
    type: str = "risk_limit_exceeded"
    priority: int = 4
    limit_type: str = ""
    current_value: float = 0.0
    limit_value: float = 0.0
    
    def __post_init__(self):
        self.data = {
            'limit_type': self.limit_type,
            'current_value': self.current_value,
            'limit_value': self.limit_value,
            'exceeded_by': self.current_value - self.limit_value
        }