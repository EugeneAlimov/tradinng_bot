#!/usr/bin/env python3
"""💉 Dependency Injection контейнер - Core слой"""

from typing import Dict, Any, Type, Optional, List, Callable, TypeVar, get_type_hints, Union
from dataclasses import dataclass, field
from enum import Enum
import inspect
import threading
from abc import ABC, abstractmethod
import uuid
import time

# Импортируем исключения из нашего модуля
try:
    from .exceptions import (
        TradingSystemError, ValidationError, ConfigurationError
    )

    class ServiceNotRegisteredError(TradingSystemError):
        """🔍 Сервис не зарегистрирован"""
        pass

    class CircularDependencyError(TradingSystemError):
        """♻️ Циклическая зависимость"""
        pass

    class ServiceCreationError(TradingSystemError):
        """🏭 Ошибка создания сервиса"""
        pass

    class DependencyInjectionError(TradingSystemError):
        """💉 Ошибка DI системы"""
        pass

except ImportError:
    # Fallback для случая если exceptions.py еще не готов
    class ServiceNotRegisteredError(Exception): pass
    class CircularDependencyError(Exception): pass
    class ServiceCreationError(Exception): pass
    class DependencyInjectionError(Exception): pass

T = TypeVar('T')


# ================= LIFETIME ENUMS =================

class ServiceLifetime(Enum):
    """🔄 Время жизни сервиса"""
    SINGLETON = "singleton"    # Один экземпляр на контейнер
    TRANSIENT = "transient"    # Новый экземпляр каждый раз
    SCOPED = "scoped"         # Один экземпляр на scope


# ================= SERVICE DESCRIPTORS =================

@dataclass
class ServiceDescriptor:
    """📋 Дескриптор регистрации сервиса"""
    service_type: Type
    implementation_type: Optional[Type] = None
    instance: Optional[Any] = None
    factory: Optional[Callable] = None
    lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT
    dependencies: List[Type] = field(default_factory=list)
    is_generic: bool = False

    @property
    def service_name(self) -> str:
        """Имя сервиса"""
        return getattr(self.service_type, '__name__', str(self.service_type))

    @property
    def implementation_name(self) -> str:
        """Имя реализации"""
        if self.implementation_type:
            return getattr(self.implementation_type, '__name__', str(self.implementation_type))
        elif self.factory:
            return getattr(self.factory, '__name__', 'factory')
        elif self.instance:
            return type(self.instance).__name__
        return "unknown"

    @property
    def is_instance_registration(self) -> bool:
        """Проверка регистрации экземпляра"""
        return self.instance is not None

    @property
    def is_factory_registration(self) -> bool:
        """Проверка регистрации фабрики"""
        return self.factory is not None

    @property
    def is_type_registration(self) -> bool:
        """Проверка регистрации типа"""
        return self.implementation_type is not None


@dataclass
class ServiceScope:
    """🎯 Область видимости сервисов"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    instances: Dict[Type, Any] = field(default_factory=dict)
    parent: Optional['ServiceScope'] = None
    created_at: float = field(default_factory=time.time)

    def get_instance(self, service_type: Type) -> Optional[Any]:
        """Получение экземпляра из scope"""
        if service_type in self.instances:
            return self.instances[service_type]

        # Ищем в родительском scope
        if self.parent:
            return self.parent.get_instance(service_type)

        return None

    def set_instance(self, service_type: Type, instance: Any) -> None:
        """Установка экземпляра в scope"""
        self.instances[service_type] = instance

    def dispose(self) -> None:
        """Освобождение ресурсов scope"""
        for instance in self.instances.values():
            if hasattr(instance, 'dispose'):
                try:
                    instance.dispose()
                except Exception as e:
                    import logging
                    logging.warning(f"Error disposing instance {type(instance)}: {e}")

        self.instances.clear()


# ================= DEPENDENCY CONTAINER =================

class DependencyContainer:
    """💉 Контейнер зависимостей"""

    def __init__(self):
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._singletons: Dict[Type, Any] = {}
        self._creation_stack: List[Type] = []
        self._lock = threading.RLock()
        self._current_scope: Optional[ServiceScope] = None
        self._disposed = False

        # Регистрируем сам контейнер
        self.register_instance(DependencyContainer, self)

    # ================= РЕГИСТРАЦИЯ СЕРВИСОВ =================

    def register_singleton(self, service_type: Type, implementation_type: Type) -> 'DependencyContainer':
        """📌 Регистрация singleton сервиса"""
        return self._register_service(
            service_type, implementation_type, ServiceLifetime.SINGLETON
        )

    def register_transient(self, service_type: Type, implementation_type: Type) -> 'DependencyContainer':
        """🔄 Регистрация transient сервиса"""
        return self._register_service(
            service_type, implementation_type, ServiceLifetime.TRANSIENT
        )

    def register_scoped(self, service_type: Type, implementation_type: Type) -> 'DependencyContainer':
        """🎯 Регистрация scoped сервиса"""
        return self._register_service(
            service_type, implementation_type, ServiceLifetime.SCOPED
        )

    def register_instance(self, service_type: Type, instance: Any) -> 'DependencyContainer':
        """📦 Регистрация экземпляра"""
        self._check_not_disposed()

        with self._lock:
            descriptor = ServiceDescriptor(
                service_type=service_type,
                instance=instance,
                lifetime=ServiceLifetime.SINGLETON
            )

            self._services[service_type] = descriptor
            self._singletons[service_type] = instance

        return self

    def register_factory(
        self,
        service_type: Type,
        factory: Callable[[], T],
        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT
    ) -> 'DependencyContainer':
        """🏭 Регистрация фабрики"""
        self._check_not_disposed()

        with self._lock:
            descriptor = ServiceDescriptor(
                service_type=service_type,
                factory=factory,
                lifetime=lifetime
            )

            self._services[service_type] = descriptor

        return self

    def _register_service(
        self,
        service_type: Type,
        implementation_type: Type,
        lifetime: ServiceLifetime
    ) -> 'DependencyContainer':
        """🔧 Внутренняя регистрация сервиса"""
        self._check_not_disposed()

        with self._lock:
            # Анализируем зависимости
            dependencies = self._analyze_dependencies(implementation_type)

            descriptor = ServiceDescriptor(
                service_type=service_type,
                implementation_type=implementation_type,
                lifetime=lifetime,
                dependencies=dependencies
            )

            self._services[service_type] = descriptor

        return self

    # ================= РАЗРЕШЕНИЕ ЗАВИСИМОСТЕЙ =================

    def resolve(self, service_type: Type[T]) -> T:
        """🔍 Разрешение зависимости"""
        self._check_not_disposed()

        with self._lock:
            try:
                return self._resolve_internal(service_type)
            except Exception as e:
                raise ServiceCreationError(
                    f"Failed to resolve service {service_type.__name__}",
                    error_code=f"SERVICE_CREATION_FAILED_{service_type.__name__}",
                    context={
                        'service_type': service_type.__name__,
                        'creation_error': str(e)
                    }
                ) from e

    def try_resolve(self, service_type: Type[T]) -> Optional[T]:
        """🔍 Попытка разрешения зависимости без исключения"""
        try:
            return self.resolve(service_type)
        except (ServiceNotRegisteredError, ServiceCreationError):
            return None

    def _resolve_internal(self, service_type: Type[T]) -> T:
        """🔧 Внутреннее разрешение зависимости"""

        # Проверяем регистрацию
        if service_type not in self._services:
            raise ServiceNotRegisteredError(
                f"Service {service_type.__name__} is not registered",
                context={'service_type': service_type.__name__}
            )

        descriptor = self._services[service_type]

        # Проверяем циклические зависимости
        if service_type in self._creation_stack:
            stack_info = ' -> '.join([t.__name__ for t in self._creation_stack] + [service_type.__name__])
            raise CircularDependencyError(
                f"Circular dependency detected: {stack_info}",
                context={'dependency_chain': stack_info}
            )

        # Обрабатываем различные типы регистрации
        if descriptor.is_instance_registration:
            return descriptor.instance

        # Singleton - проверяем кэш
        if descriptor.lifetime == ServiceLifetime.SINGLETON:
            if service_type in self._singletons:
                return self._singletons[service_type]

        # Scoped - проверяем текущий scope
        if descriptor.lifetime == ServiceLifetime.SCOPED:
            if self._current_scope:
                instance = self._current_scope.get_instance(service_type)
                if instance is not None:
                    return instance

        # Создаем новый экземпляр
        try:
            self._creation_stack.append(service_type)
            instance = self._create_instance(descriptor)

            # Кэшируем в зависимости от lifetime
            if descriptor.lifetime == ServiceLifetime.SINGLETON:
                self._singletons[service_type] = instance
            elif descriptor.lifetime == ServiceLifetime.SCOPED and self._current_scope:
                self._current_scope.set_instance(service_type, instance)

            return instance

        finally:
            self._creation_stack.pop()

    def _create_instance(self, descriptor: ServiceDescriptor) -> Any:
        """🏭 Создание экземпляра сервиса"""

        if descriptor.is_factory_registration:
            # Используем фабрику
            return descriptor.factory()

        if not descriptor.implementation_type:
            raise ServiceCreationError(
                f"No implementation type specified for {descriptor.service_name}"
            )

        # Разрешаем зависимости
        dependencies = []
        for dep_type in descriptor.dependencies:
            dep_instance = self._resolve_internal(dep_type)
            dependencies.append(dep_instance)

        # Создаем экземпляр
        try:
            return descriptor.implementation_type(*dependencies)
        except Exception as e:
            raise ServiceCreationError(
                f"Failed to create instance of {descriptor.implementation_name}",
                context={
                    'implementation_type': descriptor.implementation_name,
                    'dependencies_count': len(dependencies),
                    'creation_error': str(e)
                }
            ) from e

    def _analyze_dependencies(self, implementation_type: Type) -> List[Type]:
        """🔍 Анализ зависимостей конструктора"""
        try:
            # Получаем сигнатуру конструктора
            init_signature = inspect.signature(implementation_type.__init__)

            dependencies = []
            for param_name, param in init_signature.parameters.items():
                # Пропускаем self
                if param_name == 'self':
                    continue

                # Если есть аннотация типа
                if param.annotation != inspect.Parameter.empty:
                    dependencies.append(param.annotation)
                else:
                    # Пытаемся получить из type hints
                    try:
                        type_hints = get_type_hints(implementation_type.__init__)
                        if param_name in type_hints:
                            dependencies.append(type_hints[param_name])
                    except (NameError, AttributeError):
                        pass

            return dependencies

        except Exception:
            # Если не можем проанализировать - возвращаем пустой список
            return []

    # ================= SCOPE MANAGEMENT =================

    def create_scope(self) -> 'DependencyContainer':
        """🎯 Создание нового scope"""
        self._check_not_disposed()

        scoped_container = DependencyContainer()

        # Копируем все регистрации
        with self._lock:
            scoped_container._services = self._services.copy()
            scoped_container._singletons = self._singletons.copy()

        # Создаем новый scope
        scope = ServiceScope(parent=self._current_scope)
        scoped_container._current_scope = scope

        return scoped_container

    # ================= УПРАВЛЕНИЕ И ВАЛИДАЦИЯ =================

    def is_registered(self, service_type: Type) -> bool:
        """✅ Проверка регистрации сервиса"""
        return service_type in self._services

    def get_registration(self, service_type: Type) -> Optional[ServiceDescriptor]:
        """📋 Получение дескриптора регистрации"""
        return self._services.get(service_type)

    def get_all_registrations(self) -> Dict[Type, ServiceDescriptor]:
        """📋 Получение всех регистраций"""
        return self._services.copy()

    def validate_registrations(self) -> List[str]:
        """✅ Валидация всех регистраций"""
        errors = []

        for service_type, descriptor in self._services.items():
            try:
                self._validate_descriptor(descriptor)
            except Exception as e:
                errors.append(f"{descriptor.service_name}: {e}")

        return errors

    def _validate_descriptor(self, descriptor: ServiceDescriptor) -> None:
        """✅ Валидация дескриптора"""

        if descriptor.is_instance_registration:
            # Экземпляр должен соответствовать типу сервиса
            if not isinstance(descriptor.instance, descriptor.service_type):
                if not hasattr(descriptor.service_type, '__origin__'):  # Не generic
                    raise ValidationError(
                        f"Instance type mismatch for {descriptor.service_name}"
                    )

        elif descriptor.is_factory_registration:
            # Фабрика должна быть callable
            if not callable(descriptor.factory):
                raise ValidationError(
                    f"Factory for {descriptor.service_name} is not callable"
                )

        elif descriptor.is_type_registration:
            # Проверяем что implementation_type может быть создан
            if not inspect.isclass(descriptor.implementation_type):
                raise ValidationError(
                    f"Implementation type for {descriptor.service_name} is not a class"
                )

            # Проверяем зависимости
            for dep_type in descriptor.dependencies:
                if not self.is_registered(dep_type):
                    raise ValidationError(
                        f"Dependency {dep_type.__name__} for {descriptor.service_name} is not registered"
                    )

    def get_statistics(self) -> Dict[str, Any]:
        """📊 Получение статистики контейнера"""
        return {
            'total_services': len(self._services),
            'singletons_cached': len(self._singletons),
            'has_active_scope': self._current_scope is not None,
            'is_disposed': self._disposed,
            'services_by_lifetime': {
                lifetime.value: sum(
                    1 for desc in self._services.values()
                    if desc.lifetime == lifetime
                ) for lifetime in ServiceLifetime
            }
        }

    def dispose(self) -> None:
        """🗑️ Освобождение ресурсов контейнера"""
        if self._disposed:
            return

        with self._lock:
            # Освобождаем singleton экземпляры
            for instance in self._singletons.values():
                if hasattr(instance, 'dispose'):
                    try:
                        instance.dispose()
                    except Exception as e:
                        import logging
                        logging.warning(f"Error disposing singleton {type(instance)}: {e}")

            # Освобождаем текущий scope
            if self._current_scope:
                self._current_scope.dispose()

            # Очищаем все коллекции
            self._services.clear()
            self._singletons.clear()
            self._creation_stack.clear()
            self._current_scope = None
            self._disposed = True

    def _check_not_disposed(self) -> None:
        """✅ Проверка что контейнер не освобожден"""
        if self._disposed:
            raise DependencyInjectionError("Container has been disposed")


# ================= ДЕКОРАТОРЫ ДЛЯ АВТОМАТИЧЕСКОЙ РЕГИСТРАЦИИ =================

def injectable(lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT):
    """💉 Декоратор для автоматической регистрации"""
    def decorator(cls):
        # Добавляем метаданные для автоматической регистрации
        cls._di_lifetime = lifetime
        cls._di_injectable = True
        return cls
    return decorator


def singleton(cls):
    """📌 Декоратор для singleton сервиса"""
    return injectable(ServiceLifetime.SINGLETON)(cls)


def transient(cls):
    """🔄 Декоратор для transient сервиса"""
    return injectable(ServiceLifetime.TRANSIENT)(cls)


def scoped(cls):
    """🎯 Декоратор для scoped сервиса"""
    return injectable(ServiceLifetime.SCOPED)(cls)


# ================= SERVICE LOCATOR =================

class ServiceLocator:
    """🔍 Service Locator для legacy кода"""

    _container: Optional[DependencyContainer] = None
    _lock = threading.Lock()

    @classmethod
    def set_container(cls, container: DependencyContainer) -> None:
        """📦 Установка контейнера"""
        with cls._lock:
            cls._container = container

    @classmethod
    def get_service(cls, service_type: Type[T]) -> T:
        """🔍 Получение сервиса"""
        with cls._lock:
            if not cls._container:
                raise DependencyInjectionError("Container not set in ServiceLocator")

            return cls._container.resolve(service_type)

    @classmethod
    def try_get_service(cls, service_type: Type[T]) -> Optional[T]:
        """🔍 Попытка получения сервиса"""
        with cls._lock:
            if not cls._container:
                return None

            return cls._container.try_resolve(service_type)

    @classmethod
    def is_service_registered(cls, service_type: Type) -> bool:
        """✅ Проверка регистрации сервиса"""
        with cls._lock:
            if not cls._container:
                return False

            return cls._container.is_registered(service_type)

    @classmethod
    def clear(cls) -> None:
        """🧹 Очистка Service Locator"""
        with cls._lock:
            cls._container = None


# ================= BUILDER ДЛЯ НАСТРОЙКИ КОНТЕЙНЕРА =================

class ContainerBuilder:
    """🏗️ Строитель контейнера зависимостей"""

    def __init__(self):
        self._container = DependencyContainer()
        self._auto_registration_enabled = False
        self._validation_enabled = True

    def enable_auto_registration(self) -> 'ContainerBuilder':
        """🤖 Включение автоматической регистрации"""
        self._auto_registration_enabled = True
        return self

    def disable_validation(self) -> 'ContainerBuilder':
        """🚫 Отключение валидации (для тестов)"""
        self._validation_enabled = False
        return self

    def register_singleton(self, service_type: Type, implementation_type: Type) -> 'ContainerBuilder':
        """📌 Регистрация singleton"""
        self._container.register_singleton(service_type, implementation_type)
        return self

    def register_transient(self, service_type: Type, implementation_type: Type) -> 'ContainerBuilder':
        """🔄 Регистрация transient"""
        self._container.register_transient(service_type, implementation_type)
        return self

    def register_scoped(self, service_type: Type, implementation_type: Type) -> 'ContainerBuilder':
        """🎯 Регистрация scoped"""
        self._container.register_scoped(service_type, implementation_type)
        return self

    def register_instance(self, service_type: Type, instance: Any) -> 'ContainerBuilder':
        """📦 Регистрация экземпляра"""
        self._container.register_instance(service_type, instance)
        return self

    def register_factory(
        self,
        service_type: Type,
        factory: Callable,
        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT
    ) -> 'ContainerBuilder':
        """🏭 Регистрация фабрики"""
        self._container.register_factory(service_type, factory, lifetime)
        return self

    def build(self) -> DependencyContainer:
        """🏗️ Построение контейнера"""
        # Валидируем регистрации если включено
        if self._validation_enabled:
            validation_errors = self._container.validate_registrations()
            if validation_errors:
                error_list = '\n'.join(validation_errors)
                raise DependencyInjectionError(
                    f"Container validation failed:\n{error_list}"
                )

        return self._container


# ================= КОНТЕКСТНЫЙ МЕНЕДЖЕР ДЛЯ SCOPE =================

class DependencyScope:
    """🎯 Контекстный менеджер для dependency scope"""

    def __init__(self, parent_container: DependencyContainer):
        self.parent_container = parent_container
        self.scoped_container: Optional[DependencyContainer] = None
        self.original_container: Optional[DependencyContainer] = None

    def __enter__(self) -> DependencyContainer:
        # Сохраняем оригинальный контейнер
        self.original_container = ServiceLocator._container

        # Создаем scoped контейнер
        self.scoped_container = self.parent_container.create_scope()

        # Устанавливаем scoped контейнер как текущий
        ServiceLocator.set_container(self.scoped_container)

        return self.scoped_container

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Освобождаем ресурсы scope
        if self.scoped_container:
            self.scoped_container.dispose()

        # Восстанавливаем оригинальный контейнер
        if self.original_container:
            ServiceLocator.set_container(self.original_container)


# ================= УТИЛИТЫ =================

def auto_register_services(container: DependencyContainer, *modules) -> None:
    """🤖 Автоматическая регистрация сервисов из модулей"""
    for module in modules:
        for name in dir(module):
            obj = getattr(module, name)

            # Проверяем что это класс с метаданными DI
            if (inspect.isclass(obj) and
                hasattr(obj, '_di_injectable') and
                obj._di_injectable):

                lifetime = getattr(obj, '_di_lifetime', ServiceLifetime.TRANSIENT)

                # Регистрируем сервис как самого себя
                if lifetime == ServiceLifetime.SINGLETON:
                    container.register_singleton(obj, obj)
                elif lifetime == ServiceLifetime.SCOPED:
                    container.register_scoped(obj, obj)
                else:
                    container.register_transient(obj, obj)
