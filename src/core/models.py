from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List
from enum import Enum
import uuid


# ================= БАЗОВЫЕ ENUMS =================

class OrderType(Enum):
    """📝 Типы ордеров"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """📋 Статусы ордеров"""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PositionStatus(Enum):
    """📊 Статусы позиций"""
    EMPTY = "empty"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class StrategySignalType(Enum):
    """🎯 Типы торговых сигналов"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    EMERGENCY_EXIT = "emergency_exit"
    DCA_BUY = "dca_buy"
    PYRAMID_SELL = "pyramid_sell"


class RiskLevel(Enum):
    """🛡️ Уровни риска"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EventType(Enum):
    """📡 Типы доменных событий"""
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

        # Нормализуем валюту к верхнему регистру
        object.__setattr__(self, 'currency', self.currency.upper())

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    def __add__(self, other: 'Money') -> 'Money':
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: 'Money') -> 'Money':
        if self.currency != other.currency:
            raise ValueError("Cannot subtract different currencies")
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, multiplier: Decimal) -> 'Money':
        return Money(self.amount * multiplier, self.currency)

    def __truediv__(self, divisor: Decimal) -> 'Money':
        if divisor == 0:
            raise ValueError("Cannot divide by zero")
        return Money(self.amount / divisor, self.currency)

    @property
    def is_zero(self) -> bool:
        """Проверка на нулевую сумму"""
        return self.amount == 0

    @property
    def is_positive(self) -> bool:
        """Проверка на положительную сумму"""
        return self.amount > 0


@dataclass(frozen=True)
class Price:
    """💲 Цена (Value Object)"""
    value: Decimal
    currency: str

    def __post_init__(self):
        if self.value < 0:
            raise ValueError("Price cannot be negative")
        if not self.currency:
            raise ValueError("Currency cannot be empty")

        # Нормализуем валюту к верхнему регистру
        object.__setattr__(self, 'currency', self.currency.upper())

    def __str__(self) -> str:
        return f"{self.value} {self.currency}"

    def __eq__(self, other) -> bool:
        if not isinstance(other, Price):
            return False
        return self.value == other.value and self.currency == other.currency

    def __lt__(self, other: 'Price') -> bool:
        if self.currency != other.currency:
            raise ValueError("Cannot compare prices in different currencies")
        return self.value < other.value

    def __le__(self, other: 'Price') -> bool:
        if self.currency != other.currency:
            raise ValueError("Cannot compare prices in different currencies")
        return self.value <= other.value

    def __gt__(self, other: 'Price') -> bool:
        if self.currency != other.currency:
            raise ValueError("Cannot compare prices in different currencies")
        return self.value > other.value

    def __ge__(self, other: 'Price') -> bool:
        if self.currency != other.currency:
            raise ValueError("Cannot compare prices in different currencies")
        return self.value >= other.value

    def percentage_change(self, other: 'Price') -> Decimal:
        """Процентное изменение относительно другой цены"""
        if self.currency != other.currency:
            raise ValueError("Cannot calculate percentage change for different currencies")
        if other.value == 0:
            return Decimal('0')
        return ((self.value - other.value) / other.value) * 100


# ================= ENTITIES =================

@dataclass
class Position:
    """📊 Торговая позиция (Entity)"""
    # Обязательные поля БЕЗ значений по умолчанию (идут первыми!)
    pair: TradingPair

    # Поля со значениями по умолчанию (идут после обязательных!)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    quantity: Decimal = Decimal('0')
    average_price: Decimal = Decimal('0')
    total_cost: Decimal = Decimal('0')
    status: PositionStatus = PositionStatus.EMPTY
    opened_at: Optional[datetime] = None
    updated_at: datetime = field(default_factory=datetime.now)
    trades: List['Trade'] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """Пуста ли позиция"""
        return self.quantity <= 0 or self.status == PositionStatus.EMPTY

    @property
    def is_open(self) -> bool:
        """Открыта ли позиция"""
        return self.quantity > 0 and self.status == PositionStatus.OPEN

    @property
    def current_value(self, current_price: Decimal) -> Decimal:
        """Текущая стоимость позиции"""
        return self.quantity * current_price

    def calculate_pnl(self, current_price: Decimal) -> Decimal:
        """📈 Расчет прибыли/убытка"""
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
        """Обновление позиции после сделки"""
        if trade.order_type == OrderType.BUY:
            # Покупка - увеличиваем позицию
            total_quantity = self.quantity + trade.quantity
            total_cost = self.total_cost + trade.total_cost

            if total_quantity > 0:
                self.average_price = total_cost / total_quantity

            self.quantity = total_quantity
            self.total_cost = total_cost

            if self.status == PositionStatus.EMPTY:
                self.status = PositionStatus.OPEN
                self.opened_at = datetime.now()

        elif trade.order_type == OrderType.SELL:
            # Продажа - уменьшаем позицию
            self.quantity -= trade.quantity
            if self.quantity <= 0:
                self.quantity = Decimal('0')
                self.status = PositionStatus.CLOSED

        self.updated_at = datetime.now()
        self.trades.append(trade)


@dataclass
class TradeSignal:
    """📈 Торговый сигнал (Entity)"""
    # Обязательные поля БЕЗ значений по умолчанию
    signal_type: StrategySignalType
    pair: TradingPair

    # Поля со значениями по умолчанию
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
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
        return self.signal_type in [
            StrategySignalType.BUY,
            StrategySignalType.SELL,
            StrategySignalType.EMERGENCY_EXIT,
            StrategySignalType.DCA_BUY,
            StrategySignalType.PYRAMID_SELL
        ]

    @property
    def age_seconds(self) -> float:
        """Возраст сигнала в секундах"""
        return (datetime.now() - self.timestamp).total_seconds()

    def is_stale(self, max_age_seconds: int = 300) -> bool:
        """Проверка устарелости сигнала (по умолчанию 5 минут)"""
        return self.age_seconds > max_age_seconds

    def estimate_trade_value(self) -> Optional[Money]:
        """Оценка стоимости торговой операции"""
        if not self.price or self.quantity <= 0:
            return None

        total_value = self.quantity * self.price
        return Money(total_value, self.pair.quote)


@dataclass
class MarketData:
    """📊 Рыночные данные (Entity)"""
    # Обязательные поля
    pair: TradingPair
    current_price: Price

    # Поля со значениями по умолчанию
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
    def mid_price(self) -> Optional[Decimal]:
        """Средняя цена между bid и ask"""
        if self.bid and self.ask:
            return (self.bid + self.ask) / Decimal('2')
        return None

    @property
    def spread_percentage(self) -> Optional[float]:
        """Спред в процентах"""
        if self.bid and self.ask and self.ask > 0:
            spread = self.ask - self.bid
            return float(spread / self.ask * 100)
        return None


@dataclass
class Trade:
    """💱 Выполненная сделка (Entity)"""
    # Обязательные поля
    pair: TradingPair
    order_type: OrderType
    quantity: Decimal
    price: Decimal
    total_cost: Decimal

    # Поля со значениями по умолчанию
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    commission: Decimal = Decimal('0')
    timestamp: datetime = field(default_factory=datetime.now)
    strategy_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def net_amount(self) -> Decimal:
        """Чистая сумма после комиссии"""
        return self.total_cost - self.commission


@dataclass
class OrderResult:
    """📋 Результат выполнения ордера (Entity)"""
    # Обязательные поля
    order_id: str
    pair: TradingPair
    order_type: OrderType
    status: OrderStatus
    requested_quantity: Decimal

    # Поля со значениями по умолчанию
    executed_quantity: Decimal = Decimal('0')
    requested_price: Optional[Decimal] = None
    executed_price: Optional[Decimal] = None
    total_cost: Decimal = Decimal('0')
    commission: Decimal = Decimal('0')
    timestamp: datetime = field(default_factory=datetime.now)
    error_message: Optional[str] = None

    @property
    def success(self) -> bool:
        """Успешно ли выполнен ордер"""
        return self.status == OrderStatus.FILLED

    @property
    def is_partial(self) -> bool:
        """Частично ли выполнен ордер"""
        return self.status == OrderStatus.PARTIALLY_FILLED

    @property
    def execution_percentage(self) -> float:
        """Процент выполнения ордера"""
        if self.requested_quantity == 0:
            return 0.0
        return float(self.executed_quantity / self.requested_quantity * 100)


# ================= AGGREGATES =================

@dataclass
class TradingSession:
    """📊 Торговая сессия (Aggregate Root)"""
    # Поля со значениями по умолчанию (все поля имеют дефолты)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    initial_balance: Dict[str, Decimal] = field(default_factory=dict)
    current_balance: Dict[str, Decimal] = field(default_factory=dict)
    positions: List[Position] = field(default_factory=list)
    executed_trades: List[Trade] = field(default_factory=list)
    generated_signals: List[TradeSignal] = field(default_factory=list)
    total_commission_paid: Decimal = Decimal('0')

    @property
    def is_active(self) -> bool:
        """Активна ли сессия"""
        return self.end_time is None

    @property
    def duration_minutes(self) -> Optional[float]:
        """Длительность сессии в минутах"""
        if not self.end_time:
            end_time = datetime.now()
        else:
            end_time = self.end_time

        duration = end_time - self.start_time
        return duration.total_seconds() / 60

    def add_trade(self, trade: Trade) -> None:
        """Добавление выполненной сделки"""
        self.executed_trades.append(trade)
        self.total_commission_paid += trade.commission

    def add_signal(self, signal: TradeSignal) -> None:
        """Добавление сгенерированного сигнала"""
        self.generated_signals.append(signal)


# ================= РЕЗУЛЬТАТ ТОРГОВОЙ ОПЕРАЦИИ =================

@dataclass
class TradeResult:
    """📊 Результат торговой операции"""
    # Обязательные поля
    trade_id: str
    pair: TradingPair

    # Поля со значениями по умолчанию
    success: bool = False
    pnl: Decimal = Decimal('0')
    commission: Decimal = Decimal('0')
    execution_time: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_profitable(self) -> bool:
        """Прибыльна ли сделка"""
        return self.pnl > 0

    @property
    def net_pnl(self) -> Decimal:
        """Чистая прибыль после комиссии"""
        return self.pnl - self.commission


# ================= FACTORY METHODS =================

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
    def create_price(value: str, currency: str) -> Price:
        """Создание цены"""
        return Price(Decimal(value), currency)

    @staticmethod
    def create_empty_position(pair: TradingPair) -> Position:
        """Создание пустой позиции"""
        return Position(pair=pair, status=PositionStatus.EMPTY)

    @staticmethod
    def create_buy_signal(
            pair: TradingPair,
            quantity: Decimal,
            price: Decimal,
            strategy_name: str,
            confidence: float = 0.5,
            reason: str = ""
    ) -> TradeSignal:
        """Создание сигнала на покупку"""
        return TradeSignal(
            signal_type=StrategySignalType.BUY,
            pair=pair,
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
            confidence=confidence,
            reason=reason
        )

    @staticmethod
    def create_sell_signal(
            pair: TradingPair,
            quantity: Decimal,
            price: Decimal,
            strategy_name: str,
            confidence: float = 0.5,
            reason: str = ""
    ) -> TradeSignal:
        """Создание сигнала на продажу"""
        return TradeSignal(
            signal_type=StrategySignalType.SELL,
            pair=pair,
            quantity=quantity,
            price=price,
            strategy_name=strategy_name,
            confidence=confidence,
            reason=reason
        )

    @staticmethod
    def create_hold_signal(
            pair: TradingPair,
            strategy_name: str,
            reason: str = "No trading opportunity"
    ) -> TradeSignal:
        """Создание сигнала удержания"""
        return TradeSignal(
            signal_type=StrategySignalType.HOLD,
            pair=pair,
            strategy_name=strategy_name,
            reason=reason,
            confidence=1.0  # HOLD всегда уверенный
        )


# ================= VALIDATION HELPERS =================

def validate_trading_pair(pair_str: str) -> bool:
    """✅ Валидация строки торговой пары"""
    try:
        TradingPair.from_string(pair_str)
        return True
    except ValueError:
        return False


def validate_decimal_positive(value: Decimal) -> bool:
    """✅ Валидация положительного Decimal"""
    return value > 0


def validate_confidence(confidence: float) -> bool:
    """✅ Валидация уверенности сигнала"""
    return 0.0 <= confidence <= 1.0


# ================= КОНСТАНТЫ =================

# Минимальные значения
MIN_TRADE_AMOUNT = Decimal('0.01')
MIN_PRICE = Decimal('0.00000001')
MAX_CONFIDENCE = 1.0
MIN_CONFIDENCE = 0.0

# Таймауты
DEFAULT_SIGNAL_TIMEOUT_SECONDS = 300  # 5 минут
DEFAULT_ORDER_TIMEOUT_SECONDS = 30  # 30 секунд

# Валюты по умолчанию
DEFAULT_BASE_CURRENCY = "DOGE"
DEFAULT_QUOTE_CURRENCY = "EUR"