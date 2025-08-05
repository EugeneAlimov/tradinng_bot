#!/usr/bin/env python3
"""🚨 Система исключений торговой системы - Core слой"""

from typing import Optional, Dict, Any, List, Callable
from decimal import Decimal
from datetime import datetime
import functools
import time
import logging


# ================= БАЗОВЫЕ ИСКЛЮЧЕНИЯ =================

class TradingSystemError(Exception):
    """🚨 Базовое исключение торговой системы"""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        recoverable: bool = False
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.context = context or {}
        self.recoverable = recoverable
        self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Преобразование в словарь для логирования"""
        return {
            'error_type': self.__class__.__name__,
            'error_code': self.error_code,
            'message': self.message,
            'context': self.context,
            'recoverable': self.recoverable,
            'timestamp': self.timestamp.isoformat()
        }

    def __str__(self) -> str:
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"[{self.error_code}] {self.message} (Context: {context_str})"
        return f"[{self.error_code}] {self.message}"


class ValidationError(TradingSystemError):
    """✅ Ошибка валидации"""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Optional[Any] = None,
        **kwargs
    ):
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

    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if config_key:
            context['config_key'] = config_key

        super().__init__(message, context=context, **kwargs)
        self.config_key = config_key


# ================= API ИСКЛЮЧЕНИЯ =================

class APIError(TradingSystemError):
    """🌐 Базовая ошибка API"""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if status_code:
            context['status_code'] = status_code
        if response_data:
            context['response_data'] = response_data

        # API ошибки часто восстанавливаемы
        kwargs.setdefault('recoverable', True)

        super().__init__(message, context=context, **kwargs)
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
        context = kwargs.get('context', {})
        if retry_after:
            context['retry_after'] = retry_after

        kwargs['recoverable'] = True  # Всегда восстанавливаемо
        super().__init__(message, context=context, **kwargs)
        self.retry_after = retry_after


class ExchangeError(APIError):
    """💱 Ошибка биржи"""

    def __init__(
        self,
        message: str,
        exchange_code: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if exchange_code:
            context['exchange_code'] = exchange_code

        super().__init__(message, context=context, **kwargs)
        self.exchange_code = exchange_code


class ConnectionError(APIError):
    """🔌 Ошибка соединения"""

    def __init__(self, message: str = "Connection failed", **kwargs):
        kwargs['recoverable'] = True
        super().__init__(message, **kwargs)


class AuthenticationError(APIError):
    """🔐 Ошибка аутентификации"""

    def __init__(self, message: str = "Authentication failed", **kwargs):
        kwargs['recoverable'] = False  # Обычно не восстанавливаемо
        super().__init__(message, **kwargs)


# ================= ТОРГОВЫЕ ИСКЛЮЧЕНИЯ =================

class TradingError(TradingSystemError):
    """📈 Базовая торговая ошибка"""

    def __init__(
        self,
        message: str,
        pair: Optional[str] = None,
        quantity: Optional[Decimal] = None,
        price: Optional[Decimal] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if pair:
            context['pair'] = pair
        if quantity:
            context['quantity'] = str(quantity)
        if price:
            context['price'] = str(price)

        super().__init__(message, context=context, **kwargs)
        self.pair = pair
        self.quantity = quantity
        self.price = price


class InsufficientBalanceError(TradingError):
    """💰 Недостаточно средств"""

    def __init__(
        self,
        required: Decimal,
        available: Decimal,
        currency: str,
        **kwargs
    ):
        message = f"Недостаточно {currency}: требуется {required}, доступно {available}"
        context = kwargs.get('context', {})
        context.update({
            'required': str(required),
            'available': str(available),
            'currency': currency,
            'deficit': str(required - available)
        })

        super().__init__(message, context=context, **kwargs)
        self.required = required
        self.available = available
        self.currency = currency


class OrderExecutionError(TradingError):
    """📋 Ошибка выполнения ордера"""

    def __init__(
        self,
        message: str,
        order_id: Optional[str] = None,
        order_status: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if order_id:
            context['order_id'] = order_id
        if order_status:
            context['order_status'] = order_status

        super().__init__(message, context=context, **kwargs)
        self.order_id = order_id
        self.order_status = order_status


class PositionError(TradingError):
    """📊 Ошибка позиции"""

    def __init__(
        self,
        message: str,
        currency: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if currency:
            context['currency'] = currency

        super().__init__(message, context=context, **kwargs)
        self.currency = currency


class PositionNotFoundError(PositionError):
    """🔍 Позиция не найдена"""

    def __init__(self, currency: str, **kwargs):
        message = f"Позиция для {currency} не найдена"
        super().__init__(message, currency=currency, **kwargs)


class InvalidSignalError(TradingError):
    """📊 Неверный торговый сигнал"""

    def __init__(
        self,
        message: str,
        signal_id: Optional[str] = None,
        strategy_name: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if signal_id:
            context['signal_id'] = signal_id
        if strategy_name:
            context['strategy_name'] = strategy_name

        super().__init__(message, context=context, **kwargs)
        self.signal_id = signal_id
        self.strategy_name = strategy_name


# ================= РИСК-МЕНЕДЖМЕНТ ИСКЛЮЧЕНИЯ =================

class RiskManagementError(TradingSystemError):
    """🛡️ Ошибка управления рисками"""

    def __init__(
        self,
        message: str,
        risk_level: Optional[str] = None,
        risk_factor: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if risk_level:
            context['risk_level'] = risk_level
        if risk_factor:
            context['risk_factor'] = risk_factor

        super().__init__(message, context=context, **kwargs)
        self.risk_level = risk_level
        self.risk_factor = risk_factor


class RiskLimitExceededError(RiskManagementError):
    """📊 Превышение лимита риска"""

    def __init__(
        self,
        message: str,
        limit_type: str,
        current_value: Optional[Decimal] = None,
        limit_value: Optional[Decimal] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        context['limit_type'] = limit_type
        if current_value:
            context['current_value'] = str(current_value)
        if limit_value:
            context['limit_value'] = str(limit_value)

        super().__init__(message, context=context, **kwargs)
        self.limit_type = limit_type
        self.current_value = current_value
        self.limit_value = limit_value


class EmergencyStopError(RiskManagementError):
    """🚨 Экстренная остановка"""

    def __init__(
        self,
        message: str = "Emergency stop triggered",
        trigger_reason: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if trigger_reason:
            context['trigger_reason'] = trigger_reason

        kwargs['recoverable'] = False  # Экстренная остановка требует вмешательства
        super().__init__(message, context=context, **kwargs)
        self.trigger_reason = trigger_reason


# ================= СТРАТЕГИЧЕСКИЕ ИСКЛЮЧЕНИЯ =================

class StrategyError(TradingSystemError):
    """🎯 Ошибка стратегии"""

    def __init__(
        self,
        message: str,
        strategy_name: Optional[str] = None,
        strategy_type: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if strategy_name:
            context['strategy_name'] = strategy_name
        if strategy_type:
            context['strategy_type'] = strategy_type

        super().__init__(message, context=context, **kwargs)
        self.strategy_name = strategy_name
        self.strategy_type = strategy_type


class StrategyNotAvailableError(StrategyError):
    """🚫 Стратегия недоступна"""

    def __init__(self, strategy_name: str, reason: Optional[str] = None, **kwargs):
        message = f"Стратегия '{strategy_name}' недоступна"
        if reason:
            message += f": {reason}"

        super().__init__(message, strategy_name=strategy_name, **kwargs)
        self.reason = reason


# ================= СИСТЕМНЫЕ ИСКЛЮЧЕНИЯ =================

class SystemError(TradingSystemError):
    """⚙️ Системная ошибка"""

    def __init__(
        self,
        message: str,
        component: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if component:
            context['component'] = component

        super().__init__(message, context=context, **kwargs)
        self.component = component


class DependencyError(SystemError):
    """📦 Ошибка зависимости"""

    def __init__(
        self,
        message: str,
        dependency_name: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if dependency_name:
            context['dependency_name'] = dependency_name

        super().__init__(message, context=context, **kwargs)
        self.dependency_name = dependency_name


class ServiceUnavailableError(SystemError):
    """🚫 Сервис недоступен"""

    def __init__(
        self,
        service_name: str,
        reason: Optional[str] = None,
        **kwargs
    ):
        message = f"Сервис '{service_name}' недоступен"
        if reason:
            message += f": {reason}"

        kwargs['recoverable'] = True
        super().__init__(message, component=service_name, **kwargs)
        self.service_name = service_name
        self.reason = reason


# ================= ИСКЛЮЧЕНИЯ ДАННЫХ =================

class DataError(TradingSystemError):
    """📊 Ошибка данных"""

    def __init__(
        self,
        message: str,
        data_type: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if data_type:
            context['data_type'] = data_type

        super().__init__(message, context=context, **kwargs)
        self.data_type = data_type


class DataIntegrityError(DataError):
    """🔍 Ошибка целостности данных"""

    def __init__(
        self,
        message: str,
        constraint: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get('context', {})
        if constraint:
            context['constraint'] = constraint

        super().__init__(message, context=context, **kwargs)
        self.constraint = constraint


class CacheError(DataError):
    """🗄️ Ошибка кэша"""

    def __init__(self, message: str, cache_key: Optional[str] = None, **kwargs):
        context = kwargs.get('context', {})
        if cache_key:
            context['cache_key'] = cache_key

        kwargs['recoverable'] = True
        super().__init__(message, context=context, **kwargs)
        self.cache_key = cache_key


# ================= УТИЛИТЫ ОБРАБОТКИ ИСКЛЮЧЕНИЙ =================

class ExceptionHandler:
    """🛡️ Обработчик исключений"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    def handle_exception(
        self,
        exception: Exception,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Обработка исключения с логированием"""

        if isinstance(exception, TradingSystemError):
            # Наши исключения - детальное логирование
            log_data = exception.to_dict()
            if context:
                log_data['additional_context'] = context

            if exception.recoverable:
                self.logger.warning(f"Recoverable error: {exception}", extra=log_data)
            else:
                self.logger.error(f"Critical error: {exception}", extra=log_data)
        else:
            # Внешние исключения
            self.logger.error(
                f"Unexpected error: {exception}",
                extra={'exception_type': type(exception).__name__, 'context': context},
                exc_info=True
            )

    def is_recoverable(self, exception: Exception) -> bool:
        """Проверка, можно ли восстановиться после ошибки"""
        if isinstance(exception, TradingSystemError):
            return exception.recoverable
        return False


def handle_trading_errors(
    exceptions: tuple = (TradingSystemError,),
    default_return: Any = None,
    log_errors: bool = True
):
    """🛡️ Декоратор для обработки торговых ошибок"""

    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except exceptions as e:
                if log_errors:
                    handler = ExceptionHandler()
                    handler.handle_exception(e)
                return default_return

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                if log_errors:
                    handler = ExceptionHandler()
                    handler.handle_exception(e)
                return default_return

        # Определяем, асинхронная ли функция
        if hasattr(func, '__code__') and func.__code__.co_flags & 0x80:
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def retry_on_error(
    max_attempts: int = 3,
    delay_seconds: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (APIError, ConnectionError)
):
    """🔄 Декоратор для повторных попыток при ошибках"""

    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt < max_attempts - 1:  # Не последняя попытка
                        delay = delay_seconds * (backoff_factor ** attempt)
                        await asyncio.sleep(delay)
                        continue

                    # Последняя попытка - поднимаем исключение
                    raise e

            # На всякий случай
            if last_exception:
                raise last_exception

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt < max_attempts - 1:
                        delay = delay_seconds * (backoff_factor ** attempt)
                        time.sleep(delay)
                        continue

                    raise e

            if last_exception:
                raise last_exception

        # Определяем тип функции
        if hasattr(func, '__code__') and func.__code__.co_flags & 0x80:
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


# ================= КОНТЕКСТНЫЕ МЕНЕДЖЕРЫ =================

class ErrorContext:
    """📋 Контекстный менеджер для обработки ошибок"""

    def __init__(
        self,
        operation_name: str,
        logger: Optional[logging.Logger] = None,
        reraise: bool = True
    ):
        self.operation_name = operation_name
        self.logger = logger or logging.getLogger(__name__)
        self.reraise = reraise
        self.handler = ExceptionHandler(self.logger)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            context = {'operation': self.operation_name}
            self.handler.handle_exception(exc_val, context)

            if not self.reraise:
                return True  # Подавляем исключение

        return False  # Пропускаем исключение дальше


# Импорт asyncio для retry декоратора
import asyncio# Исключения будут созданы
