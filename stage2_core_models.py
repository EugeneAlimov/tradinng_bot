#!/usr/bin/env python3
"""🏗️ Базовые модели данных торговой системы - Core слой"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List
from enum import Enum
import uuid


# ================= БАЗОВЫЕ ENUMS =================

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


class EventType(Enum):
    """Типы доменных событий"""
    TRADE_EXECUTED = "trade_executed"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_UPDATED = "position_updated"
    SIGNAL_GENERATED = "signal_generated"
    RISK_LIMIT_EXCEEDED = "risk_limit_exceeded"
    EMERGENCY_STOP_TRIGGERED = "emergency_stop_triggered"
    BALANCE_UPDATED = "balance_updated"


# ================= VALUE OBJECTS =================

@dataclass(frozen=True)
class TradingPair:
    """💱 Торговая пара (Value Object)"""
    base: str
    quote: str
    
    def __post_init__(self):
        if not self.base or not self.quote:
            raise ValueError("Base and quote currencies cannot be empty")
        
        # Нормализуем к верхнему регистру
        object.__setattr__(self, 'base', self.base.upper())
        object.__setattr__(self, 'quote', self.quote.upper())
    
    def __str__(self) -> str:
        return f"{self.base}_{self.quote}"
    
    @classmethod
    def from_string(cls, pair_str: str) -> 'TradingPair':
        """Создание из строки вида 'BTC_USD'"""
        try:
            base, quote = pair_str.split('_')
            return cls(base=base, quote=quote)
        except ValueError:
            raise ValueError(f"Invalid trading pair format: {pair_str}")
    
    @property
    def symbol(self) -> str:
        """Символ торговой пары"""
        return f"{self.base}{self.quote}"


@dataclass(frozen=True)
class Money:
    """💰 Денежная сумма (Value Object)"""
    amount: Decimal
    currency: str
    
    def __post_init__(self):
        if self.amount < 0:
            raise ValueError("Amount cannot be negative")
        if not self.currency:
            raise ValueError("Currency cannot be empty")
        
        object.__setattr__(self, 'currency', self.currency.upper())
    
    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"
    
    def __add__(self, other: 'Money') -> 'Money':
        if self.currency != other.currency:
            raise ValueError(f"Cannot add different currencies: {self.currency} and {other.currency}")
        return Money(self.amount + other.amount, self.currency)
    
    def __sub__(self, other: 'Money') -> 'Money':
        if self.currency != other.currency:
            raise ValueError(f"Cannot subtract different currencies: {self.currency} and {other.currency}")
        return Money(self.amount - other.amount, self.currency)
    
    def __mul__(self, multiplier: Decimal) -> 'Money':
        return Money(self.amount * multiplier, self.currency)
    
    def __truediv__(self, divisor: Decimal) -> 'Money':
        return Money(self.amount / divisor, self.currency)
    
    @property
    def is_zero(self) -> bool:
        return self.amount == Decimal('0')
    
    @property
    def is_positive(self) -> bool:
        return self.amount > Decimal('0')


@dataclass(frozen=True)
class Price:
    """💱 Цена (Value Object)"""
    value: Decimal
    pair: TradingPair
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        if self.value <= 0:
            raise ValueError("Price value must be positive")
    
    def __str__(self) -> str:
        return f"{self.value} {self.pair}"
    
    def calculate_value(self, quantity: Decimal) -> Money:
        """Расчет стоимости для заданного количества"""
        total_value = self.value * quantity
        return Money(total_value, self.pair.quote)
    
    @property
    def age_seconds(self) -> float:
        """Возраст цены в секундах"""
        return (datetime.now() - self.timestamp).total_seconds()
    
    def is_stale(self, max_age_seconds: int = 60) -> bool:
        """Проверка устарелости цены"""
        return self.age_seconds > max_age_seconds


# ================= ENTITIES =================

@dataclass
class Position:
    """📊 Торговая позиция (Entity)"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    currency: str = ""
    quantity: Decimal = Decimal('0')
    avg_price: Decimal = Decimal('0')
    total_cost: Decimal = Decimal('0')
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.currency:
            self.currency = self.currency.upper()
    
    @property
    def current_value(self) -> Decimal:
        """Текущая стоимость позиции по средней цене"""
        return self.quantity * self.avg_price
    
    @property
    def is_empty(self) -> bool:
        """Проверка пустой позиции"""
        return self.quantity == Decimal('0')
    
    def calculate_profit_loss(self, current_price: Decimal) -> Decimal:
        """Расчет прибыли/убытка"""
        if self.is_empty:
            return Decimal('0')
        
        current_value = self.quantity * current_price
        return current_value - self.total_cost
    
    def calculate_profit_loss_percentage(self, current_price: Decimal) -> Decimal:
        """Расчет прибыли/убытка в процентах"""
        if self.total_cost == 0:
            return Decimal('0')
        
        profit_loss = self.calculate_profit_loss(current_price)
        return (profit_loss / self.total_cost) * Decimal('100')
    
    def update_with_trade(self, quantity: Decimal, price: Decimal, trade_type: OrderType) -> None:
        """Обновление позиции после торговой операции"""
        if trade_type == OrderType.BUY:
            # Покупка - увеличиваем позицию
            new_total_cost = self.total_cost + (quantity * price)
            new_quantity = self.quantity + quantity
            
            if new_quantity > 0:
                self.avg_price = new_total_cost / new_quantity
            
            self.quantity = new_quantity
            self.total_cost = new_total_cost
            
        elif trade_type == OrderType.SELL:
            # Продажа - уменьшаем позицию
            if quantity > self.quantity:
                raise ValueError(f"Cannot sell {quantity}, only {self.quantity} available")
            
            # Пропорционально уменьшаем общую стоимость
            cost_reduction = (quantity / self.quantity) * self.total_cost
            self.quantity -= quantity
            self.total_cost -= cost_reduction
            
            # Средняя цена остается той же при частичной продаже
        
        self.updated_at = datetime.now()
    
    def close(self, exit_price: Decimal) -> Decimal:
        """Закрытие позиции"""
        if self.is_empty:
            return Decimal('0')
        
        profit_loss = self.calculate_profit_loss(exit_price)
        self.quantity = Decimal('0')
        self.total_cost = Decimal('0')
        self.updated_at = datetime.now()
        
        return profit_loss


@dataclass
class TradeSignal:
    """📈 Торговый сигнал (Entity)"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    signal_type: StrategySignalType = StrategySignalType.HOLD
    pair: Optional[TradingPair] = None
    quantity: Decimal = Decimal('0')
    price: Optional[Decimal] = None
    confidence: float = 0.0
    strategy_name: str = ""
    reason: str = ""
    risk_level: RiskLevel = RiskLevel.MEDIUM
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("Confidence must be between 0 and 1")
    
    @property
    def is_actionable(self) -> bool:
        """Проверка, требует ли сигнал действий"""
        return self.signal_type in [StrategySignalType.BUY, StrategySignalType.SELL, StrategySignalType.EMERGENCY_EXIT]
    
    @property
    def age_seconds(self) -> float:
        """Возраст сигнала в секундах"""
        return (datetime.now() - self.timestamp).total_seconds()
    
    def is_stale(self, max_age_seconds: int = 300) -> bool:
        """Проверка устарелости сигнала (по умолчанию 5 минут)"""
        return self.age_seconds > max_age_seconds
    
    def estimate_trade_value(self) -> Optional[Money]:
        """Оценка стоимости торговой операции"""
        if not self.pair or not self.price or self.quantity <= 0:
            return None
        
        total_value = self.quantity * self.price
        return Money(total_value, self.pair.quote)


@dataclass
class MarketData:
    """📊 Рыночные данные (Entity)"""
    pair: TradingPair
    price: Price
    volume_24h: Decimal = Decimal('0')
    high_24h: Optional[Decimal] = None
    low_24h: Optional[Decimal] = None
    change_24h: Optional[Decimal] = None
    change_24h_percent: Optional[Decimal] = None
    bid: Optional[Decimal] = None
    ask: Optional[Decimal] = None
    spread: Optional[Decimal] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def current_price(self) -> Decimal:
        """Текущая цена"""
        return self.price.value
    
    @property
    def mid_price(self) -> Optional[Decimal]:
        """Средняя цена между bid и ask"""
        if self.bid and self.ask:
            return (self.bid + self.ask) / Decimal('2')
        return None
    
    @property
    def spread_percentage(self) -> Optional[Decimal]:
        """Спред в процентах"""
        if self.bid and self.ask and self.ask > 0:
            return ((self.ask - self.bid) / self.ask) * Decimal('100')
        return None
    
    def is_stale(self, max_age_seconds: int = 60) -> bool:
        """Проверка устарелости данных"""
        age = (datetime.now() - self.timestamp).total_seconds()
        return age > max_age_seconds


@dataclass
class OrderResult:
    """📋 Результат исполнения ордера (Entity)"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str = ""
    pair: Optional[TradingPair] = None
    order_type: Optional[OrderType] = None
    status: OrderStatus = OrderStatus.PENDING
    requested_quantity: Decimal = Decimal('0')
    executed_quantity: Decimal = Decimal('0')
    requested_price: Optional[Decimal] = None
    executed_price: Optional[Decimal] = None
    commission: Decimal = Decimal('0')
    commission_currency: str = ""
    total_cost: Decimal = Decimal('0')
    created_at: datetime = field(default_factory=datetime.now)
    executed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_successful(self) -> bool:
        """Проверка успешности ордера"""
        return self.status == OrderStatus.FILLED
    
    @property
    def is_failed(self) -> bool:
        """Проверка неудачи ордера"""
        return self.status in [OrderStatus.FAILED, OrderStatus.CANCELLED]
    
    @property
    def is_partially_filled(self) -> bool:
        """Проверка частичного исполнения"""
        return self.status == OrderStatus.PARTIALLY_FILLED
    
    @property
    def fill_percentage(self) -> Decimal:
        """Процент исполнения ордера"""
        if self.requested_quantity == 0:
            return Decimal('0')
        return (self.executed_quantity / self.requested_quantity) * Decimal('100')
    
    def calculate_effective_price(self) -> Optional[Decimal]:
        """Расчет эффективной цены с учетом комиссии"""
        if self.executed_quantity == 0:
            return None
        
        if self.order_type == OrderType.BUY:
            # При покупке комиссия увеличивает стоимость
            return (self.total_cost + self.commission) / self.executed_quantity
        else:
            # При продаже комиссия уменьшает выручку
            return (self.total_cost - self.commission) / self.executed_quantity


# ================= ДОМЕННЫЕ СОБЫТИЯ =================

@dataclass
class DomainEvent:
    """📡 Базовое доменное событие"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = EventType.TRADE_EXECUTED
    timestamp: datetime = field(default_factory=datetime.now)
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    correlation_id: Optional[str] = None
    
    @property
    def age_seconds(self) -> float:
        """Возраст события в секундах"""
        return (datetime.now() - self.timestamp).total_seconds()


@dataclass
class TradeExecutedEvent(DomainEvent):
    """📈 Событие исполнения торговой операции"""
    order_result: OrderResult = field(default_factory=OrderResult)
    signal_id: Optional[str] = None
    position_before: Optional[Position] = None
    position_after: Optional[Position] = None
    
    def __post_init__(self):
        self.event_type = EventType.TRADE_EXECUTED
        self.data.update({
            'order_id': self.order_result.order_id,
            'pair': str(self.order_result.pair) if self.order_result.pair else None,
            'quantity': str(self.order_result.executed_quantity),
            'price': str(self.order_result.executed_price) if self.order_result.executed_price else None,
            'total_cost': str(self.order_result.total_cost)
        })


@dataclass
class PositionUpdatedEvent(DomainEvent):
    """📊 Событие обновления позиции"""
    position: Position = field(default_factory=Position)
    previous_quantity: Decimal = Decimal('0')
    change_reason: str = ""
    
    def __post_init__(self):
        self.event_type = EventType.POSITION_UPDATED
        self.data.update({
            'position_id': self.position.id,
            'currency': self.position.currency,
            'new_quantity': str(self.position.quantity),
            'previous_quantity': str(self.previous_quantity),
            'avg_price': str(self.position.avg_price),
            'reason': self.change_reason
        })


@dataclass
class SignalGeneratedEvent(DomainEvent):
    """📈 Событие генерации торгового сигнала"""
    signal: TradeSignal = field(default_factory=TradeSignal)
    
    def __post_init__(self):
        self.event_type = EventType.SIGNAL_GENERATED
        self.data.update({
            'signal_id': self.signal.id,
            'signal_type': self.signal.signal_type.value,
            'strategy_name': self.signal.strategy_name,
            'pair': str(self.signal.pair) if self.signal.pair else None,
            'quantity': str(self.signal.quantity),
            'confidence': self.signal.confidence,
            'reason': self.signal.reason
        })


@dataclass
class RiskLimitExceededEvent(DomainEvent):
    """🚨 Событие превышения лимита риска"""
    risk_type: str = ""
    current_value: Decimal = Decimal('0')
    limit_value: Decimal = Decimal('0')
    affected_positions: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        self.event_type = EventType.RISK_LIMIT_EXCEEDED
        self.data.update({
            'risk_type': self.risk_type,
            'current_value': str(self.current_value),
            'limit_value': str(self.limit_value),
            'affected_positions': self.affected_positions,
            'severity': 'high'
        })


# ================= АГРЕГАТЫ =================

@dataclass
class TradingSession:
    """📊 Торговая сессия (Aggregate Root)"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    initial_balance: Dict[str, Decimal] = field(default_factory=dict)
    current_balance: Dict[str, Decimal] = field(default_factory=dict)
    positions: List[Position] = field(default_factory=list)
    executed_trades: List[OrderResult] = field(default_factory=list)
    generated_signals: List[TradeSignal] = field(default_factory=list)
    total_profit_loss: Decimal = Decimal('0')
    total_commission_paid: Decimal = Decimal('0')
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_active(self) -> bool:
        """Проверка активности сессии"""
        return self.end_time is None
    
    @property
    def duration_seconds(self) -> float:
        """Длительность сессии в секундах"""
        end_time = self.end_time or datetime.now()
        return (end_time - self.start_time).total_seconds()
    
    @property
    def successful_trades_count(self) -> int:
        """Количество успешных торгов"""
        return sum(1 for trade in self.executed_trades if trade.is_successful)
    
    @property
    def failed_trades_count(self) -> int:
        """Количество неудачных торгов"""
        return sum(1 for trade in self.executed_trades if trade.is_failed)
    
    @property
    def success_rate(self) -> float:
        """Процент успешных торгов"""
        total_trades = len(self.executed_trades)
        if total_trades == 0:
            return 0.0
        return (self.successful_trades_count / total_trades) * 100
    
    def add_trade(self, order_result: OrderResult) -> None:
        """Добавление торговой операции"""
        self.executed_trades.append(order_result)
        
        if order_result.is_successful:
            self.total_commission_paid += order_result.commission
            # Обновляем P&L
            if order_result.order_type == OrderType.SELL:
                profit = order_result.total_cost - order_result.commission
                # Здесь нужна более сложная логика для расчета реальной прибыли
                # с учетом средней цены покупки
    
    def add_signal(self, signal: TradeSignal) -> None:
        """Добавление торгового сигнала"""
        self.generated_signals.append(signal)
    
    def get_position(self, currency: str) -> Optional[Position]:
        """Получение позиции по валюте"""
        for position in self.positions:
            if position.currency.upper() == currency.upper():
                return position
        return None
    
    def update_balance(self, currency: str, new_balance: Decimal) -> None:
        """Обновление баланса"""
        self.current_balance[currency.upper()] = new_balance
    
    def close_session(self) -> None:
        """Закрытие торговой сессии"""
        if not self.is_active:
            return
        
        self.end_time = datetime.now()
        # Закрываем все открытые позиции для расчета финального P&L
        # Здесь нужна логика получения текущих цен и закрытия позиций


# ================= ЗАВОДСКИЕ МЕТОДЫ =================

class ModelFactory:
    """🏭 Фабрика для создания моделей"""
    
    @staticmethod
    def create_trading_pair(pair_string: str) -> TradingPair:
        """Создание торговой пары из строки"""
        return TradingPair.from_string(pair_string)
    
    @staticmethod
    def create_money(amount: str, currency: str) -> Money:
        """Создание денежной суммы"""
        return Money(Decimal(amount), currency)
    
    @staticmethod
    def create_price(value: str, pair: TradingPair, timestamp: Optional[datetime] = None) -> Price:
        """Создание цены"""
        return Price(
            value=Decimal(value),
            pair=pair,
            timestamp=timestamp or datetime.now()
        )
    
    @staticmethod
    def create_buy_signal(pair: TradingPair, quantity: Decimal, price: Optional[Decimal] = None,
                         confidence: float = 0.5, strategy_name: str = "", reason: str = "") -> TradeSignal:
        """Создание сигнала покупки"""
        return TradeSignal(
            signal_type=StrategySignalType.BUY,
            pair=pair,
            quantity=quantity,
            price=price,
            confidence=confidence,
            strategy_name=strategy_name,
            reason=reason
        )
    
    @staticmethod
    def create_sell_signal(pair: TradingPair, quantity: Decimal, price: Optional[Decimal] = None,
                          confidence: float = 0.5, strategy_name: str = "", reason: str = "") -> TradeSignal:
        """Создание сигнала продажи"""
        return TradeSignal(
            signal_type=StrategySignalType.SELL,
            pair=pair,
            quantity=quantity,
            price=price,
            confidence=confidence,
            strategy_name=strategy_name,
            reason=reason
        )
    
    @staticmethod
    def create_hold_signal(strategy_name: str = "", reason: str = "No action needed") -> TradeSignal:
        """Создание сигнала удержания"""
        return TradeSignal(
            signal_type=StrategySignalType.HOLD,
            confidence=0.0,
            strategy_name=strategy_name,
            reason=reason
        )
    
    @staticmethod
    def create_position(currency: str, quantity: Decimal = Decimal('0'), 
                       avg_price: Decimal = Decimal('0')) -> Position:
        """Создание позиции"""
        return Position(
            currency=currency.upper(),
            quantity=quantity,
            avg_price=avg_price,
            total_cost=quantity * avg_price
        )
    
    @staticmethod
    def create_market_data(pair: TradingPair, price: Decimal, 
                          volume_24h: Decimal = Decimal('0'),
                          **kwargs) -> MarketData:
        """Создание рыночных данных"""
        price_obj = Price(value=price, pair=pair)
        return MarketData(
            pair=pair,
            price=price_obj,
            volume_24h=volume_24h,
            **kwargs
        )


# ================= КОНСТАНТЫ И КОНФИГУРАЦИЯ =================

class TradingConstants:
    """🎯 Торговые константы"""
    
    # Минимальные размеры
    MIN_ORDER_SIZE = Decimal("5.0")  # EUR
    MIN_QUANTITY = Decimal("0.000001")
    MIN_PRICE = Decimal("0.00000001")
    
    # Точность округления
    PRICE_PRECISION = 8
    QUANTITY_PRECISION = 6
    
    # Временные лимиты
    MAX_SIGNAL_AGE_SECONDS = 300  # 5 минут
    MAX_PRICE_AGE_SECONDS = 60    # 1 минута
    MAX_MARKET_DATA_AGE_SECONDS = 60  # 1 минута
    
    # Комиссии (примерные для EXMO)
    TAKER_FEE = Decimal("0.003")  # 0.3%
    MAKER_FEE = Decimal("0.002")  # 0.2%
    
    # Торговые пары по умолчанию
    DEFAULT_TRADING_PAIRS = [
        "DOGE_EUR", "DOGE_USD", "BTC_EUR", "ETH_EUR"
    ]