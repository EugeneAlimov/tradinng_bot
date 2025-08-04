#!/usr/bin/env python3
"""📦 Dependency Injection Container для торговой системы"""

from typing import Dict, Any, TypeVar, Type, Callable, Optional, Union
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from .exceptions import DependencyError, ConfigurationError

T = TypeVar('T')


class Lifetime(Enum):
    """🔄 Жизненный цикл зависимостей"""
    SINGLETON = "singleton"     # Один экземпляр на весь контейнер
    TRANSIENT = "transient"     # Новый экземпляр каждый раз
    SCOPED = "scoped"          # Один экземпляр на scope


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
        """🏭 Является ли фабрикой"""
        return self.factory is not None
    
    @property
    def is_instance(self) -> bool:
        """📦 Является ли готовым экземпляром"""
        return self.instance is not None


class IDependencyContainer(ABC):
    """🏗️ Интерфейс контейнера зависимостей"""
    
    @abstractmethod
    def register_singleton(self, service_type: Type[T], implementation_type: Type[T]) -> None:
        """📌 Регистрация singleton сервиса"""
        pass
    
    @abstractmethod
    def register_transient(self, service_type: Type[T], implementation_type: Type[T]) -> None:
        """🔄 Регистрация transient сервиса"""
        pass
    
    @abstractmethod
    def register_instance(self, service_type: Type[T], instance: T) -> None:
        """📦 Регистрация готового экземпляра"""
        pass
    
    @abstractmethod
    def register_factory(self, service_type: Type[T], factory: Callable[..., T]) -> None:
        """🏭 Регистрация фабрики"""
        pass
    
    @abstractmethod
    def resolve(self, service_type: Type[T]) -> T:
        """🔍 Разрешение зависимости"""
        pass
    
    @abstractmethod
    def is_registered(self, service_type: Type) -> bool:
        """✅ Проверка регистрации сервиса"""
        pass


class DependencyContainer(IDependencyContainer):
    """📦 Простой контейнер зависимостей"""
    
    def __init__(self):
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._instances: Dict[Type, Any] = {}  # Кэш singleton экземпляров
        self._building: set = set()  # Защита от циклических зависимостей
    
    def register_singleton(self, service_type: Type[T], implementation_type: Type[T] = None) -> 'DependencyContainer':
        """📌 Регистрация singleton сервиса"""
        impl_type = implementation_type or service_type
        self._services[service_type] = ServiceDescriptor(
            service_type=service_type,
            implementation_type=impl_type,
            lifetime=Lifetime.SINGLETON
        )
        return self
    
    def register_transient(self, service_type: Type[T], implementation_type: Type[T] = None) -> 'DependencyContainer':
        """🔄 Регистрация transient сервиса"""
        impl_type = implementation_type or service_type
        self._services[service_type] = ServiceDescriptor(
            service_type=service_type,
            implementation_type=impl_type,
            lifetime=Lifetime.TRANSIENT
        )
        return self
    
    def register_instance(self, service_type: Type[T], instance: T) -> 'DependencyContainer':
        """📦 Регистрация готового экземпляра"""
        self._services[service_type] = ServiceDescriptor(
            service_type=service_type,
            instance=instance,
            lifetime=Lifetime.SINGLETON
        )
        # Сразу кэшируем экземпляр
        self._instances[service_type] = instance
        return self
    
    def register_factory(self, service_type: Type[T], factory: Callable[..., T], lifetime: Lifetime = Lifetime.TRANSIENT) -> 'DependencyContainer':
        """🏭 Регистрация фабрики"""
        self._services[service_type] = ServiceDescriptor(
            service_type=service_type,
            factory=factory,
            lifetime=lifetime
        )
        return self
    
    def resolve(self, service_type: Type[T]) -> T:
        """🔍 Разрешение зависимости"""
        
        # Проверяем циклические зависимости
        if service_type in self._building:
            dependency_chain = " -> ".join([str(t) for t in self._building])
            raise DependencyError(
                service_type.__name__, 
                f"Циклическая зависимость: {dependency_chain} -> {service_type.__name__}"
            )
        
        # Проверяем регистрацию
        if not self.is_registered(service_type):
            raise DependencyError(
                service_type.__name__, 
                f"Сервис не зарегистрирован: {service_type.__name__}"
            )
        
        descriptor = self._services[service_type]
        
        # Singleton - проверяем кэш
        if descriptor.lifetime == Lifetime.SINGLETON:
            if service_type in self._instances:
                return self._instances[service_type]
        
        # Добавляем в список строящихся
        self._building.add(service_type)
        
        try:
            # Создаем экземпляр
            instance = self._create_instance(descriptor)
            
            # Кэшируем для singleton
            if descriptor.lifetime == Lifetime.SINGLETON:
                self._instances[service_type] = instance
            
            return instance
            
        finally:
            # Убираем из списка строящихся
            self._building.discard(service_type)
    
    def _create_instance(self, descriptor: ServiceDescriptor) -> Any:
        """🏗️ Создание экземпляра сервиса"""
        
        # Готовый экземпляр
        if descriptor.is_instance:
            return descriptor.instance
        
        # Фабрика
        if descriptor.is_factory:
            return self._call_factory(descriptor.factory)
        
        # Конструктор класса
        if descriptor.implementation_type:
            return self._create_from_constructor(descriptor.implementation_type)
        
        raise DependencyError(
            descriptor.service_type.__name__,
            "Не удалось создать экземпляр - нет реализации, фабрики или экземпляра"
        )
    
    def _create_from_constructor(self, implementation_type: Type) -> Any:
        """🔨 Создание экземпляра через конструктор"""
        
        # Анализируем конструктор
        constructor = implementation_type.__init__
        signature = inspect.signature(constructor)
        
        # Собираем аргументы для конструктора
        args = {}
        for param_name, param in signature.parameters.items():
            if param_name == 'self':
                continue
            
            # Пропускаем параметры без аннотации типа
            if param.annotation == inspect.Parameter.empty:
                if param.default == inspect.Parameter.empty:
                    raise DependencyError(
                        implementation_type.__name__,
                        f"Параметр '{param_name}' не имеет аннотации типа и значения по умолчанию"
                    )
                continue
            
            # Разрешаем зависимость
            try:
                args[param_name] = self.resolve(param.annotation)
            except DependencyError:
                # Если зависимость не найдена, проверяем значение по умолчанию
                if param.default != inspect.Parameter.empty:
                    args[param_name] = param.default
                else:
                    raise
        
        # Создаем экземпляр
        return implementation_type(**args)
    
    def _call_factory(self, factory: Callable) -> Any:
        """🏭 Вызов фабрики"""
        
        signature = inspect.signature(factory)
        
        # Собираем аргументы для фабрики
        args = {}
        for param_name, param in signature.parameters.items():
            
            # Пропускаем параметры без аннотации типа
            if param.annotation == inspect.Parameter.empty:
                if param.default == inspect.Parameter.empty:
                    continue
                else:
                    args[param_name] = param.default
                    continue
            
            # Разрешаем зависимость
            try:
                args[param_name] = self.resolve(param.annotation)
            except DependencyError:
                # Если зависимость не найдена, проверяем значение по умолчанию
                if param.default != inspect.Parameter.empty:
                    args[param_name] = param.default
                else:
                    raise
        
        # Вызываем фабрику
        return factory(**args)
    
    def is_registered(self, service_type: Type) -> bool:
        """✅ Проверка регистрации сервиса"""
        return service_type in self._services
    
    def get_registration_info(self, service_type: Type) -> Optional[ServiceDescriptor]:
        """📋 Информация о регистрации сервиса"""
        return self._services.get(service_type)
    
    def get_all_registrations(self) -> Dict[Type, ServiceDescriptor]:
        """📋 Все регистрации"""
        return self._services.copy()
    
    def clear(self) -> None:
        """🧹 Очистка контейнера"""
        self._services.clear()
        self._instances.clear()
        self._building.clear()
    
    def remove_registration(self, service_type: Type) -> None:
        """🗑️ Удаление регистрации"""
        if service_type in self._services:
            del self._services[service_type]
        
        if service_type in self._instances:
            del self._instances[service_type]
    
    def create_scope(self) -> 'ScopedContainer':
        """🎯 Создание scoped контейнера"""
        return ScopedContainer(self)


class ScopedContainer(IDependencyContainer):
    """🎯 Scoped контейнер зависимостей"""
    
    def __init__(self, parent: DependencyContainer):
        self.parent = parent
        self._scoped_instances: Dict[Type, Any] = {}
    
    def register_singleton(self, service_type: Type[T], implementation_type: Type[T] = None) -> 'ScopedContainer':
        """📌 Регистрация в родительском контейнере"""
        self.parent.register_singleton(service_type, implementation_type)
        return self
    
    def register_transient(self, service_type: Type[T], implementation_type: Type[T] = None) -> 'ScopedContainer':
        """🔄 Регистрация в родительском контейнере"""
        self.parent.register_transient(service_type, implementation_type)
        return self
    
    def register_instance(self, service_type: Type[T], instance: T) -> 'ScopedContainer':
        """📦 Регистрация в scoped области"""
        self._scoped_instances[service_type] = instance
        return self
    
    def register_factory(self, service_type: Type[T], factory: Callable[..., T]) -> 'ScopedContainer':
        """🏭 Регистрация в родительском контейнере"""
        self.parent.register_factory(service_type, factory)
        return self
    
    def resolve(self, service_type: Type[T]) -> T:
        """🔍 Разрешение с учетом scope"""
        
        # Проверяем scoped экземпляры
        if service_type in self._scoped_instances:
            return self._scoped_instances[service_type]
        
        # Проверяем родительский контейнер
        if self.parent.is_registered(service_type):
            descriptor = self.parent.get_registration_info(service_type)
            
            # Для scoped сервисов создаем экземпляр в scope
            if descriptor.lifetime == Lifetime.SCOPED:
                instance = self.parent._create_instance(descriptor)
                self._scoped_instances[service_type] = instance
                return instance
        
        # Делегируем родительскому контейнеру
        return self.parent.resolve(service_type)
    
    def is_registered(self, service_type: Type) -> bool:
        """✅ Проверка регистрации"""
        return (
            service_type in self._scoped_instances or 
            self.parent.is_registered(service_type)
        )
    
    def dispose(self) -> None:
        """🗑️ Освобождение ресурсов scope"""
        # Вызываем dispose для экземпляров, которые его поддерживают
        for instance in self._scoped_instances.values():
            if hasattr(instance, 'dispose'):
                try:
                    instance.dispose()
                except Exception as e:
                    # Логируем ошибку, но не прерываем процесс
                    print(f"⚠️ Ошибка при dispose {type(instance)}: {e}")
        
        self._scoped_instances.clear()


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
            raise DependencyError("ServiceLocator", "Контейнер не установлен")
        return cls._container
    
    @classmethod
    def resolve(cls, service_type: Type[T]) -> T:
        """🔍 Разрешение зависимости"""
        return cls.get_container().resolve(service_type)
    
    @classmethod
    def is_registered(cls, service_type: Type) -> bool:
        """✅ Проверка регистрации"""
        if cls._container is None:
            return False
        return cls._container.is_registered(service_type)


# Декораторы для упрощения работы с DI

def injectable(cls):
    """💉 Декоратор для классов с зависимостями"""
    # Добавляем метаданные о том, что класс поддерживает DI
    cls._injectable = True
    return cls


def singleton(service_type: Type = None):
    """📌 Декоратор для singleton сервисов"""
    def decorator(cls):
        # Автоматическая регистрация в контейнере при наличии
        if hasattr(ServiceLocator, '_container') and ServiceLocator._container:
            target_type = service_type or cls
            ServiceLocator._container.register_singleton(target_type, cls)
        
        cls._lifetime = Lifetime.SINGLETON
        cls._service_type = service_type
        return cls
    
    return decorator


def transient(service_type: Type = None):
    """🔄 Декоратор для transient сервисов"""
    def decorator(cls):
        if hasattr(ServiceLocator, '_container') and ServiceLocator._container:
            target_type = service_type or cls
            ServiceLocator._container.register_transient(target_type, cls)
        
        cls._lifetime = Lifetime.TRANSIENT
        cls._service_type = service_type
        return cls
    
    return decorator


def factory(service_type: Type, lifetime: Lifetime = Lifetime.TRANSIENT):
    """🏭 Декоратор для фабричных функций"""
    def decorator(func):
        if hasattr(ServiceLocator, '_container') and ServiceLocator._container:
            ServiceLocator._container.register_factory(service_type, func, lifetime)
        
        func._factory_for = service_type
        func._lifetime = lifetime
        return func
    
    return decorator


# Утилиты для автоматической регистрации

class ContainerBuilder:
    """🏗️ Построитель контейнера"""
    
    def __init__(self):
        self.container = DependencyContainer()
    
    def register_singleton(self, service_type: Type[T], implementation_type: Type[T] = None) -> 'ContainerBuilder':
        """📌 Регистрация singleton"""
        self.container.register_singleton(service_type, implementation_type)
        return self
    
    def register_transient(self, service_type: Type[T], implementation_type: Type[T] = None) -> 'ContainerBuilder':
        """🔄 Регистрация transient"""
        self.container.register_transient(service_type, implementation_type)
        return self
    
    def register_instance(self, service_type: Type[T], instance: T) -> 'ContainerBuilder':
        """📦 Регистрация экземпляра"""
        self.container.register_instance(service_type, instance)
        return self
    
    def register_factory(self, service_type: Type[T], factory: Callable[..., T], lifetime: Lifetime = Lifetime.TRANSIENT) -> 'ContainerBuilder':
        """🏭 Регистрация фабрики"""
        self.container.register_factory(service_type, factory, lifetime)
        return self
    
    def auto_register_module(self, module) -> 'ContainerBuilder':
        """🤖 Автоматическая регистрация модуля"""
        import inspect
        
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj):
                # Проверяем декораторы
                if hasattr(obj, '_lifetime'):
                    service_type = getattr(obj, '_service_type', obj)
                    
                    if obj._lifetime == Lifetime.SINGLETON:
                        self.container.register_singleton(service_type, obj)
                    elif obj._lifetime == Lifetime.TRANSIENT:
                        self.container.register_transient(service_type, obj)
            
            elif inspect.isfunction(obj):
                # Проверяем фабричные функции
                if hasattr(obj, '_factory_for'):
                    service_type = obj._factory_for
                    lifetime = getattr(obj, '_lifetime', Lifetime.TRANSIENT)
                    self.container.register_factory(service_type, obj, lifetime)
        
        return self
    
    def build(self) -> DependencyContainer:
        """🔨 Создание контейнера"""
        # Устанавливаем в ServiceLocator
        ServiceLocator.set_container(self.container)
        return self.container


# Контекстный менеджер для scope

class DependencyScope:
    """🎯 Контекстный менеджер для dependency scope"""
    
    def __init__(self, parent_container: DependencyContainer):
        self.parent_container = parent_container
        self.scoped_container: Optional[ScopedContainer] = None
        self.original_container: Optional[DependencyContainer] = None
    
    def __enter__(self) -> ScopedContainer:
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


# Валидатор конфигурации DI

class DependencyValidator:
    """✅ Валидатор зависимостей"""
    
    def __init__(self, container: DependencyContainer):
        self.container = container
    
    def validate_all(self) -> None:
        """✅ Валидация всех зависимостей"""
        errors = []
        
        for service_type, descriptor in self.container.get_all_registrations().items():
            try:
                self._validate_service(service_type, descriptor)
            except Exception as e:
                errors.append(f"{service_type.__name__}: {e}")
        
        if errors:
            raise DependencyError("Validation", f"Ошибки валидации зависимостей: {'; '.join(errors)}")
    
    def _validate_service(self, service_type: Type, descriptor: ServiceDescriptor) -> None:
        """✅ Валидация отдельного сервиса"""
        
        # Проверяем готовый экземпляр
        if descriptor.is_instance:
            if not isinstance(descriptor.instance, service_type):
                raise DependencyError(
                    service_type.__name__,
                    f"Экземпляр не является типом {service_type.__name__}"
                )
            return
        
        # Проверяем фабрику
        if descriptor.is_factory:
            self._validate_factory(service_type, descriptor.factory)
            return
        
        # Проверяем реализацию
        if descriptor.implementation_type:
            self._validate_implementation(service_type, descriptor.implementation_type)
            return
        
        raise DependencyError(
            service_type.__name__,
            "Нет реализации, фабрики или экземпляра"
        )
    
    def _validate_implementation(self, service_type: Type, implementation_type: Type) -> None:
        """✅ Валидация реализации"""
        
        # Проверяем наследование/соответствие
        if not issubclass(implementation_type, service_type):
            # Для протоколов проверяем соответствие интерфейса
            if hasattr(service_type, '__protocol__'):
                # Это Protocol - проверяем наличие методов
                self._validate_protocol_implementation(service_type, implementation_type)
            else:
                raise DependencyError(
                    service_type.__name__,
                    f"Тип {implementation_type.__name__} не наследует {service_type.__name__}"
                )
        
        # Проверяем конструктор
        self._validate_constructor(implementation_type)
    
    def _validate_protocol_implementation(self, protocol_type: Type, implementation_type: Type) -> None:
        """✅ Валидация реализации протокола"""
        import inspect
        
        protocol_methods = [
            name for name, method in inspect.getmembers(protocol_type, inspect.isfunction)
            if not name.startswith('_')
        ]
        
        implementation_methods = [
            name for name, method in inspect.getmembers(implementation_type, inspect.ismethod)
            if not name.startswith('_')
        ]
        
        missing_methods = set(protocol_methods) - set(implementation_methods)
        if missing_methods:
            raise DependencyError(
                protocol_type.__name__,
                f"Реализация {implementation_type.__name__} не содержит методы: {', '.join(missing_methods)}"
            )
    
    def _validate_constructor(self, implementation_type: Type) -> None:
        """✅ Валидация конструктора"""
        import inspect
        
        try:
            constructor = implementation_type.__init__
            signature = inspect.signature(constructor)
            
            for param_name, param in signature.parameters.items():
                if param_name == 'self':
                    continue
                
                # Параметры без аннотации должны иметь значение по умолчанию
                if param.annotation == inspect.Parameter.empty:
                    if param.default == inspect.Parameter.empty:
                        raise DependencyError(
                            implementation_type.__name__,
                            f"Параметр '{param_name}' не имеет аннотации типа и значения по умолчанию"
                        )
                else:
                    # Проверяем регистрацию зависимости
                    if not self.container.is_registered(param.annotation):
                        if param.default == inspect.Parameter.empty:
                            raise DependencyError(
                                implementation_type.__name__,
                                f"Зависимость '{param.annotation.__name__}' для параметра '{param_name}' не зарегистрирована"
                            )
        
        except TypeError as e:
            raise DependencyError(
                implementation_type.__name__,
                f"Ошибка анализа конструктора: {e}"
            )
    
    def _validate_factory(self, service_type: Type, factory: Callable) -> None:
        """✅ Валидация фабрики"""
        import inspect
        
        try:
            signature = inspect.signature(factory)
            
            # Проверяем возвращаемый тип
            if signature.return_annotation != inspect.Parameter.empty:
                if not issubclass(signature.return_annotation, service_type):
                    raise DependencyError(
                        service_type.__name__,
                        f"Фабрика возвращает {signature.return_annotation.__name__}, ожидается {service_type.__name__}"
                    )
            
            # Проверяем параметры фабрики
            for param_name, param in signature.parameters.items():
                if param.annotation != inspect.Parameter.empty:
                    if not self.container.is_registered(param.annotation):
                        if param.default == inspect.Parameter.empty:
                            raise DependencyError(
                                service_type.__name__,
                                f"Зависимость '{param.annotation.__name__}' для фабрики не зарегистрирована"
                            )
        
        except TypeError as e:
            raise DependencyError(
                service_type.__name__,
                f"Ошибка анализа фабрики: {e}"
            )


# Удобные функции

def resolve(service_type: Type[T]) -> T:
    """🔍 Быстрое разрешение зависимости"""
    return ServiceLocator.resolve(service_type)


def create_container() -> ContainerBuilder:
    """🏗️ Создание нового контейнера"""
    return ContainerBuilder()


def scope(container: DependencyContainer = None) -> DependencyScope:
    """🎯 Создание scope"""
    target_container = container or ServiceLocator.get_container()
    return DependencyScope(target_container)


if __name__ == "__main__":
    # Пример использования
    print("📦 Тестирование Dependency Injection Container")
    
    # Определяем интерфейсы и реализации
    from abc import ABC, abstractmethod
    
    class IRepository(ABC):
        @abstractmethod
        def save(self, data: str) -> None:
            pass
    
    class DatabaseRepository(IRepository):
        def __init__(self, connection_string: str = "default"):
            self.connection_string = connection_string
        
        def save(self, data: str) -> None:
            print(f"Сохранено в БД ({self.connection_string}): {data}")
    
    @injectable
    class UserService:
        def __init__(self, repository: IRepository):
            self.repository = repository
        
        def create_user(self, name: str) -> None:
            self.repository.save(f"User: {name}")
    
    # Настраиваем контейнер
    container = (create_container()
                .register_singleton(IRepository, DatabaseRepository)
                .register_transient(UserService)
                .build())
    
    # Валидируем
    validator = DependencyValidator(container)
    try:
        validator.validate_all()
        print("✅ Валидация DI контейнера успешна")
    except DependencyError as e:
        print(f"❌ Ошибка валидации: {e}")
    
    # Используем
    try:
        user_service = resolve(UserService)
        user_service.create_user("John Doe")
        print("✅ Разрешение зависимостей работает")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    # Тестируем scope
    print("\n🎯 Тестирование scoped контейнера:")
    with scope() as scoped_container:
        scoped_service = scoped_container.resolve(UserService)
        scoped_service.create_user("Jane Doe")
        print("✅ Scoped контейнер работает")