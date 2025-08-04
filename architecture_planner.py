#!/usr/bin/env python3
"""🏗️ Архитектурное планирование для Clean Architecture - Этап 1.2"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any
from enum import Enum
from pathlib import Path
import json


class LayerType(Enum):
    """🏗️ Типы слоев архитектуры"""
    CORE = "core"
    DOMAIN = "domain"
    APPLICATION = "application"
    INFRASTRUCTURE = "infrastructure"
    PRESENTATION = "presentation"


class ComponentType(Enum):
    """📦 Типы компонентов"""
    INTERFACE = "interface"
    MODEL = "model"
    SERVICE = "service"
    REPOSITORY = "repository"
    CONTROLLER = "controller"
    ADAPTER = "adapter"
    FACTORY = "factory"
    VALIDATOR = "validator"


@dataclass
class ArchitecturalComponent:
    """🏗️ Архитектурный компонент"""
    name: str
    layer: LayerType
    component_type: ComponentType
    file_path: str
    dependencies: Set[str] = field(default_factory=set)
    interfaces: Set[str] = field(default_factory=set)
    responsibilities: List[str] = field(default_factory=list)
    size_estimate: int = 0  # строк кода
    priority: int = 1  # 1-высокий, 3-низкий
    migration_status: str = "planned"  # planned, in_progress, completed
    legacy_mapping: Optional[str] = None  # соответствие старому коду


@dataclass
class BoundedContext:
    """🗺️ Ограниченный контекст"""
    name: str
    description: str
    components: List[ArchitecturalComponent] = field(default_factory=list)
    interfaces: Set[str] = field(default_factory=set)
    events: Set[str] = field(default_factory=set)


@dataclass
class ArchitecturalPlan:
    """📋 Архитектурный план"""
    contexts: Dict[str, BoundedContext] = field(default_factory=dict)
    dependency_rules: Dict[str, List[str]] = field(default_factory=dict)
    di_configuration: Dict[str, Any] = field(default_factory=dict)
    error_handling_strategy: Dict[str, Any] = field(default_factory=dict)


class ArchitecturePlanner:
    """🏗️ Планировщик архитектуры"""
    
    def __init__(self):
        self.plan = ArchitecturalPlan()
        self._setup_dependency_rules()
        self._setup_error_handling()
    
    def create_clean_architecture_plan(self) -> ArchitecturalPlan:
        """🎯 Создание плана Clean Architecture"""
        print("🏗️ Создаем план Clean Architecture...")
        
        # 1. Определяем bounded contexts
        self._define_bounded_contexts()
        
        # 2. Планируем слои
        self._plan_core_layer()
        self._plan_domain_layer()
        self._plan_application_layer()
        self._plan_infrastructure_layer()
        self._plan_presentation_layer()
        
        # 3. Настраиваем DI
        self._configure_dependency_injection()
        
        print("✅ План архитектуры создан")
        return self.plan
    
    def _define_bounded_contexts(self) -> None:
        """🗺️ Определение ограниченных контекстов"""
        
        # Trading Context - основная торговая логика
        trading_context = BoundedContext(
            name="trading",
            description="Основная торговая логика, стратегии, управление позициями",
            interfaces={
                "ITradingService", "IPositionService", "IStrategyService"
            },
            events={
                "TradeExecuted", "PositionOpened", "PositionClosed", "StrategySignal"
            }
        )
        
        # Risk Context - управление рисками
        risk_context = BoundedContext(
            name="risk",
            description="Управление рисками, лимиты, stop-loss",
            interfaces={
                "IRiskManager", "IRiskAssessor", "ILimitChecker"
            },
            events={
                "RiskLimitExceeded", "StopLossTriggered", "EmergencyStop"
            }
        )
        
        # Market Data Context - рыночные данные
        market_context = BoundedContext(
            name="market",
            description="Получение и обработка рыночных данных",
            interfaces={
                "IMarketDataProvider", "IPriceService", "IAnalyticsService"
            },
            events={
                "PriceUpdated", "MarketDataReceived", "ConnectionLost"
            }
        )
        
        # Infrastructure Context - внешние сервисы
        infrastructure_context = BoundedContext(
            name="infrastructure",
            description="API интеграция, персистентность, уведомления",
            interfaces={
                "IExchangeAPI", "INotificationService", "ICacheService"
            },
            events={
                "APICallFailed", "NotificationSent", "DataPersisted"
            }
        )
        
        self.plan.contexts = {
            "trading": trading_context,
            "risk": risk_context,
            "market": market_context,
            "infrastructure": infrastructure_context
        }
    
    def _plan_core_layer(self) -> None:
        """🎯 Планирование Core слоя"""
        
        # Основные интерфейсы
        interfaces_component = ArchitecturalComponent(
            name="Interfaces",
            layer=LayerType.CORE,
            component_type=ComponentType.INTERFACE,
            file_path="src/core/interfaces.py",
            responsibilities=[
                "Определение всех интерфейсов системы",
                "Протоколы для типизации",
                "Абстрактные базовые классы"
            ],
            size_estimate=300,
            priority=1
        )
        
        # Модели данных
        models_component = ArchitecturalComponent(
            name="Models",
            layer=LayerType.CORE,
            component_type=ComponentType.MODEL,
            file_path="src/core/models.py",
            responsibilities=[
                "Основные модели данных",
                "Value objects",
                "Enums и константы"
            ],
            size_estimate=250,
            priority=1
        )
        
        # Исключения
        exceptions_component = ArchitecturalComponent(
            name="Exceptions",
            layer=LayerType.CORE,
            component_type=ComponentType.MODEL,
            file_path="src/core/exceptions.py",
            responsibilities=[
                "Кастомные исключения",
                "Иерархия ошибок",
                "Error handling utilities"
            ],
            size_estimate=150,
            priority=1
        )
        
        # События
        events_component = ArchitecturalComponent(
            name="Events",
            layer=LayerType.CORE,
            component_type=ComponentType.MODEL,
            file_path="src/core/events.py",
            responsibilities=[
                "Доменные события",
                "Event bus интерфейсы",
                "Event handlers"
            ],
            size_estimate=200,
            priority=2
        )
        
        # Добавляем в контексты
        for context in self.plan.contexts.values():
            context.components.extend([
                interfaces_component, models_component, 
                exceptions_component, events_component
            ])
    
    def _plan_domain_layer(self) -> None:
        """🏛️ Планирование Domain слоя"""
        
        # Trading Domain
        trading_components = [
            ArchitecturalComponent(
                name="TradingService",
                layer=LayerType.DOMAIN,
                component_type=ComponentType.SERVICE,
                file_path="src/domain/trading/trading_service.py",
                interfaces={"ITradingService"},
                responsibilities=[
                    "Координация торговых операций",
                    "Валидация торговых сигналов",
                    "Управление торговым циклом"
                ],
                size_estimate=400,
                priority=1,
                legacy_mapping="TradeOrchestrator"
            ),
            
            ArchitecturalComponent(
                name="StrategyService",
                layer=LayerType.DOMAIN,
                component_type=ComponentType.SERVICE,
                file_path="src/domain/trading/strategy_service.py",
                interfaces={"IStrategyService"},
                dependencies={"ITradingStrategy", "IMarketData"},
                responsibilities=[
                    "Управление торговыми стратегиями",
                    "Выбор активной стратегии",
                    "Анализ торговых сигналов"
                ],
                size_estimate=350,
                priority=1,
                legacy_mapping="StrategyManager"
            ),
            
            ArchitecturalComponent(
                name="PositionService",
                layer=LayerType.DOMAIN,
                component_type=ComponentType.SERVICE,
                file_path="src/domain/trading/position_service.py",
                interfaces={"IPositionService"},
                dependencies={"IPositionRepository", "ITradeValidator"},
                responsibilities=[
                    "Управление торговыми позициями",
                    "Расчет P&L",
                    "Отслеживание размера позиций"
                ],
                size_estimate=300,
                priority=1,
                legacy_mapping="PositionManager"
            )
        ]
        
        # Risk Domain
        risk_components = [
            ArchitecturalComponent(
                name="RiskManager",
                layer=LayerType.DOMAIN,
                component_type=ComponentType.SERVICE,
                file_path="src/domain/risk/risk_manager.py",
                interfaces={"IRiskManager"},
                dependencies={"IRiskAssessor", "ILimitChecker"},
                responsibilities=[
                    "Оценка торговых рисков",
                    "Применение лимитов",
                    "Блокировка опасных операций"
                ],
                size_estimate=350,
                priority=1,
                legacy_mapping="RiskManager"
            ),
            
            ArchitecturalComponent(
                name="EmergencyExitManager",
                layer=LayerType.DOMAIN,
                component_type=ComponentType.SERVICE,
                file_path="src/domain/risk/emergency_exit_manager.py",
                interfaces={"IEmergencyExitManager"},
                responsibilities=[
                    "Аварийное закрытие позиций",
                    "Защита от критических потерь",
                    "Экстренная остановка торговли"
                ],
                size_estimate=200,
                priority=2,
                legacy_mapping="EmergencyExitManager"
            )
        ]
        
        # Analytics Domain
        analytics_components = [
            ArchitecturalComponent(
                name="AnalyticsService",
                layer=LayerType.DOMAIN,
                component_type=ComponentType.SERVICE,
                file_path="src/domain/analytics/analytics_service.py",
                interfaces={"IAnalyticsService"},
                dependencies={"IMetricsCollector", "IReportGenerator"},
                responsibilities=[
                    "Сбор торговой статистики",
                    "Генерация отчетов",
                    "Анализ производительности"
                ],
                size_estimate=300,
                priority=2,
                legacy_mapping="AnalyticsSystem"
            )
        ]
        
        # Добавляем компоненты в соответствующие контексты
        self.plan.contexts["trading"].components.extend(trading_components)
        self.plan.contexts["risk"].components.extend(risk_components)
        self.plan.contexts["market"].components.extend(analytics_components)
    
    def _plan_application_layer(self) -> None:
        """⚙️ Планирование Application слоя"""
        
        # Services (координация между доменами)
        services_components = [
            ArchitecturalComponent(
                name="TradingOrchestrator",
                layer=LayerType.APPLICATION,
                component_type=ComponentType.SERVICE,
                file_path="src/application/services/trading_orchestrator.py",
                dependencies={
                    "ITradingService", "IPositionService", 
                    "IRiskManager", "IMarketDataProvider"
                },
                responsibilities=[
                    "Координация торгового цикла",
                    "Интеграция между доменами",
                    "Обработка торговых команд"
                ],
                size_estimate=400,
                priority=1,
                legacy_mapping="TradeOrchestrator"
            ),
            
            ArchitecturalComponent(
                name="MarketDataOrchestrator",
                layer=LayerType.APPLICATION,
                component_type=ComponentType.SERVICE,
                file_path="src/application/services/market_data_orchestrator.py",
                dependencies={"IMarketDataProvider", "ICacheService"},
                responsibilities=[
                    "Сбор рыночных данных",
                    "Кэширование данных",
                    "Уведомления об изменениях"
                ],
                size_estimate=250,
                priority=2
            )
        ]
        
        # Command/Query Handlers
        handlers_components = [
            ArchitecturalComponent(
                name="TradingCommandHandlers",
                layer=LayerType.APPLICATION,
                component_type=ComponentType.SERVICE,  
                file_path="src/application/handlers/trading_commands.py",
                dependencies={"ITradingService", "IValidator"},
                responsibilities=[
                    "Обработка торговых команд",
                    "Валидация команд",
                    "Координация выполнения"
                ],
                size_estimate=300,
                priority=2
            ),
            
            ArchitecturalComponent(
                name="QueryHandlers",
                layer=LayerType.APPLICATION,
                component_type=ComponentType.SERVICE,
                file_path="src/application/handlers/queries.py",
                dependencies={"IRepository", "IAnalyticsService"},
                responsibilities=[
                    "Обработка запросов данных",
                    "Агрегация информации",
                    "Формирование ответов"
                ],
                size_estimate=200,
                priority=3
            )
        ]
        
        # Добавляем в контексты
        all_app_components = services_components + handlers_components
        for context in self.plan.contexts.values():
            context.components.extend(all_app_components)
    
    def _plan_infrastructure_layer(self) -> None:
        """🔧 Планирование Infrastructure слоя"""
        
        # API Integration
        api_components = [
            ArchitecturalComponent(
                name="ExmoApiAdapter",
                layer=LayerType.INFRASTRUCTURE,
                component_type=ComponentType.ADAPTER,
                file_path="src/infrastructure/api/exmo_adapter.py",
                interfaces={"IExchangeAPI"},
                dependencies={"IRateLimiter", "IHttpClient"},
                responsibilities=[
                    "Интеграция с EXMO API",
                    "Адаптация API ответов",
                    "Обработка API ошибок"
                ],
                size_estimate=400,
                priority=1,
                legacy_mapping="ExmoAPIClient"
            ),
            
            ArchitecturalComponent(
                name="RateLimiter",
                layer=LayerType.INFRASTRUCTURE,
                component_type=ComponentType.SERVICE,
                file_path="src/infrastructure/api/rate_limiter.py",
                interfaces={"IRateLimiter"},
                responsibilities=[
                    "Ограничение частоты запросов",
                    "Адаптивные задержки",
                    "Статистика использования API"
                ],
                size_estimate=250,
                priority=1,
                legacy_mapping="RateLimiter"
            )
        ]
        
        # Persistence
        persistence_components = [
            ArchitecturalComponent(
                name="PositionRepository",
                layer=LayerType.INFRASTRUCTURE,
                component_type=ComponentType.REPOSITORY,
                file_path="src/infrastructure/persistence/position_repository.py",
                interfaces={"IPositionRepository"},
                dependencies={"IFileStorage", "ISerializer"},
                responsibilities=[
                    "Сохранение позиций",
                    "Загрузка истории позиций",
                    "Резервное копирование"
                ],
                size_estimate=200,
                priority=2
            ),
            
            ArchitecturalComponent(
                name="TradeHistoryRepository", 
                layer=LayerType.INFRASTRUCTURE,
                component_type=ComponentType.REPOSITORY,
                file_path="src/infrastructure/persistence/trade_history_repository.py",
                interfaces={"ITradeHistoryRepository"},
                responsibilities=[
                    "Сохранение истории торгов",
                    "Поиск и фильтрация сделок",
                    "Экспорт данных"
                ],
                size_estimate=180,
                priority=3
            )
        ]
        
        # Monitoring
        monitoring_components = [
            ArchitecturalComponent(
                name="LoggingService",
                layer=LayerType.INFRASTRUCTURE,
                component_type=ComponentType.SERVICE,
                file_path="src/infrastructure/monitoring/logging_service.py",
                interfaces={"ILogger"},
                responsibilities=[
                    "Структурированное логирование",
                    "Ротация логов",
                    "Фильтрация по уровням"
                ],
                size_estimate=150,
                priority=2
            ),
            
            ArchitecturalComponent(
                name="MetricsCollector",
                layer=LayerType.INFRASTRUCTURE,
                component_type=ComponentType.SERVICE,
                file_path="src/infrastructure/monitoring/metrics_collector.py",
                interfaces={"IMetricsCollector"},
                responsibilities=[
                    "Сбор метрик производительности",
                    "Агрегация статистики",
                    "Экспорт метрик"
                ],
                size_estimate=200,
                priority=3
            )
        ]
        
        # Добавляем в infrastructure контекст
        all_infra_components = api_components + persistence_components + monitoring_components
        self.plan.contexts["infrastructure"].components.extend(all_infra_components)
    
    def _plan_presentation_layer(self) -> None:
        """🎨 Планирование Presentation слоя"""
        
        # CLI Interface
        cli_components = [
            ArchitecturalComponent(
                name="CLIController",
                layer=LayerType.PRESENTATION,
                component_type=ComponentType.CONTROLLER,
                file_path="src/presentation/cli/cli_controller.py",
                dependencies={"ITradingOrchestrator", "IConfigProvider"},
                responsibilities=[
                    "Обработка CLI команд",
                    "Валидация входных параметров",
                    "Форматирование вывода"
                ],
                size_estimate=250,
                priority=2,
                legacy_mapping="main.py"
            ),
            
            ArchitecturalComponent(
                name="StatusDisplay",
                layer=LayerType.PRESENTATION,
                component_type=ComponentType.SERVICE,
                file_path="src/presentation/cli/status_display.py",
                dependencies={"IAnalyticsService", "IPositionService"},
                responsibilities=[
                    "Отображение статуса бота",
                    "Реал-тайм мониторинг",
                    "Форматирование данных"  
                ],
                size_estimate=180,
                priority=3
            )
        ]
        
        # Future: Web API (подготовка)
        web_components = [
            ArchitecturalComponent(
                name="WebApiController",
                layer=LayerType.PRESENTATION,
                component_type=ComponentType.CONTROLLER,
                file_path="src/presentation/web/api_controller.py",
                dependencies={"ITradingOrchestrator", "IAuthService"},
                responsibilities=[
                    "REST API endpoints",
                    "Аутентификация",
                    "JSON сериализация"
                ],
                size_estimate=300,
                priority=3,
                migration_status="future"
            )
        ]
        
        # Добавляем в общие компоненты
        all_presentation_components = cli_components + web_components
        for context in self.plan.contexts.values():
            context.components.extend(all_presentation_components)
    
    def _setup_dependency_rules(self) -> None:
        """🔗 Настройка правил зависимостей"""
        self.plan.dependency_rules = {
            # Core слой - ни от кого не зависит
            "core": [],
            
            # Domain слой - зависит только от Core
            "domain": ["core"],
            
            # Application слой - от Domain и Core
            "application": ["domain", "core"],
            
            # Infrastructure слой - от Application, Domain и Core
            "infrastructure": ["application", "domain", "core"],
            
            # Presentation слой - от всех
            "presentation": ["infrastructure", "application", "domain", "core"]
        }
    
    def _setup_error_handling(self) -> None:
        """🚨 Настройка стратегии обработки ошибок"""
        self.plan.error_handling_strategy = {
            "global_exception_handler": {
                "file": "src/core/error_handler.py",
                "responsibilities": [
                    "Централизованная обработка ошибок",
                    "Логирование исключений",
                    "Уведомления о критических ошибках"
                ]
            },
            "domain_errors": {
                "trading_errors": "src/domain/trading/exceptions.py",
                "risk_errors": "src/domain/risk/exceptions.py",
                "market_errors": "src/domain/market/exceptions.py"
            },
            "infrastructure_errors": {
                "api_errors": "src/infrastructure/api/exceptions.py",
                "persistence_errors": "src/infrastructure/persistence/exceptions.py"
            },
            "error_recovery": {
                "retry_policies": "Exponential backoff для API",
                "circuit_breaker": "При множественных ошибках API",
                "fallback_strategies": "Переключение на backup источники"
            }
        }
    
    def _configure_dependency_injection(self) -> None:
        """💉 Настройка Dependency Injection"""
        self.plan.di_configuration = {
            "container_location": "src/core/di_container.py",
            "registration_strategy": "Decorator-based auto-registration",
            "lifetimes": {
                "singleton": [
                    "IExchangeAPI", "IConfigProvider", "ILogger",
                    "IRateLimiter", "ICacheService"
                ],
                "scoped": [
                    "ITradingService", "IRiskManager", "IPositionService"
                ],
                "transient": [
                    "IValidator", "IMapper", "IEventHandler"
                ]
            },
            "configuration_files": {
                "development": "src/config/di_dev.json",
                "production": "src/config/di_prod.json",
                "testing": "src/config/di_test.json"
            },
            "bootstrap_sequence": [
                "1. Load configuration",
                "2. Register infrastructure services",
                "3. Register domain services", 
                "4. Register application services",
                "5. Register presentation controllers",
                "6. Validate dependencies",
                "7. Start services"
            ]
        }
    
    def generate_migration_timeline(self) -> Dict[str, Any]:
        """📅 Генерация временной шкалы миграции"""
        
        # Группируем компоненты по приоритетам
        high_priority = []
        medium_priority = []
        low_priority = []
        
        for context in self.plan.contexts.values():
            for component in context.components:
                if component.priority == 1:
                    high_priority.append(component)
                elif component.priority == 2:
                    medium_priority.append(component)
                else:
                    low_priority.append(component)
        
        # Убираем дубликаты
        all_components = []
        seen = set()
        for comp_list in [high_priority, medium_priority, low_priority]:
            for comp in comp_list:
                if comp.name not in seen:
                    all_components.append(comp)
                    seen.add(comp.name)
        
        return {
            "phase_1_core": {
                "duration_days": 2,
                "components": [c.name for c in all_components if c.layer == LayerType.CORE],
                "deliverables": [
                    "Все интерфейсы определены",
                    "Базовые модели созданы",
                    "Система исключений готова"
                ]
            },
            "phase_2_domain": {
                "duration_days": 3,
                "components": [c.name for c in all_components if c.layer == LayerType.DOMAIN],
                "deliverables": [
                    "Доменные сервисы реализованы",
                    "Бизнес-логика портирована",
                    "Unit тесты написаны"
                ]
            },
            "phase_3_application": {
                "duration_days": 2,
                "components": [c.name for c in all_components if c.layer == LayerType.APPLICATION],
                "deliverables": [
                    "Оркестраторы созданы",
                    "Command/Query handlers готовы",
                    "Integration тесты написаны"
                ]
            },
            "phase_4_infrastructure": {
                "duration_days": 3,
                "components": [c.name for c in all_components if c.layer == LayerType.INFRASTRUCTURE],
                "deliverables": [
                    "API адаптеры портированы",
                    "Персистентность настроена", 
                    "Мониторинг добавлен"
                ]
            },
            "phase_5_presentation": {
                "duration_days": 1,
                "components": [c.name for c in all_components if c.layer == LayerType.PRESENTATION],
                "deliverables": [
                    "CLI обновлен",
                    "Интеграция завершена",
                    "E2E тесты пройдены"
                ]
            },
            "total_estimate": {
                "days": 11,
                "total_components": len(all_components),
                "total_lines_estimate": sum(c.size_estimate for c in all_components)
            }
        }
    
    def save_plan(self, output_file: str = "architecture_plan.json") -> None:
        """💾 Сохранение архитектурного плана"""
        
        # Конвертируем в сериализуемый формат
        plan_data = {
            "contexts": {},
            "dependency_rules": self.plan.dependency_rules,
            "di_configuration": self.plan.di_configuration,
            "error_handling_strategy": self.plan.error_handling_strategy,
            "migration_timeline": self.generate_migration_timeline()
        }
        
        # Конвертируем контексты
        for name, context in self.plan.contexts.items():
            components_data = []
            seen_components = set()
            
            for component in context.components:
                if component.name in seen_components:
                    continue
                seen_components.add(component.name)
                
                components_data.append({
                    "name": component.name,
                    "layer": component.layer.value,
                    "component_type": component.component_type.value,
                    "file_path": component.file_path,
                    "dependencies": list(component.dependencies),
                    "interfaces": list(component.interfaces),
                    "responsibilities": component.responsibilities,
                    "size_estimate": component.size_estimate,
                    "priority": component.priority,
                    "migration_status": component.migration_status,
                    "legacy_mapping": component.legacy_mapping
                })
            
            plan_data["contexts"][name] = {
                "name": context.name,
                "description": context.description,
                "components": components_data,
                "interfaces": list(context.interfaces),
                "events": list(context.events)
            }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(plan_data, f, indent=2, ensure_ascii=False)
        
        print(f"📄 Архитектурный план сохранен в {output_file}")


def main():
    """🚀 Главная функция"""
    planner = ArchitecturePlanner()
    plan = planner.create_clean_architecture_plan()
    
    # Печатаем краткий отчет
    print("\n" + "="*60)
    print("🏗️ АРХИТЕКТУРНЫЙ ПЛАН")
    print("="*60)
    
    # Статистика по контекстам
    print(f"📋 Bounded Contexts: {len(plan.contexts)}")
    for name, context in plan.contexts.items():
        unique_components = len(set(c.name for c in context.components))
        print(f"  🗂️ {name}: {unique_components} компонентов")
    
    # Статистика по слоям
    all_components = []
    seen = set()
    for context in plan.contexts.values():
        for comp in context.components:
            if comp.name not in seen:
                all_components.append(comp)
                seen.add(comp.name)
    
    layer_stats = {}
    for comp in all_components:
        layer = comp.layer.value
        if layer not in layer_stats:
            layer_stats[layer] = 0
        layer_stats[layer] += 1
    
    print(f"\n📊 Компоненты по слоям:")
    for layer, count in layer_stats.items():
        print(f"  🏗️ {layer}: {count} компонентов")
    
    # Временная шкала
    timeline = planner.generate_migration_timeline()
    print(f"\n📅 Временная шкала:")
    print(f"  ⏱️ Общее время: {timeline['total_estimate']['days']} дней")
    print(f"  📦 Всего компонентов: {timeline['total_estimate']['total_components']}")
    print(f"  📏 Оценка строк кода: {timeline['total_estimate']['total_lines_estimate']}")
    
    # Приоритеты
    priority_stats = {}
    for comp in all_components:
        priority = f"Приоритет {comp.priority}"
        if priority not in priority_stats:
            priority_stats[priority] = 0
        priority_stats[priority] += 1
    
    print(f"\n🎯 Приоритеты:")
    for priority, count in priority_stats.items():
        print(f"  {priority}: {count} компонентов")
    
    # Сохраняем план
    planner.save_plan()
    
    print(f"\n💡 Следующие шаги:")
    print(f"  1. Изучите architecture_plan.json")
    print(f"  2. Создайте структуру директорий")
    print(f"  3. Начните с Core слоя (Этап 2)")
    
    return plan


if __name__ == "__main__":
    main()