#!/usr/bin/env python3
"""🚨 Система исключений торговой системы - Core слой"""

from typing import Optional, Dict, Any, List, Callable
from decimal import Decimal
from datetime import datetime
import functools
import time


# ================= БАЗОВЫЕ ИСКЛЮЧЕНИЯ =================

class TradingSystemError(Exception):
    """🚨 Базовое исключение торговой системы"""

    def __init__(self, message: str, error_code: Optional[str] = None,
                 context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.context = context or {}
        self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь для логирования"""
        return {
            'error_type': self.__class__.__name__,
            'error_code': self.error_code,
            'message': self.message,
            'context': self.context,
            'timestamp': self.timestamp.isoformat()
        }

    def __str__(self) -> str:
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} (Context: {context_str})"
        return self.message


class ValidationError(TradingSystemError):
    """✅ Ошибка валидации"""

    def __init__(self, message: str, field: Optional[str] = None,
                 value: Optional[Any] = None, **kwargs):
        context = kwargs.get('context', {})
        if field:
            context['field'] = field
        if value is not None:
            context['value'] = str(value)

        super().__init__(message, context=context, **kwargs)
        self.field = field
        self.value = value


class ConfigurationError(TradingSystemError):
    """⚙️ Ошибка конфигурации"""

    def __init__(self, message: str, config_key: Optional[str] = None, **kwargs):
        context = kwargs.get('context', {})
        if config_key:
            context['config_key'] = config_key

        super().__init__(message, context=context, **kwargs)
        self.config_key = config_key


# ================= API ИСКЛЮЧЕНИЯ =================

class APIError(TradingSystemError):
    """🌐 Базовая ошибка API"""

    def __init__(self, message: str, status_code: Optional[int] = None,
                 response_data: Optional[Dict[str, Any]] = None, **kwargs):
        context = kwargs.get('context', {})
        if status_code:
            context['status_code'] = status_code
        if response_data:
            context['response_data'] = response_data

        super().__init__(message, context=context, **kwargs)
        self.status_code = status_code
        self.response_data = response_data


class APIConnectionError(APIError):
    """🔌 Ошибка подключения к API"""

    def __init__(self, message: str = "Failed to connect to exchange API", **kwargs):
        super().__init__(message, **kwargs)


class APITimeoutError(APIError):
    """⏰ Таймаут API запроса"""

    def __init__(self, message: str = "API request timeout",
                 timeout_seconds: Optional[float] = None, **kwargs):
        context = kwargs.get('context', {})
        if timeout_seconds:
            context['timeout_seconds'] = timeout_seconds

        super().__init__(message, context=context, **kwargs)
        self.timeout_seconds = timeout_seconds


class APIRateLimitError(APIError):
    """⏱️ Превышение лимита запросов API"""

    def __init__(self, message: str = "API rate limit exceeded",
                 retry_after: Optional[int] = None, **kwargs):
        context = kwargs.get('context', {})
        if retry_after:
            context['retry_after_seconds'] = retry_after

        super().__init__(message, context=context, **kwargs)
        self.retry_after = retry_after


class APIAuthenticationError(APIError):
    """🔐 Ошибка аутентификации API"""

    def __init__(self, message: str = "API authentication failed", **kwargs):
        super().__init__(message, error_code="API_AUTH_FAILED", **kwargs)


class APIInvalidResponseError(APIError):
    """📄 Некорректный ответ API"""

    def __init__(self, message: str = "Invalid API response format",
                 expected_format: Optional[str] = None, **kwargs):
        context = kwargs.get('context', {})
        if expected_format:
            context['expected_format'] = expected_format

        super().__init__(message, context=context, **kwargs)
        self.expected_format = expected_format


# ================= ТОРГОВЫЕ ИСКЛЮЧЕНИЯ =================

class TradingError(TradingSystemError):
    """📈 Базовая торговая ошибка"""
    pass


class InsufficientBalanceError(TradingError):
    """💰 Недостаточный баланс"""

    def __init__(self, message: str, currency: str, required_amount: Decimal,
                 available_amount: Decimal, **kwargs):
        context = kwargs.get('context', {})
        context.update({
            'currency': currency,
            'required_amount': str(required_amount),
            'available_amount': str(available_amount),
            'deficit': str(required_amount - available_amount)
        })

        super().__init__(message, context=context, **kwargs)
        self.currency = currency
        self.required_amount = required_amount
        self.available_amount = available_amount


class InvalidOrderParametersError(TradingError):
    """📋 Некорректные параметры ордера"""

    def __init__(self, message: str, pair: Optional[str] = None,
                 quantity: Optional[Decimal] = None, price: Optional[Decimal] = None, **kwargs):
        context = kwargs.get('context', {})
        if pair:
            context['trading_pair'] = pair
        if quantity is not None:
            context['quantity'] = str(quantity)
        if price is not None:
            context['price'] = str(price)

        super().__init__(message, context=context, **kwargs)
        self.pair = pair
        self.quantity = quantity
        self.price = price


class OrderExecutionError(TradingError):
    """⚡ Ошибка исполнения ордера"""

    def __init__(self, message: str, order_id: Optional[str] = None,
                 exchange_error: Optional[str] = None, **kwargs):
        context = kwargs.get('context', {})
        if order_id:
            context['order_id'] = order_id
        if exchange_error:
            context['exchange_error'] = exchange_error

        super().__init__(message, context=context, **kwargs)
        self.order_id = order_id
        self.exchange_error = exchange_error


class OrderNotFoundError(TradingError):
    """🔍 Ордер не найден"""

    def __init__(self, message: str, order_id: str, **kwargs):
        context = kwargs.get('context', {})
        context['order_id'] = order_id

        super().__init__(message, context=context, **kwargs)
        self.order_id = order_id


class PositionNotFoundError(TradingError):
    """📊 Позиция не найдена"""

    def __init__(self, message: str, currency: str, **kwargs):
        context = kwargs.get('context', {})
        context['currency'] = currency

        super().__init__(message, context=context, **kwargs)
        self.currency = currency


class InvalidTradingPairError(TradingError):
    """💱 Некорректная торговая пара"""

    def __init__(self, message: str, pair: str, **kwargs):
        context = kwargs.get('context', {})
        context['trading_pair'] = pair

        super().__init__(message, context=context, **kwargs)
        self.pair = pair


# ================= СТРАТЕГИЧЕСКИЕ ИСКЛЮЧЕНИЯ =================

class StrategyError(TradingSystemError):
    """🎯 Базовая ошибка стратегии"""
    pass


class StrategyNotFoundError(StrategyError):
    """🔍 Стратегия не найдена"""

    def __init__(self, message: str, strategy_name: str, **kwargs):
        context = kwargs.get('context', {})
        context['strategy_name'] = strategy_name

        super().__init__(message, context=context, **kwargs)
        self.strategy_name = strategy_name


class StrategyExecutionError(StrategyError):
    """⚡ Ошибка выполнения стратегии"""

    def __init__(self, message: str, strategy_name: str,
                 execution_step: Optional[str] = None, **kwargs):
        context = kwargs.get('context', {})
        context['strategy_name'] = strategy_name
        if execution_step:
            context['execution_step'] = execution_step

        super().__init__(message, context=context, **kwargs)
        self.strategy_name = strategy_name
        self.execution_step = execution_step


class InvalidSignalError(StrategyError):
    """📈 Некорректный торговый сигнал"""

    def __init__(self, message: str, signal_data: Optional[Dict[str, Any]] = None, **kwargs):
        context = kwargs.get('context', {})
        if signal_data:
            context['signal_data'] = signal_data

        super().__init__(message, context=context, **kwargs)
        self.signal_data = signal_data


class StaleSignalError(StrategyError):
    """⏰ Устаревший торговый сигнал"""

    def __init__(self, message: str, signal_age_seconds: float,
                 max_age_seconds: float, **kwargs):
        context = kwargs.get('context', {})
        context.update({
            'signal_age_seconds': signal_age_seconds,
            'max_age_seconds': max_age_seconds
        })

        super().__init__(message, context=context, **kwargs)
        self.signal_age_seconds = signal_age_seconds
        self.max_age_seconds = max_age_seconds


# ================= РИСК-МЕНЕДЖМЕНТ ИСКЛЮЧЕНИЯ =================

class RiskManagementError(TradingSystemError):
    """🛡️ Базовая ошибка риск-менеджмента"""
    pass


class RiskLimitExceededError(RiskManagementError):
    """🚨 Превышение лимита риска"""

    def __init__(self, message: str, risk_type: str, current_value: Decimal,
                 limit_value: Decimal, **kwargs):
        context = kwargs.get('context', {})
        context.update({
            'risk_type': risk_type,
            'current_value': str(current_value),
            'limit_value': str(limit_value),
            'excess_amount': str(current_value - limit_value)
        })

        super().__init__(message, context=context, **kwargs)
        self.risk_type = risk_type
        self.current_value = current_value
        self.limit_value = limit_value


class MaxDrawdownExceededError(RiskManagementError):
    """📉 Превышение максимальной просадки"""

    def __init__(self, message: str, current_drawdown: Decimal,
                 max_drawdown: Decimal, **kwargs):
        context = kwargs.get('context', {})
        context.update({
            'current_drawdown_percent': str(current_drawdown),
            'max_drawdown_percent': str(max_drawdown)
        })

        super().__init__(message, context=context, **kwargs)
        self.current_drawdown = current_drawdown
        self.max_drawdown = max_drawdown


class EmergencyStopTriggeredError(RiskManagementError):
    """🚨 Срабатывание экстренной остановки"""

    def __init__(self, message: str, trigger_reason: str, **kwargs):
        context = kwargs.get('context', {})
        context['trigger_reason'] = trigger_reason

        super().__init__(message, context=context, **kwargs)
        self.trigger_reason = trigger_reason


# ================= DEPENDENCY INJECTION ИСКЛЮЧЕНИЯ =================

class DependencyInjectionError(TradingSystemError):
    """💉 Базовая ошибка DI"""
    pass


class ServiceNotRegisteredError(DependencyInjectionError):
    """📋 Сервис не зарегистрирован"""

    def __init__(self, message: str, service_type: str, **kwargs):
        context = kwargs.get('context', {})
        context['service_type'] = service_type

        super().__init__(message, context=context, **kwargs)
        self.service_type = service_type


class CircularDependencyError(DependencyInjectionError):
    """🔄 Циклическая зависимость"""

    def __init__(self, message: str, dependency_chain: List[str], **kwargs):
        context = kwargs.get('context', {})
        context['dependency_chain'] = dependency_chain

        super().__init__(message, context=context, **kwargs)
        self.dependency_chain = dependency_chain


class ServiceCreationError(DependencyInjectionError):
    """🏭 Ошибка создания сервиса"""

    def __init__(self, message: str, service_type: str,
                 creation_error: Optional[str] = None, **kwargs):
        context = kwargs.get('context', {})
        context['service_type'] = service_type
        if creation_error:
            context['creation_error'] = creation_error

        super().__init__(message, context=context, **kwargs)
        self.service_type = service_type
        self.creation_error = creation_error


# ================= СОБЫТИЙНЫЕ ИСКЛЮЧЕНИЯ =================

class EventError(TradingSystemError):
    """📡 Базовая ошибка событий"""
    pass


class EventHandlerError(EventError):
    """🎯 Ошибка обработчика событий"""

    def __init__(self, message: str, event_type: str, handler_name: str, **kwargs):
        context = kwargs.get('context', {})
        context.update({
            'event_type': event_type,
            'handler_name': handler_name
        })

        super().__init__(message, context=context, **kwargs)
        self.event_type = event_type
        self.handler_name = handler_name


class EventBusError(EventError):
    """📡 Ошибка шины событий"""

    def __init__(self, message: str, bus_operation: str, **kwargs):
        context = kwargs.get('context', {})
        context['bus_operation'] = bus_operation

        super().__init__(message, context=context, **kwargs)
        self.bus_operation = bus_operation


# ================= ИСКЛЮЧЕНИЯ ПЕРСИСТЕНТНОСТИ =================

class PersistenceError(TradingSystemError):
    """💾 Ошибка сохранения данных"""

    def __init__(self, message: str, operation: str, entity_type: Optional[str] = None, **kwargs):
        context = kwargs.get('context', {})
        context['operation'] = operation
        if entity_type:
            context['entity_type'] = entity_type

        super().__init__(message, context=context, **kwargs)
        self.operation = operation
        self.entity_type = entity_type


class DataIntegrityError(PersistenceError):
    """🔍 Ошибка целостности данных"""

    def __init__(self, message: str, constraint: str, **kwargs):
        context = kwargs.get('context', {})
        context['constraint'] = constraint

        super().__init__(message, "integrity_check", context=context, **kwargs)
        self.constraint = constraint


# ================= СИСТЕМНЫЕ ИСКЛЮЧЕНИЯ =================

class SystemNotReadyError(TradingSystemError):
    """🚦 Система не готова"""

    def __init__(self, message: str, component: str, reason: str, **kwargs):
        context = kwargs.get('context', {})
        context.update({
            'component': component,
            'reason': reason
        })

        super().__init__(message, context=context, **kwargs)
        self.component = component
        self.reason = reason


class CircuitBreakerOpenError(TradingSystemError):
    """🔌 Circuit breaker открыт"""

    def __init__(self, message: str, service: str, retry_after: Optional[int] = None, **kwargs):
        context = kwargs.get('context', {})
        context['service'] = service
        if retry_after:
            context['retry_after_seconds'] = retry_after

        super().__init__(message, context=context, **kwargs)
        self.service = service
        self.retry_after = retry_after


class ResourceExhaustionError(TradingSystemError):
    """💾 Исчерпание ресурсов"""

    def __init__(self, message: str, resource_type: str,
                 current_usage: Optional[str] = None, **kwargs):
        context = kwargs.get('context', {})
        context['resource_type'] = resource_type
        if current_usage:
            context['current_usage'] = current_usage

        super().__init__(message, context=context, **kwargs)
        self.resource_type = resource_type
        self.current_usage = current_usage


# ================= УТИЛИТЫ ДЛЯ ОБРАБОТКИ ИСКЛЮЧЕНИЙ =================

class ExceptionHandler:
    """🛡️ Обработчик исключений"""

    @staticmethod
    def log_exception(exception: Exception, logger=None) -> None:
        """📝 Логирование исключения"""
        if logger is None:
            import logging
            logger = logging.getLogger(__name__)

        if isinstance(exception, TradingSystemError):
            logger.error(f"TradingSystemError: {exception.to_dict()}")
        else:
            logger.error(f"Unexpected error: {type(exception).__name__}: {str(exception)}")

    @staticmethod
    def handle_api_error(func):
        """🛡️ Декоратор для обработки API ошибок"""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except APIError:
                raise  # Пропускаем известные API ошибки
            except Exception as e:
                # Оборачиваем неизвестные ошибки в API ошибку
                raise APIError(f"Unexpected API error: {str(e)}") from e
        return wrapper

    @staticmethod
    def handle_trading_error(func):
        """🛡️ Декоратор для обработки торговых ошибок"""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except TradingError:
                raise  # Пропускаем известные торговые ошибки
            except Exception as e:
                # Оборачиваем неизвестные ошибки в торговую ошибку
                raise TradingError(f"Unexpected trading error: {str(e)}") from e
        return wrapper

    @staticmethod
    def with_retry(max_attempts: int = 3, delay_seconds: float = 1.0,
                   exceptions: tuple = (APITimeoutError, APIConnectionError)):
        """🔄 Декоратор для повторных попыток"""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                last_exception = None
                for attempt in range(max_attempts):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if attempt < max_attempts - 1:
                            time.sleep(delay_seconds * (attempt + 1))  # Экспоненциальная задержка
                        continue
                    except Exception as e:
                        # Неожиданная ошибка - не повторяем
                        raise e

                # Если все попытки исчерпаны
                raise last_exception
            return wrapper
        return decorator

    @staticmethod
    def is_retryable_error(exception: Exception) -> bool:
        """🔄 Проверка возможности повторной попытки"""
        retryable_types = (
            APITimeoutError,
            APIConnectionError,
            APIRateLimitError,
            ResourceExhaustionError
        )
        return isinstance(exception, retryable_types)

    @staticmethod
    def get_retry_delay(exception: Exception, attempt: int) -> float:
        """⏱️ Расчет задержки для повторной попытки"""
        base_delay = 1.0

        if isinstance(exception, APIRateLimitError) and exception.retry_after:
            return float(exception.retry_after)
        elif isinstance(exception, APITimeoutError):
            return base_delay * (2 ** attempt)  # Экспоненциальная задержка
        elif isinstance(exception, APIConnectionError):
            return base_delay * attempt  # Линейная задержка

        return base_delay


# ================= ФАБРИКА ИСКЛЮЧЕНИЙ =================

class ExceptionFactory:
    """🏭 Фабрика для создания исключений"""

    @staticmethod
    def create_api_error(status_code: int, message: str,
                        response_data: Optional[Dict[str, Any]] = None) -> APIError:
        """🌐 Создание API ошибки по коду статуса"""
        if status_code == 401:
            return APIAuthenticationError(message, response_data=response_data)
        elif status_code == 429:
            retry_after = None
            if response_data and 'retry_after' in response_data:
                retry_after = response_data['retry_after']
            return APIRateLimitError(message, retry_after=retry_after)
        elif status_code >= 500:
            return APIConnectionError(f"Server error: {message}")
        elif status_code == 408:
            return APITimeoutError(message)
        else:
            return APIError(message, status_code=status_code, response_data=response_data)

    @staticmethod
    def create_trading_error(error_type: str, message: str, **kwargs) -> TradingError:
        """📈 Создание торговой ошибки по типу"""
        if error_type == "insufficient_balance":
            return InsufficientBalanceError(message, **kwargs)
        elif error_type == "invalid_order":
            return InvalidOrderParametersError(message, **kwargs)
        elif error_type == "order_execution":
            return OrderExecutionError(message, **kwargs)
        elif error_type == "order_not_found":
            return OrderNotFoundError(message, **kwargs)
        elif error_type == "position_not_found":
            return PositionNotFoundError(message, **kwargs)
        elif error_type == "invalid_pair":
            return InvalidTradingPairError(message, **kwargs)
        else:
            return TradingError(message, **kwargs)

    @staticmethod
    def create_validation_error(field: str, value: Any, rule: str) -> ValidationError:
        """✅ Создание ошибки валидации"""
        message = f"Field '{field}' with value '{value}' violates rule: {rule}"
        return ValidationError(message, field=field, value=value)


# ================= ВАЛИДАТОРЫ ИСКЛЮЧЕНИЙ =================

class ExceptionValidator:
    """✅ Валидатор исключений"""

    @staticmethod
    def validate_error_context(context: Dict[str, Any]) -> List[str]:
        """Валидация контекста ошибки"""
        errors = []

        # Проверяем наличие обязательных полей
        if not isinstance(context, dict):
            errors.append("Context must be a dictionary")
            return errors

        # Проверяем значения
        for key, value in context.items():
            if value is None:
                errors.append(f"Context key '{key}' cannot be None")
            elif isinstance(value, str) and not value.strip():
                errors.append(f"Context key '{key}' cannot be empty string")

        return errors

    @staticmethod
    def is_critical_error(exception: Exception) -> bool:
        """🚨 Проверка критичности ошибки"""
        critical_types = (
            APIAuthenticationError,
            EmergencyStopTriggeredError,
            MaxDrawdownExceededError,
            SystemNotReadyError,
            CircularDependencyError
        )
        return isinstance(exception, critical_types)

    @staticmethod
    def should_stop_trading(exception: Exception) -> bool:
        """🛑 Проверка необходимости остановки торговли"""
        stop_trading_types = (
            APIAuthenticationError,
            EmergencyStopTriggeredError,
            MaxDrawdownExceededError,
            RiskLimitExceededError
        )
        return isinstance(exception, stop_trading_types)


# ================= ГЛОБАЛЬНЫЙ ОБРАБОТЧИК =================

_global_exception_handler: Optional[ExceptionHandler] = None


def set_global_exception_handler(handler: ExceptionHandler) -> None:
    """🌍 Установка глобального обработчика исключений"""
    global _global_exception_handler
    _global_exception_handler = handler


def get_global_exception_handler() -> ExceptionHandler:
    """🌍 Получение глобального обработчика исключений"""
    global _global_exception_handler
    if _global_exception_handler is None:
        _global_exception_handler = ExceptionHandler()
    return _global_exception_handler


def log_error(exception: Exception) -> None:
    """📝 Логирование ошибки через глобальный обработчик"""
    handler = get_global_exception_handler()
    handler.log_exception(exception)


# ================= ФОРМАТИРОВАНИЕ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =================

def format_exception_for_user(exception: Exception) -> str:
    """👤 Форматирование исключения для пользователя"""
    if isinstance(exception, APIAuthenticationError):
        return "🔐 Ошибка авторизации API. Проверьте ключи доступа."
    elif isinstance(exception, APIRateLimitError):
        retry_msg = f" Повторите через {exception.retry_after}с." if exception.retry_after else ""
        return f"⏱️ Превышен лимит запросов к API.{retry_msg}"
    elif isinstance(exception, InsufficientBalanceError):
        return f"💰 Недостаточно средств: нужно {exception.required_amount} {exception.currency}, доступно {exception.available_amount}"
    elif isinstance(exception, RiskLimitExceededError):
        return f"🚨 Превышен лимит риска: {exception.risk_type} ({exception.current_value} > {exception.limit_value})"
    elif isinstance(exception, TradingSystemError):
        return f"⚠️ {exception.message}"
    else:
        return f"❌ Системная ошибка: {str(exception)}"


def create_error_response(exception: Exception) -> Dict[str, Any]:
    """📊 Создание структурированного ответа об ошибке"""
    if isinstance(exception, TradingSystemError):
        return {
            'success': False,
            'error': {
                'type': exception.__class__.__name__,
                'code': exception.error_code,
                'message': exception.message,
                'context': exception.context,
                'timestamp': exception.timestamp.isoformat(),
                'user_message': format_exception_for_user(exception),
                'is_critical': ExceptionValidator.is_critical_error(exception),
                'should_stop_trading': ExceptionValidator.should_stop_trading(exception)
            }
        }
    else:
        return {
            'success': False,
            'error': {
                'type': type(exception).__name__,
                'code': 'UNKNOWN_ERROR',
                'message': str(exception),
                'context': {},
                'timestamp': datetime.now().isoformat(),
                'user_message': format_exception_for_user(exception),
                'is_critical': False,
                'should_stop_trading': False
            }
        }


# ================= КОНСТАНТЫ ОШИБОК =================

class ErrorCodes:
    """📋 Коды ошибок"""

    # API ошибки
    API_CONNECTION_FAILED = "API_001"
    API_TIMEOUT = "API_002"
    API_RATE_LIMIT = "API_003"
    API_AUTH_FAILED = "API_004"
    API_INVALID_RESPONSE = "API_005"

    # Торговые ошибки
    INSUFFICIENT_BALANCE = "TRADE_001"
    INVALID_ORDER_PARAMS = "TRADE_002"
    ORDER_EXECUTION_FAILED = "TRADE_003"
    ORDER_NOT_FOUND = "TRADE_004"
    POSITION_NOT_FOUND = "TRADE_005"
    INVALID_TRADING_PAIR = "TRADE_006"

    # Стратегические ошибки
    STRATEGY_NOT_FOUND = "STRATEGY_001"
    STRATEGY_EXECUTION_FAILED = "STRATEGY_002"
