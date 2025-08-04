#!/usr/bin/env python3
"""💉 Dependency Injection контейнер - Core слой"""

from typing import Dict, Any, Type, Optional, List, Callable, TypeVar, get_type_hints, Union
from dataclasses import dataclass, field
from enum import Enum
import inspect
import threading
from abc import ABC, abstractmethod
import uuid

# Импортируем исключения из нашего модуля
try:
    from .exceptions import (
        ServiceNotRegisteredError, CircularDependencyError, 
        ServiceCreationError, DependencyInjectionError
    )
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
    id: str
    instances: Dict[Type, Any] = field(default_factory=dict)
    parent: Optional['ServiceScope'] = None
    created_at: float = field(default_factory=lambda: __import__('time').time())
    
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
    
    def register_factory(self, service_type: Type, factory: Callable[[], T], 
                        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT) -> 'DependencyContainer':
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
    
    def _register_service(self, service_type: Type, implementation_type: Type, 
                         lifetime: ServiceLifetime) -> 'DependencyContainer':
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
                    service_type=service_type.__name__,
                    creation_error=str(e)
                ) from e
    
    def try_resolve(self, service_type: Type[T]) -> Optional[T]:
        """🔍 Попытка разрешения зависимости без исключения"""
        try:
            return self.resolve(service_type)
        except (ServiceNotRegisteredError, ServiceCreationError):
            return None
    
    def resolve_all(self, service_type: Type[T]) -> List[T]:
        """📋 Разрешение всех реализаций интерфейса"""
        instance = self.try_resolve(service_type)
        return [instance] if instance else []
    
    def _resolve_internal(self, service_type: Type) -> Any:
        """🔧 Внутреннее разрешение зависимости"""
        # Проверяем циклические зависимости
        if service_type in self._creation_stack:
            chain = self._creation_stack + [service_type]
            chain_names = [t.__name__ for t in chain]
            raise CircularDependencyError(
                f"Circular dependency detected: {' -> '.join(chain_names)}",
                dependency_chain=chain_names
            )
        
        # Проверяем регистрацию
        if service_type not in self._services:
            raise ServiceNotRegisteredError(
                f"Service {service_type.__name__} is not registered",
                service_type=service_type.__name__
            )
        
        descriptor = self._services[service_type]
        
        # Singleton - проверяем кэш
        if descriptor.lifetime == ServiceLifetime.SINGLETON:
            if service_type in self._singletons:
                return self._singletons[service_type]
        
        # Scoped - проверяем текущий scope
        elif descriptor.lifetime == ServiceLifetime.SCOPED:
            if self._current_scope:
                scoped_instance = self._current_scope.get_instance(service_type)
                if scoped_instance:
                    return scoped_instance
        
        # Создаем экземпляр
        self._creation_stack.append(service_type)
        try:
            instance = self._create_instance(descriptor)
            
            # Кэшируем если нужно
            if descriptor.lifetime == ServiceLifetime.SINGLETON:
                self._singletons[service_type] = instance
            elif descriptor.lifetime == ServiceLifetime.SCOPED and self._current_scope:
                self._current_scope.set_instance(service_type, instance)
            
            return instance
        
        finally:
            self._creation_stack.pop()
    
    def _create_instance(self, descriptor: ServiceDescriptor) -> Any:
        """🏭 Создание экземпляра сервиса"""
        # Уже созданный экземпляр
        if descriptor.instance is not None:
            return descriptor.instance
        
        # Фабрика
        if descriptor.factory is not None:
            return self._call_factory(descriptor.factory)
        
        # Конструктор класса
        if descriptor.implementation_type is not None:
            return self._create_from_constructor(descriptor.implementation_type)
        
        raise ServiceCreationError(
            f"No way to create instance for {descriptor.service_name}",
            service_type=descriptor.service_name,
            creation_error="No implementation, factory, or instance"
        )
    
    def _create_from_constructor(self, implementation_type: Type) -> Any:
        """🔧 Создание экземпляра через конструктор"""
        constructor = implementation_type.__init__
        signature = inspect.signature(constructor)
        
        # Собираем аргументы
        args = []
        kwargs = {}
        
        for param_name, param in signature.parameters.items():
            if param_name == 'self':
                continue
            
            # Определяем тип параметра
            param_type = param.annotation
            if param_type == inspect.Parameter.empty:
                # Пытаемся получить из type hints
                try:
                    type_hints = get_type_hints(implementation_type.__init__)
                    param_type = type_hints.get(param_name)
                except Exception:
                    param_type = None
            
            if param_type and param_type != inspect.Parameter.empty:
                # Разрешаем зависимость
                dependency = self._resolve_internal(param_type)
                
                if param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                    kwargs[param_name] = dependency
                else:
                    args.append(dependency)
            
            elif param.default != inspect.Parameter.empty:
                # Параметр с значением по умолчанию - пропускаем
                continue
            else:
                # Обязательный параметр без типа - ошибка
                raise ServiceCreationError(
                    f"Cannot resolve parameter '{param_name}' for {implementation_type.__name__}",
                    service_type=implementation_type.__name__,
                    creation_error=f"Parameter '{param_name}' has no type annotation"
                )
        
        # Создаем экземпляр
        return implementation_type(*args, **kwargs)
    
    def _call_factory(self, factory: Callable) -> Any:
        """🏭 Вызов фабрики"""
        signature = inspect.signature(factory)
        
        # Если фабрика принимает контейнер как параметр
        if len(signature.parameters) == 1:
            param = next(iter(signature.parameters.values()))
            if param.annotation == DependencyContainer:
                return factory(self)
        
        # Фабрика без параметров
        return factory()
    
    def _analyze_dependencies(self, implementation_type: Type) -> List[Type]:
        """🔍 Анализ зависимостей типа"""
        dependencies = []
        
        try:
            constructor = implementation_type.__init__
            type_hints = get_type_hints(constructor)
            
            for param_name, param_type in type_hints.items():
                if param_name not in ['self', 'return']:
                    dependencies.append(param_type)
        
        except Exception:
            # Если не удалось проанализировать - возвращаем пустой список
            pass
        
        return dependencies
    
    # ================= SCOPE MANAGEMENT =================
    
    def create_scope(self, scope_id: str = None) -> ServiceScope:
        """🎯 Создание нового scope"""
        scope_id = scope_id or str(uuid.uuid4())
        return ServiceScope(id=scope_id, parent=self._current_scope)
    
    def enter_scope(self, scope: ServiceScope) -> None:
        """⬇️ Вход в scope"""
        scope.parent = self._current_scope
        self._current_scope = scope
    
    def exit_scope(self) -> None:
        """⬆️ Выход из scope"""
        if self._current_scope:
            self._current_scope = self._current_scope.parent
    
    # ================= ИНФОРМАЦИЯ О СЕРВИСАХ =================
    
    def is_registered(self, service_type: Type) -> bool:
        """✅ Проверка регистрации сервиса"""
        return service_type in self._services
    
    def get_service_info(self, service_type: Type) -> Optional[Dict[str, Any]]:
        """📊 Получение информации о сервисе"""
        if service_type not in self._services:
            return None
        
        descriptor = self._services[service_type]
        return {
            'service_type': descriptor.service_name,
            'implementation_type': descriptor.implementation_name,
            'lifetime': descriptor.lifetime.value,
            'dependencies': [dep.__name__ for dep in descriptor.dependencies],
            'is_singleton_created': service_type in self._singletons,
            'has_instance': descriptor.instance is not None,
            'has_factory': descriptor.factory is not None,
            'registration_type': self._get_registration_type(descriptor)
        }
    
    def _get_registration_type(self, descriptor: ServiceDescriptor) -> str:
        """🔍 Определение типа регистрации"""
        if descriptor.is_instance_registration:
            return "instance"
        elif descriptor.is_factory_registration:
            return "factory"
        elif descriptor.is_type_registration:
            return "type"
        else:
            return "unknown"
    
    def get_all_registrations(self) -> List[Dict[str, Any]]:
        """📋 Получение всех регистраций"""
        registrations = []
        
        for service_type, descriptor in self._services.items():
            info = self.get_service_info(service_type)
            if info:
                registrations.append(info)
        
        return registrations
    
    def validate_registrations(self) -> List[str]:
        """✅ Валидация всех регистраций"""
        errors = []
        
        for service_type, descriptor in self._services.items():
            try:
                self._validate_service_descriptor(descriptor)
            except Exception as e:
                errors.append(f"{descriptor.service_name}: {str(e)}")
        
        return errors
    
    def _validate_service_descriptor(self, descriptor: ServiceDescriptor) -> None:
        """✅ Валидация дескриптора сервиса"""
        # Проверяем наличие способа создания
        if (not descriptor.implementation_type and 
            not descriptor.factory and 
            descriptor.instance is None):
            raise DependencyInjectionError(
                f"Service {descriptor.service_name} has no implementation, factory, or instance"
            )
        
        # Проверяем совместимость типов
        if descriptor.implementation_type:
            if not self._is_compatible_type(descriptor.service_type, descriptor.implementation_type):
                raise DependencyInjectionError(
                    f"Implementation {descriptor.implementation_name} is not compatible with service {descriptor.service_name}"
                )
    
    def _is_compatible_type(self, service_type: Type, implementation_type: Type) -> bool:
        """🔍 Проверка совместимости типов"""
        # Проверяем наследование
        try:
            return issubclass(implementation_type, service_type)
        except TypeError:
            # Для Protocol типов или других случаев
            return True  # Упрощенная проверка
    
    # ================= УПРАВЛЕНИЕ ЖИЗНЕННЫМ ЦИКЛОМ =================
    
    def dispose(self) -> None:
        """🗑️ Освобождение ресурсов контейнера"""
        if self._disposed:
            return
        
        with self._lock:
            # Освобождаем singleton instances
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
    
    def register_factory(self, service_type: Type, factory: Callable, 
                        lifetime: ServiceLifetime = ServiceLifetime.TRANSIENT) -> 'ContainerBuilder':
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

class ScopeContext:
    """🎯 Контекстный менеджер для управления scope"""
    
    def __init__(self, container: DependencyContainer, scope_id: str = None):
        self.container = container
        self.scope = container.create_scope(scope_id)
        self.previous_scope = None
    
    def __enter__(self) -> ServiceScope:
        self.previous_scope = self.container._current_scope
        self.container.enter_scope(self.scope)
        return self.scope
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Освобождаем ресурсы scope
        self.scope.dispose()
        
        # Восстанавливаем предыдущий scope
        self.container.exit_scope()


# ================= ФАБРИЧНЫЕ МЕТОДЫ =================

def create_container() -> DependencyContainer:
    """🏭 Создание базового контейнера"""
    return DependencyContainer()


def create_configured_container() -> DependencyContainer:
    """🏭 Создание настроенного контейнера"""
    builder = ContainerBuilder()
    
    # Базовые регистрации для торговой системы
    # Регистрируем основные типы
    builder.register_instance(str, "")  # Базовый тип
    builder.register_instance(int, 0)   # Базовый тип
    builder.register_instance(float, 0.0)  # Базовый тип
    
    return builder.build()


# ================= ГЛОБАЛЬНЫЙ КОНТЕЙНЕР =================

_global_container: Optional[DependencyContainer] = None
_global_container_lock = threading.Lock()


def get_global_container() -> DependencyContainer:
    """🌍 Получение глобального контейнера"""
    global _global_container
    
    if _global_container is None:
        with _global_container_lock:
            if _global_container is None:  # Double-check locking
                _global_container = create_configured_container()
    
    return _global_container


def set_global_container(container: DependencyContainer) -> None:
    """🌍 Установка глобального контейнера"""
    global _global_container
    
    with _global_container_lock:
        # Освобождаем старый контейнер если есть
        if _global_container is not None:
            try:
                _global_container.dispose()
            except Exception:
                pass
        
        _global_container = container
        ServiceLocator.set_container(container)


def resolve_service(service_type: Type[T]) -> T:
    """🔍 Разрешение сервиса через глобальный контейнер"""
    return get_global_container().resolve(service_type)


def try_resolve_service(service_type: Type[T]) -> Optional[T]:
    """🔍 Попытка разрешения сервиса через глобальный контейнер"""
    return get_global_container().try_resolve(service_type)