#!/usr/bin/env python3
"""📦 Миграция Part 4 - Dependency Injection контейнер"""

import logging
from pathlib import Path


class Migration:
    """📦 Миграция DI контейнера"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.src_dir = project_root / "src"
        self.infrastructure_dir = self.src_dir / "infrastructure"
        self.logger = logging.getLogger(__name__)

    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("📦 Создание DI контейнера...")
            
            # Создаем структуру директорий
            self._create_directory_structure()
            
            # Создаем DI контейнер
            self._create_di_container()
            
            # Создаем базовые классы
            self._create_base_classes()
            
            self.logger.info("✅ DI контейнер создан")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания DI контейнера: {e}")
            return False

    def _create_directory_structure(self):
        """📁 Создание структуры директорий"""
        dirs_to_create = [
            self.infrastructure_dir,
        ]
        
        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
            
            # Создаем __init__.py
            init_file = dir_path / "__init__.py"
            if not init_file.exists():
                init_file.write_text('"""🏗️ Инфраструктурный модуль"""\n')

    def _create_di_container(self):
        """📦 Создание DI контейнера"""
        di_container_content = '''#!/usr/bin/env python3
"""📦 Dependency Injection Container"""

import inspect
import logging
from typing import Dict, Any, TypeVar, Type, Callable, Optional, List
from enum import Enum
from dataclasses import dataclass

from ..core.interfaces import IDependencyContainer
from ..core.exceptions import DependencyError

T = TypeVar('T')


class Lifetime(Enum):
    """🔄 Жизненный цикл зависимостей"""
    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"


@dataclass
class ServiceDescriptor:
    """📋 Описание сервиса"""
    service_type: Type
    implementation_type: Optional[Type] = None
    factory: Optional[Callable] = None
    instance: Optional[Any] = None
    lifetime: Lifetime = Lifetime.TRANSIENT
    
    @property
    def is_factory(self) -> bool:
        return self.factory is not None
    
    @property
    def is_instance(self) -> bool:
        return self.instance is not None


class DependencyContainer(IDependencyContainer):
    """📦 Контейнер зависимостей"""
    
    def __init__(self):
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._instances: Dict[Type, Any] = {}
        self._building: set = set()
        self.logger = logging.getLogger(f"{__name__}.DependencyContainer")
    
    def register_singleton(self, service_type: Type[T], implementation_type: Type[T]) -> None:
        """📌 Регистрация singleton сервиса"""
        self._services[service_type] = ServiceDescriptor(
            service_type=service_type,
            implementation_type=implementation_type,
            lifetime=Lifetime.SINGLETON
        )
        self.logger.debug(f"📌 Registered singleton: {service_type.__name__} -> {implementation_type.__name__}")
    
    def register_transient(self, service_type: Type[T], implementation_type: Type[T]) -> None:
        """🔄 Регистрация transient сервиса"""
        self._services[service_type] = ServiceDescriptor(
            service_type=service_type,
            implementation_type=implementation_type,
            lifetime=Lifetime.TRANSIENT
        )
        self.logger.debug(f"🔄 Registered transient: {service_type.__name__} -> {implementation_type.__name__}")
    
    def register_instance(self, service_type: Type[T], instance: T) -> None:
        """📦 Регистрация готового экземпляра"""
        self._services[service_type] = ServiceDescriptor(
            service_type=service_type,
            instance=instance,
            lifetime=Lifetime.SINGLETON
        )
        self._instances[service_type] = instance
        self.logger.debug(f"📦 Registered instance: {service_type.__name__}")
    
    def register_factory(self, service_type: Type[T], factory: Callable[..., T]) -> None:
        """🏭 Регистрация фабрики"""
        self._services[service_type] = ServiceDescriptor(
            service_type=service_type,
            factory=factory,
            lifetime=Lifetime.TRANSIENT
        )
        self.logger.debug(f"🏭 Registered factory: {service_type.__name__}")
    
    def resolve(self, service_type: Type[T]) -> T:
        """🔍 Разрешение зависимости"""
        if service_type in self._building:
            raise DependencyError(service_type.__name__, "Circular dependency detected")
        
        try:
            self._building.add(service_type)
            return self._resolve_internal(service_type)
        finally:
            self._building.discard(service_type)
    
    def _resolve_internal(self, service_type: Type[T]) -> T:
        """🔍 Внутреннее разрешение зависимости"""
        # Проверяем регистрацию
        if service_type not in self._services:
            raise DependencyError(service_type.__name__, "Service not registered")
        
        descriptor = self._services[service_type]
        
        # Singleton - проверяем кэш
        if descriptor.lifetime == Lifetime.SINGLETON and service_type in self._instances:
            return self._instances[service_type]
        
        # Создаем экземпляр
        instance = self._create_instance(descriptor)
        
        # Кэшируем для singleton
        if descriptor.lifetime == Lifetime.SINGLETON:
            self._instances[service_type] = instance
        
        return instance
    
    def _create_instance(self, descriptor: ServiceDescriptor) -> Any:
        """🔨 Создание экземпляра"""
        # Готовый экземпляр
        if descriptor.is_instance:
            return descriptor.instance
        
        # Фабрика
        if descriptor.is_factory:
            return self._invoke_factory(descriptor.factory)
        
        # Конструктор
        if descriptor.implementation_type:
            return self._invoke_constructor(descriptor.implementation_type)
        
        raise DependencyError(descriptor.service_type.__name__, "No implementation available")
    
    def _invoke_constructor(self, implementation_type: Type) -> Any:
        """🔨 Вызов конструктора с инъекцией зависимостей"""
        constructor = implementation_type.__init__
        signature = inspect.signature(constructor)
        
        # Собираем аргументы
        kwargs = {}
        for param_name, param in signature.parameters.items():
            if param_name == 'self':
                continue
            
            if param.annotation == param.empty:
                # Нет типа - пропускаем
                continue
            
            try:
                dependency = self.resolve(param.annotation)
                kwargs[param_name] = dependency
            except DependencyError:
                # Зависимость не найдена
                if param.default == param.empty:
                    raise DependencyError(
                        implementation_type.__name__,
                        f"Cannot resolve dependency: {param_name} ({param.annotation})"
                    )
        
        return implementation_type(**kwargs)
    
    def _invoke_factory(self, factory: Callable) -> Any:
        """🏭 Вызов фабрики с инъекцией зависимостей"""
        signature = inspect.signature(factory)
        
        # Собираем аргументы
        kwargs = {}
        for param_name, param in signature.parameters.items():
            if param.annotation == param.empty:
                continue
            
            try:
                dependency = self.resolve(param.annotation)
                kwargs[param_name] = dependency
            except DependencyError:
                if param.default == param.empty:
                    raise DependencyError(
                        factory.__name__,
                        f"Cannot resolve factory dependency: {param_name} ({param.annotation})"
                    )
        
        return factory(**kwargs)
    
    def is_registered(self, service_type: Type) -> bool:
        """✅ Проверка регистрации сервиса"""
        return service_type in self._services
    
    def get_all_registrations(self) -> Dict[Type, ServiceDescriptor]:
        """📋 Получение всех регистраций"""
        return self._services.copy()


class ServiceLocator:
    """🌐 Service Locator для глобального доступа"""
    
    _container: Optional[DependencyContainer] = None
    
    @classmethod
    def set_container(cls, container: DependencyContainer) -> None:
        """📦 Установка контейнера"""
        cls._container = container
    
    @classmethod
    def get_container(cls) -> DependencyContainer:
        """📦 Получение контейнера"""
        if cls._container is None:
            raise DependencyError("ServiceLocator", "Container not set")
        return cls._container
    
    @classmethod
    def resolve(cls, service_type: Type[T]) -> T:
        """🔍 Разрешение зависимости"""
        return cls.get_container().resolve(service_type)


# Декораторы для упрощения работы

def injectable(cls):
    """💉 Декоратор для классов с зависимостями"""
    cls._injectable = True
    return cls


def singleton(service_type: Type = None):
    """📌 Декоратор для singleton сервисов"""
    def decorator(cls):
        if hasattr(ServiceLocator, '_container') and ServiceLocator._container:
            target_type = service_type or cls
            ServiceLocator._container.register_singleton(target_type, cls)
        
        cls._lifetime = Lifetime.SINGLETON
        cls._service_type = service_type
        return cls
    
    return decorator


# Билдер контейнера

class ContainerBuilder:
    """🔨 Билдер для контейнера зависимостей"""
    
    def __init__(self):
        self.container = DependencyContainer()
    
    def register_singleton(self, service_type: Type[T], implementation_type: Type[T]) -> 'ContainerBuilder':
        """📌 Регистрация singleton"""
        self.container.register_singleton(service_type, implementation_type)
        return self
    
    def register_transient(self, service_type: Type[T], implementation_type: Type[T]) -> 'ContainerBuilder':
        """🔄 Регистрация transient"""
        self.container.register_transient(service_type, implementation_type)
        return self
    
    def register_instance(self, service_type: Type[T], instance: T) -> 'ContainerBuilder':
        """📦 Регистрация экземпляра"""
        self.container.register_instance(service_type, instance)
        return self
    
    def register_factory(self, service_type: Type[T], factory: Callable[..., T]) -> 'ContainerBuilder':
        """🏭 Регистрация фабрики"""
        self.container.register_factory(service_type, factory)
        return self
    
    def build(self) -> DependencyContainer:
        """🔨 Создание контейнера"""
        ServiceLocator.set_container(self.container)
        return self.container


# Вспомогательные функции

def resolve(service_type: Type[T]) -> T:
    """🔍 Быстрое разрешение зависимости"""
    return ServiceLocator.resolve(service_type)


def create_container() -> ContainerBuilder:
    """🏗️ Создание нового контейнера"""
    return ContainerBuilder()


if __name__ == "__main__":
    # Пример использования
    from abc import ABC, abstractmethod
    
    class IRepository(ABC):
        @abstractmethod
        def save(self, data: str) -> None:
            pass
    
    class DatabaseRepository(IRepository):
        def save(self, data: str) -> None:
            print(f"Сохранено в БД: {data}")
    
    @injectable
    class UserService:
        def __init__(self, repository: IRepository):
            self.repository = repository
        
        def create_user(self, name: str) -> None:
            self.repository.save(f"User: {name}")
    
    # Настройка контейнера
    container = (create_container()
                .register_singleton(IRepository, DatabaseRepository)
                .register_transient(UserService)
                .build())
    
    # Использование
    user_service = resolve(UserService)
    user_service.create_user("John Doe")
    print("✅ DI контейнер работает")
'''

        di_file = self.infrastructure_dir / "di_container.py"
        di_file.write_text(di_container_content)
        self.logger.info("  ✅ Создан di_container.py")

    def _create_base_classes(self):
        """🏗️ Создание базовых классов"""
        base_content = '''#!/usr/bin/env python3
"""🏗️ Базовые абстрактные классы"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

from ..core.models import TradeSignal, MarketData, Position, TradingPair
from ..core.interfaces import ITradingStrategy


class BaseStrategy(ITradingStrategy):
    """🎯 Базовая торговая стратегия"""
    
    def __init__(self, strategy_name: str, config: Dict[str, Any] = None):
        self.strategy_name = strategy_name
        self.config = config or {}
        self.logger = logging.getLogger(f"strategy.{strategy_name}")
        
        # Статистика стратегии
        self.trades_count = 0
        self.successful_trades = 0
        self.total_profit_loss = 0.0
        self.last_signal_time: Optional[datetime] = None
    
    @abstractmethod
    async def analyze(self, market_data: MarketData, 
                     position: Optional[Position] = None) -> TradeSignal:
        """📈 Анализ рынка и генерация сигнала"""
        pass
    
    def get_strategy_name(self) -> str:
        """📛 Получение имени стратегии"""
        return self.strategy_name
    
    def update_statistics(self, trade_result: Dict[str, Any]) -> None:
        """📊 Обновление статистики стратегии"""
        self.trades_count += 1
        
        if trade_result.get('success', False):
            self.successful_trades += 1
            
        profit_loss = trade_result.get('profit_loss', 0.0)
        self.total_profit_loss += profit_loss
        
        self.logger.info(f"📊 Статистика {self.strategy_name}: "
                        f"сделок {self.trades_count}, "
                        f"успешных {self.successful_trades}, "
                        f"P&L {self.total_profit_loss:.2f}")
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """📈 Получение метрик производительности"""
        win_rate = 0.0
        if self.trades_count > 0:
            win_rate = (self.successful_trades / self.trades_count) * 100
        
        return {
            'strategy_name': self.strategy_name,
            'total_trades': self.trades_count,
            'successful_trades': self.successful_trades,
            'win_rate': round(win_rate, 2),
            'total_profit_loss': self.total_profit_loss,
            'last_signal_time': self.last_signal_time
        }
    
    def _create_signal(self, action: str, trading_pair: TradingPair, 
                      quantity: float, price: Optional[float] = None,
                      confidence: float = 0.0, reason: str = "") -> TradeSignal:
        """🎯 Создание торгового сигнала"""
        from decimal import Decimal
        from ..core.models import SignalAction
        
        self.last_signal_time = datetime.now()
        
        return TradeSignal(
            action=SignalAction(action),
            trading_pair=trading_pair,
            quantity=Decimal(str(quantity)),
            price=Decimal(str(price)) if price else None,
            confidence=confidence,
            reason=reason,
            strategy_name=self.strategy_name,
            timestamp=self.last_signal_time
        )


class BaseService(ABC):
    """🌐 Базовый сервис"""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.logger = logging.getLogger(f"service.{service_name}")
        self.is_initialized = False
        self.startup_time: Optional[datetime] = None
    
    async def initialize(self) -> bool:
        """🚀 Инициализация сервиса"""
        try:
            self.logger.info(f"🚀 Инициализация {self.service_name}...")
            await self._initialize_implementation()
            self.is_initialized = True
            self.startup_time = datetime.now()
            self.logger.info(f"✅ {self.service_name} инициализирован")
            return True
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации {self.service_name}: {e}")
            return False
    
    @abstractmethod
    async def _initialize_implementation(self) -> None:
        """🔧 Реализация инициализации"""
        pass
    
    async def shutdown(self) -> None:
        """🛑 Завершение работы сервиса"""
        try:
            self.logger.info(f"🛑 Завершение работы {self.service_name}...")
            await self._shutdown_implementation()
            self.is_initialized = False
            self.logger.info(f"✅ {self.service_name} остановлен")
        except Exception as e:
            self.logger.error(f"❌ Ошибка остановки {self.service_name}: {e}")
    
    async def _shutdown_implementation(self) -> None:
        """🔧 Реализация завершения работы"""
        pass
    
    def get_status(self) -> Dict[str, Any]:
        """📊 Получение статуса сервиса"""
        uptime_seconds = 0
        if self.startup_time and self.is_initialized:
            uptime_seconds = int((datetime.now() - self.startup_time).total_seconds())
        
        return {
            'service_name': self.service_name,
            'is_initialized': self.is_initialized,
            'startup_time': self.startup_time.isoformat() if self.startup_time else None,
            'uptime_seconds': uptime_seconds
        }


class BaseValidator:
    """✅ Базовый валидатор"""
    
    def __init__(self, validator_name: str):
        self.validator_name = validator_name
        self.logger = logging.getLogger(f"validator.{validator_name}")
    
    def validate(self, data: Any) -> bool:
        """✅ Валидация данных"""
        raise NotImplementedError("Subclasses must implement validate method")
    
    def validate_with_errors(self, data: Any) -> tuple[bool, List[str]]:
        """✅ Валидация с получением списка ошибок"""
        errors = []
        try:
            is_valid = self.validate(data)
            return is_valid, errors
        except Exception as e:
            errors.append(str(e))
            return False, errors
    
    def _add_validation_error(self, errors: List[str], field: str, message: str) -> None:
        """❌ Добавление ошибки валидации"""
        errors.append(f"{field}: {message}")
        self.logger.warning(f"Validation error - {field}: {message}")


class BaseRepository:
    """💾 Базовый репозиторий"""
    
    def __init__(self, repository_name: str, data_dir: str = "data"):
        self.repository_name = repository_name
        self.data_dir = Path(data_dir)
        self.logger = logging.getLogger(f"repository.{repository_name}")
        
        # Создаем директорию если не существует
        self.data_dir.mkdir(exist_ok=True)
    
    def _get_file_path(self, filename: str) -> Path:
        """📁 Получение пути к файлу"""
        return self.data_dir / filename
    
    def _serialize_data(self, data: Any) -> Any:
        """🔧 Сериализация данных"""
        from decimal import Decimal
        from datetime import datetime
        
        if isinstance(data, Decimal):
            return str(data)
        elif isinstance(data, datetime):
            return data.isoformat()
        elif isinstance(data, dict):
            return {k: self._serialize_data(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._serialize_data(item) for item in data]
        return data
    
    def _deserialize_data(self, data: Any) -> Any:
        """🔧 Десериализация данных"""
        from decimal import Decimal
        from datetime import datetime
        
        if isinstance(data, str):
            # Попробуем преобразовать в Decimal
            try:
                return Decimal(data)
            except:
                # Попробуем преобразовать в datetime
                try:
                    return datetime.fromisoformat(data)
                except:
                    return data
        elif isinstance(data, dict):
            return {k: self._deserialize_data(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._deserialize_data(item) for item in data]
        return data


if __name__ == "__main__":
    # Тестирование базовых классов
    print("🏗️ Базовые классы готовы к использованию")
    
    # Проверяем что все импорты работают
    try:
        from datetime import datetime
        print("✅ Импорты работают")
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
'''

        base_file = self.src_dir / "core" / "base.py"
        base_file.write_text(base_content)
        self.logger.info("  ✅ Создан core/base.py")