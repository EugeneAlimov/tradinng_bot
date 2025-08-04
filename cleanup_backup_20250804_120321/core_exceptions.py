#!/usr/bin/env python3
"""🚨 Кастомные исключения торговой системы"""

from typing import Optional, Dict, Any


class TradingSystemError(Exception):
    """🚨 Базовое исключение торговой системы"""
    
    def __init__(
        self, 
        message: str, 
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}
    
    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class ConfigurationError(TradingSystemError):
    """⚙️ Ошибка конфигурации"""
    pass


class APIError(TradingSystemError):
    """🌐 Ошибка API"""
    
    def __init__(
        self, 
        message: str, 
        status_code: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.status_code = status_code
        self.response_data = response_data or {}


class RateLimitExceededError(APIError):
    """⚡ Превышение лимитов API"""
    
    def __init__(
        self, 
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ExchangeError(APIError):
    """💱 Ошибка биржи"""
    pass


class InsufficientBalanceError(TradingSystemError):
    """💰 Недостаточно средств"""
    
    def __init__(
        self, 
        required: float, 
        available: float, 
        currency: str
    ):
        message = f"Недостаточно {currency}: требуется {required}, доступно {available}"
        super().__init__(message)
        self.required = required
        self.available = available
        self.currency = currency


class PositionError(TradingSystemError):
    """📊 Ошибка позиции"""
    pass


class PositionNotFoundError(PositionError):
    """🔍 Позиция не найдена"""
    
    def __init__(self, currency: str):
        super().__init__(f"Позиция для {currency} не найдена")
        self.currency = currency


class InvalidPositionError(PositionError):
    """❌ Некорректная позиция"""
    pass


class StrategyError(TradingSystemError):
    """🎯 Ошибка стратегии"""
    pass


class StrategyNotReadyError(StrategyError):
    """⏸️ Стратегия не готова"""
    pass


class InvalidSignalError(StrategyError):
    """📊 Некорректный сигнал"""
    pass


class RiskManagementError(TradingSystemError):
    """🛡️ Ошибка риск-менеджмента"""
    pass


class RiskLimitExceededError(RiskManagementError):
    """⚠️ Превышение риск-лимитов"""
    
    def __init__(
        self, 
        limit_type: str, 
        current_value: float, 
        limit_value: float
    ):
        message = f"Превышен лимит {limit_type}: {current_value} > {limit_value}"
        super().__init__(message)
        self.limit_type = limit_type
        self.current_value = current_value
        self.limit_value = limit_value


class EmergencyExitRequired(RiskManagementError):
    """🚨 Требуется аварийный выход"""
    
    def __init__(
        self, 
        reason: str, 
        urgency: str = "high",
        sell_percentage: float = 1.0
    ):
        super().__init__(f"Аварийный выход: {reason}")
        self.reason = reason
        self.urgency = urgency
        self.sell_percentage = sell_percentage


class OrderError(TradingSystemError):
    """📝 Ошибка ордера"""
    pass


class OrderExecutionError(OrderError):
    """⚡ Ошибка исполнения ордера"""
    
    def __init__(
        self, 
        message: str, 
        order_id: Optional[str] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.order_id = order_id


class OrderValidationError(OrderError):
    """✅ Ошибка валидации ордера"""
    pass


class PriceValidationError(TradingSystemError):
    """💰 Ошибка валидации цены"""
    
    def __init__(
        self, 
        price: float, 
        reason: str,
        suggested_price: Optional[float] = None
    ):
        message = f"Некорректная цена {price}: {reason}"
        super().__init__(message)
        self.price = price
        self.reason = reason
        self.suggested_price = suggested_price


class AnalyticsError(TradingSystemError):
    """📊 Ошибка аналитики"""
    pass


class DataIntegrityError(TradingSystemError):
    """🔍 Ошибка целостности данных"""
    pass


class CacheError(TradingSystemError):
    """🗄️ Ошибка кэша"""
    pass


class PersistenceError(TradingSystemError):
    """💾 Ошибка сохранения"""
    pass


class NotificationError(TradingSystemError):
    """📢 Ошибка уведомлений"""
    pass


class SystemNotReadyError(TradingSystemError):
    """🚦 Система не готова"""
    
    def __init__(self, component: str, reason: str):
        super().__init__(f"Компонент {component} не готов: {reason}")
        self.component = component
        self.reason = reason


class CircuitBreakerOpenError(TradingSystemError):
    """🔌 Circuit breaker открыт"""
    
    def __init__(self, service: str, retry_after: Optional[int] = None):
        message = f"Circuit breaker открыт для {service}"
        if retry_after:
            message += f", повтор через {retry_after} секунд"
        super().__init__(message)
        self.service = service
        self.retry_after = retry_after


class ValidationError(TradingSystemError):
    """✅ Ошибка валидации"""
    
    def __init__(
        self, 
        field: str, 
        value: Any, 
        message: str
    ):
        super().__init__(f"Валидация поля '{field}' со значением '{value}': {message}")
        self.field = field
        self.value = value


class BacktestError(TradingSystemError):
    """📈 Ошибка бэктестинга"""
    pass


class DependencyError(TradingSystemError):
    """📦 Ошибка зависимости"""
    
    def __init__(self, dependency: str, reason: str):
        super().__init__(f"Зависимость '{dependency}' недоступна: {reason}")
        self.dependency = dependency
        self.reason = reason


# Утилиты для обработки исключений

def handle_api_error(func):
    """🛡️ Декоратор для обработки API ошибок"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "rate limit" in str(e).lower():
                raise RateLimitExceededError(str(e))
            elif "insufficient" in str(e).lower():
                raise InsufficientBalanceError(0, 0, "unknown")
            else:
                raise APIError(f"API ошибка в {func.__name__}: {e}")
    return wrapper


def require_position(func):
    """📊 Декоратор для проверки наличия позиции"""
    def wrapper(self, currency: str, *args, **kwargs):
        position = self.get_position(currency)
        if not position or position.is_empty:
            raise PositionNotFoundError(currency)
        return func(self, currency, *args, **kwargs)
    return wrapper


class ErrorContext:
    """📋 Контекст для сбора ошибок"""
    
    def __init__(self):
        self.errors: List[TradingSystemError] = []
        self.warnings: List[str] = []
    
    def add_error(self, error: TradingSystemError):
        """➕ Добавить ошибку"""
        self.errors.append(error)
    
    def add_warning(self, warning: str):
        """⚠️ Добавить предупреждение"""
        self.warnings.append(warning)
    
    def has_errors(self) -> bool:
        """❌ Есть ли ошибки"""
        return len(self.errors) > 0
    
    def has_warnings(self) -> bool:
        """⚠️ Есть ли предупреждения"""
        return len(self.warnings) > 0
    
    def raise_if_errors(self):
        """🚨 Поднять исключение если есть ошибки"""
        if self.has_errors():
            if len(self.errors) == 1:
                raise self.errors[0]
            else:
                error_messages = [str(e) for e in self.errors]
                raise TradingSystemError(
                    f"Множественные ошибки: {'; '.join(error_messages)}",
                    details={'errors': self.errors, 'warnings': self.warnings}
                )
    
    def get_summary(self) -> Dict[str, Any]:
        """📋 Сводка ошибок и предупреждений"""
        return {
            'errors_count': len(self.errors),
            'warnings_count': len(self.warnings),
            'errors': [str(e) for e in self.errors],
            'warnings': self.warnings
        }
