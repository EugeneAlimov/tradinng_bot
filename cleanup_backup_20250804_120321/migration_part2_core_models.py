#!/usr/bin/env python3
"""📋 Миграция Part 2 - Core модели"""

import logging
from pathlib import Path


class Migration:
    """📋 Миграция моделей данных"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.src_dir = project_root / "src"
        self.core_dir = self.src_dir / "core"
        self.logger = logging.getLogger(__name__)

    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("📋 Создание Core моделей...")
            
            # Создаем модели данных
            self._create_models()
            
            # Создаем исключения
            self._create_exceptions()
            
            self.logger.info("✅ Core модели созданы")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания моделей: {e}")
            return False

    def _create_models(self):
        """📋 Создание моделей данных"""
        models_content = '''#!/usr/bin/env python3
"""📋 Модели данных торговой системы"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List
from enum import Enum


class OrderType(Enum):
    """📋 Типы ордеров"""
    BUY = "buy"
    SELL = "sell"
    LIMIT_BUY = "limit_buy"
    LIMIT_SELL = "limit_sell"


class OrderStatus(Enum):
    """📊 Статусы ордеров"""
    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    PARTIALLY_FILLED = "partially_filled"


class SignalAction(Enum):
    """🎯 Действия торговых сигналов"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    EMERGENCY_EXIT = "emergency_exit"


class TradingMode(Enum):
    """🎮 Режимы торговли"""
    LIVE = "live"
    PAPER = "paper"
    BACKTEST = "backtest"


class LogLevel(Enum):
    """📝 Уровни логирования"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class TradingPair:
    """💱 Торговая пара"""
    base: str
    quote: str

    def __str__(self) -> str:
        return f"{self.base}_{self.quote}"

    def __post_init__(self):
        self.base = self.base.upper()
        self.quote = self.quote.upper()


@dataclass
class MarketData:
    """📊 Рыночные данные"""
    trading_pair: TradingPair
    current_price: Decimal
    volume_24h: Optional[Decimal] = None
    high_24h: Optional[Decimal] = None
    low_24h: Optional[Decimal] = None
    change_24h: Optional[Decimal] = None
    timestamp: datetime = field(default_factory=datetime.now)
    additional_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeSignal:
    """🎯 Торговый сигнал"""
    action: SignalAction
    trading_pair: TradingPair
    quantity: Decimal
    price: Optional[Decimal] = None
    confidence: float = 0.0
    reason: str = ""
    strategy_name: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Валидация confidence
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confidence должен быть между 0.0 и 1.0")
        
        # Валидация quantity
        if self.quantity <= 0:
            raise ValueError("Quantity должен быть положительным")


@dataclass
class Position:
    """📊 Торговая позиция"""
    currency: str
    quantity: Decimal
    avg_price: Decimal
    total_cost: Decimal
    timestamp: datetime = field(default_factory=datetime.now)
    trades: List[Dict[str, Any]] = field(default_factory=list)
    
    def calculate_current_value(self, current_price: Decimal) -> Decimal:
        """💰 Расчет текущей стоимости позиции"""
        return self.quantity * current_price
    
    def calculate_profit_loss(self, current_price: Decimal) -> Decimal:
        """📈 Расчет прибыли/убытка"""
        current_value = self.calculate_current_value(current_price)
        return current_value - self.total_cost
    
    def calculate_profit_loss_percentage(self, current_price: Decimal) -> Decimal:
        """📊 Расчет прибыли/убытка в процентах"""
        if self.total_cost == 0:
            return Decimal('0')
        profit_loss = self.calculate_profit_loss(current_price)
        return (profit_loss / self.total_cost) * Decimal('100')


@dataclass
class Order:
    """📋 Торговый ордер"""
    order_id: str
    trading_pair: TradingPair
    order_type: OrderType
    quantity: Decimal
    price: Optional[Decimal] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: Decimal = Decimal('0')
    avg_fill_price: Optional[Decimal] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_fully_filled(self) -> bool:
        """✅ Проверка полного исполнения"""
        return self.filled_quantity >= self.quantity
    
    def get_remaining_quantity(self) -> Decimal:
        """📊 Получение оставшегося количества"""
        return self.quantity - self.filled_quantity


@dataclass
class Trade:
    """💱 Выполненная сделка"""
    trade_id: str
    trading_pair: TradingPair
    side: str  # buy/sell
    quantity: Decimal
    price: Decimal
    commission: Decimal = Decimal('0')
    timestamp: datetime = field(default_factory=datetime.now)
    order_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_total_cost(self) -> Decimal:
        """💰 Получение общей стоимости сделки"""
        return self.quantity * self.price + self.commission


@dataclass
class RiskMetrics:
    """📊 Метрики риска"""
    max_drawdown: Decimal = Decimal('0')
    current_drawdown: Decimal = Decimal('0')
    sharpe_ratio: Optional[Decimal] = None
    profit_factor: Optional[Decimal] = None
    win_rate: Decimal = Decimal('0')
    avg_win: Decimal = Decimal('0')
    avg_loss: Decimal = Decimal('0')
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SystemStatus:
    """🏥 Статус системы"""
    is_healthy: bool = True
    api_connectivity: bool = True
    last_update: datetime = field(default_factory=datetime.now)
    active_strategies: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    uptime_seconds: int = 0
    
    def add_error(self, error: str) -> None:
        """❌ Добавление ошибки"""
        self.errors.append(f"{datetime.now().isoformat()}: {error}")
        self.is_healthy = False
    
    def add_warning(self, warning: str) -> None:
        """⚠️ Добавление предупреждения"""
        self.warnings.append(f"{datetime.now().isoformat()}: {warning}")


@dataclass
class StrategyPerformance:
    """📈 Производительность стратегии"""
    strategy_name: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit_loss: Decimal = Decimal('0')
    max_drawdown: Decimal = Decimal('0')
    last_trade_time: Optional[datetime] = None
    avg_trade_duration_minutes: Optional[int] = None
    
    def get_win_rate(self) -> float:
        """🏆 Получение процента выигрышных сделок"""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    def get_profit_factor(self) -> Optional[Decimal]:
        """💹 Получение фактора прибыли"""
        if self.losing_trades == 0 or self.total_profit_loss <= 0:
            return None
        
        # Приблизительный расчет (нужны детальные данные)
        avg_win = self.total_profit_loss / max(self.winning_trades, 1)
        avg_loss = abs(self.total_profit_loss) / max(self.losing_trades, 1)
        
        if avg_loss == 0:
            return None
        
        return avg_win / avg_loss


@dataclass
class ConfigProfile:
    """⚙️ Профиль конфигурации"""
    name: str
    description: str
    risk_level: str  # conservative, balanced, aggressive
    max_position_size_percent: Decimal
    stop_loss_percent: Decimal
    take_profit_percent: Decimal
    max_daily_trades: int
    cooldown_minutes: int
    
    def validate(self) -> bool:
        """✅ Валидация профиля"""
        return (
            0 < self.max_position_size_percent <= 100 and
            0 < self.stop_loss_percent <= 50 and
            0 < self.take_profit_percent <= 100 and
            self.max_daily_trades > 0 and
            self.cooldown_minutes >= 0
        )


@dataclass
class NotificationEvent:
    """📢 Событие уведомления"""
    event_type: str
    level: str  # info, warning, error, emergency
    message: str
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """📋 Конвертация в словарь"""
        return {
            'event_type': self.event_type,
            'level': self.level,
            'message': self.message,
            'context': self.context,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class HealthCheck:
    """🔍 Результат проверки здоровья"""
    name: str
    status: str  # healthy, warning, critical, unknown
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0
    
    def is_healthy(self) -> bool:
        """✅ Проверка здоровья"""
        return self.status == "healthy"


@dataclass
class TradingSession:
    """📊 Торговая сессия"""
    session_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    trades_count: int = 0
    total_profit_loss: Decimal = Decimal('0')
    max_drawdown: Decimal = Decimal('0')
    peak_profit: Decimal = Decimal('0')
    active_strategies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_trade_result(self, profit_loss: Decimal) -> None:
        """➕ Добавление результата сделки"""
        self.trades_count += 1
        self.total_profit_loss += profit_loss
        
        # Обновляем пик прибыли
        if self.total_profit_loss > self.peak_profit:
            self.peak_profit = self.total_profit_loss
        
        # Обновляем максимальную просадку
        current_drawdown = self.peak_profit - self.total_profit_loss
        if current_drawdown > self.max_drawdown:
            self.max_drawdown = current_drawdown
    
    def get_duration_hours(self) -> float:
        """⏰ Получение длительности сессии в часах"""
        end_time = self.end_time or datetime.now()
        duration = end_time - self.start_time
        return duration.total_seconds() / 3600
    
    def get_win_rate(self) -> float:
        """🏆 Получение процента выигрышных сделок (приблизительно)"""
        if self.trades_count == 0:
            return 0.0
        
        # Упрощенный расчет на основе общей прибыльности
        if self.total_profit_loss > 0:
            return min(100.0, 50.0 + float(self.total_profit_loss) * 10)
        else:
            return max(0.0, 50.0 + float(self.total_profit_loss) * 10)
'''

        models_file = self.core_dir / "models.py"
        models_file.write_text(models_content)
        self.logger.info("  ✅ Создан models.py")

    def _create_exceptions(self):
        """🚨 Создание кастомных исключений"""
        exceptions_content = '''#!/usr/bin/env python3
"""🚨 Кастомные исключения торговой системы"""

from typing import Optional, Dict, Any


class TradingSystemError(Exception):
    """🚨 Базовое исключение торговой системы"""
    
    def __init__(self, message: str, error_code: Optional[str] = None, 
                 context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}
    
    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class ConfigurationError(TradingSystemError):
    """⚙️ Ошибка конфигурации"""
    pass


class APIError(TradingSystemError):
    """🌐 Ошибка API"""
    
    def __init__(self, message: str, status_code: Optional[int] = None, 
                 response_data: Optional[Dict[str, Any]] = None):
        super().__init__(message, f"API_{status_code}" if status_code else "API_ERROR")
        self.status_code = status_code
        self.response_data = response_data or {}


class DependencyError(TradingSystemError):
    """🏗️ Ошибка Dependency Injection"""
    
    def __init__(self, service_name: str, message: str):
        super().__init__(f"Dependency error for {service_name}: {message}")
        self.service_name = service_name


class StrategyError(TradingSystemError):
    """🎯 Ошибка торговой стратегии"""
    
    def __init__(self, strategy_name: str, message: str, signal_data: Optional[Dict[str, Any]] = None):
        super().__init__(f"Strategy '{strategy_name}': {message}")
        self.strategy_name = strategy_name
        self.signal_data = signal_data or {}


class RiskManagementError(TradingSystemError):
    """🛡️ Ошибка управления рисками"""
    
    def __init__(self, message: str, risk_data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.risk_data = risk_data or {}


class PositionError(TradingSystemError):
    """📊 Ошибка управления позициями"""
    
    def __init__(self, message: str, position_data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.position_data = position_data or {}


class OrderError(TradingSystemError):
    """📋 Ошибка ордера"""
    
    def __init__(self, message: str, order_id: Optional[str] = None, 
                 order_data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.order_id = order_id
        self.order_data = order_data or {}


class ValidationError(TradingSystemError):
    """✅ Ошибка валидации"""
    
    def __init__(self, field_name: str, message: str, value: Any = None):
        super().__init__(f"Validation error for '{field_name}': {message}")
        self.field_name = field_name
        self.value = value


class InsufficientFundsError(TradingSystemError):
    """💰 Ошибка недостаточных средств"""
    
    def __init__(self, required_amount: float, available_amount: float, currency: str):
        message = f"Insufficient {currency}: required {required_amount}, available {available_amount}"
        super().__init__(message)
        self.required_amount = required_amount
        self.available_amount = available_amount
        self.currency = currency


class RateLimitError(APIError):
    """⏱️ Ошибка превышения лимита запросов"""
    
    def __init__(self, retry_after: Optional[int] = None):
        message = "API rate limit exceeded"
        if retry_after:
            message += f", retry after {retry_after} seconds"
        super().__init__(message, 429)
        self.retry_after = retry_after


class EmergencyExitError(TradingSystemError):
    """🚨 Ошибка аварийного выхода"""
    
    def __init__(self, message: str, exit_data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.exit_data = exit_data or {}


class AdapterError(TradingSystemError):
    """🔄 Ошибка адаптера"""
    
    def __init__(self, adapter_name: str, message: str):
        super().__init__(f"Adapter '{adapter_name}': {message}")
        self.adapter_name = adapter_name


class PersistenceError(TradingSystemError):
    """💾 Ошибка персистентности"""
    
    def __init__(self, operation: str, message: str, file_path: Optional[str] = None):
        super().__init__(f"Persistence error during {operation}: {message}")
        self.operation = operation
        self.file_path = file_path


class MonitoringError(TradingSystemError):
    """🏥 Ошибка мониторинга"""
    
    def __init__(self, check_name: str, message: str):
        super().__init__(f"Monitoring error in {check_name}: {message}")
        self.check_name = check_name


# Вспомогательные функции для обработки ошибок

def handle_api_error(func):
    """🌐 Декоратор для обработки API ошибок"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "rate limit" in str(e).lower():
                raise RateLimitError()
            elif "insufficient" in str(e).lower():
                raise InsufficientFundsError(0, 0, "unknown")
            else:
                raise APIError(str(e))
    return wrapper


def validate_decimal_positive(value: Any, field_name: str):
    """✅ Валидация положительного Decimal"""
    from decimal import Decimal, InvalidOperation
    
    try:
        decimal_value = Decimal(str(value))
        if decimal_value <= 0:
            raise ValidationError(field_name, "Must be positive", value)
        return decimal_value
    except (InvalidOperation, TypeError):
        raise ValidationError(field_name, "Must be a valid decimal number", value)


def validate_percentage(value: Any, field_name: str, min_val: float = 0, max_val: float = 100):
    """✅ Валидация процентного значения"""
    try:
        float_value = float(value)
        if not min_val <= float_value <= max_val:
            raise ValidationError(field_name, f"Must be between {min_val} and {max_val}", value)
        return float_value
    except (ValueError, TypeError):
        raise ValidationError(field_name, "Must be a valid number", value)


def validate_required_field(value: Any, field_name: str):
    """✅ Валидация обязательного поля"""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(field_name, "Field is required", value)
    return value


def safe_execute(func, error_class=TradingSystemError, default_value=None, log_errors=True):
    """🛡️ Безопасное выполнение функции с обработкой ошибок"""
    import logging
    logger = logging.getLogger(__name__)
    
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except error_class as e:
            if log_errors:
                logger.error(f"❌ Expected error in {func.__name__}: {e}")
            raise
        except Exception as e:
            if log_errors:
                logger.error(f"❌ Unexpected error in {func.__name__}: {e}")
            if default_value is not None:
                return default_value
            raise error_class(f"Unexpected error in {func.__name__}: {e}")
    
    return wrapper


class ErrorContext:
    """📋 Контекст для сбора ошибок"""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.has_critical_errors = False
    
    def add_error(self, message: str, is_critical: bool = False) -> None:
        """❌ Добавление ошибки"""
        self.errors.append(message)
        if is_critical:
            self.has_critical_errors = True
    
    def add_warning(self, message: str) -> None:
        """⚠️ Добавление предупреждения"""
        self.warnings.append(message)
    
    def has_errors(self) -> bool:
        """❓ Проверка наличия ошибок"""
        return len(self.errors) > 0
    
    def get_summary(self) -> Dict[str, Any]:
        """📊 Получение сводки ошибок"""
        return {
            'has_errors': self.has_errors(),
            'has_critical_errors': self.has_critical_errors,
            'errors_count': len(self.errors),
            'warnings_count': len(self.warnings),
            'errors': self.errors,
            'warnings': self.warnings
        }
    
    def raise_if_errors(self, error_class=TradingSystemError):
        """🚨 Генерация исключения при наличии ошибок"""
        if self.has_errors():
            error_summary = "; ".join(self.errors)
            raise error_class(f"Multiple errors occurred: {error_summary}")


if __name__ == "__main__":
    # Тестирование исключений
    try:
        raise ValidationError("test_field", "Test validation message", "test_value")
    except ValidationError as e:
        print(f"✅ Валидационная ошибка поймана: {e}")
        print(f"   Поле: {e.field_name}")
        print(f"   Значение: {e.value}")
    
    # Тестирование контекста ошибок
    context = ErrorContext()
    context.add_error("Тестовая ошибка")
    context.add_warning("Тестовое предупреждение")
    
    summary = context.get_summary()
    print(f"📊 Контекст ошибок: {summary['errors_count']} ошибок, {summary['warnings_count']} предупреждений")
    
    print("🚨 Система исключений готова")
'''

        exceptions_file = self.core_dir / "exceptions.py"
        exceptions_file.write_text(exceptions_content)
        self.logger.info("  ✅ Создан exceptions.py")