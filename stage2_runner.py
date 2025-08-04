#!/usr/bin/env python3
"""🏗️ Запускатель этапа 2: Создание ядра новой архитектуры"""

import sys
import os
import time
from pathlib import Path
from typing import Dict, Any, List
import json
import shutil


class Stage2Runner:
    """🏗️ Координатор выполнения этапа 2"""
    
    def __init__(self):
        self.root_path = Path(".")
        self.src_path = Path("src")
        self.results = {}
        self.start_time = time.time()
        
        print("🏗️ ЭТАП 2: СОЗДАНИЕ ЯДРА НОВОЙ АРХИТЕКТУРЫ")
        print("=" * 60)
        print("📋 Задачи этапа:")
        print("  2.1 📁 Создание структуры Core слоя")
        print("  2.2 🎯 Проверка интерфейсов (interfaces.py)")
        print("  2.3 🏗️ Проверка моделей (models.py)")
        print("  2.4 🚨 Проверка исключений (exceptions.py)")
        print("  2.5 📡 Проверка событий (events.py)")
        print("  2.6 💉 Проверка DI контейнера (di_container.py)")
        print("  2.7 ⚙️ Проверка конфигурации (config/settings.py)")
        print("  2.8 🧪 Валидация и тестирование")
        print("=" * 60)
    
    def run_complete_stage2(self) -> bool:
        """🎯 Выполнение полного этапа 2"""
        
        success = True
        
        try:
            # 2.1 Создание структуры
            print("\n📁 Шаг 2.1: Создание структуры Core слоя...")
            structure_result = self._create_core_structure()
            success = success and structure_result
            
            # 2.2 Проверка интерфейсов
            print("\n🎯 Шаг 2.2: Проверка интерфейсов...")
            interfaces_result = self._check_interfaces()
            success = success and interfaces_result
            
            # 2.3 Проверка моделей
            print("\n🏗️ Шаг 2.3: Проверка моделей...")
            models_result = self._check_models()
            success = success and models_result
            
            # 2.4 Проверка исключений
            print("\n🚨 Шаг 2.4: Проверка исключений...")
            exceptions_result = self._check_exceptions()
            success = success and exceptions_result
            
            # 2.5 Проверка событий
            print("\n📡 Шаг 2.5: Проверка событий...")
            events_result = self._check_events()
            success = success and events_result
            
            # 2.6 Проверка DI
            print("\n💉 Шаг 2.6: Проверка DI контейнера...")
            di_result = self._check_di_container()
            success = success and di_result
            
            # 2.7 Проверка конфигурации
            print("\n⚙️ Шаг 2.7: Проверка конфигурации...")
            config_result = self._check_config()
            success = success and config_result
            
            # 2.8 Валидация и тестирование
            print("\n🧪 Шаг 2.8: Валидация и тестирование...")
            validation_result = self._run_validation_tests()
            
            # Генерируем итоговый отчет
            self._generate_stage2_summary()
            
            overall_success = all([
                structure_result, interfaces_result, models_result,
                exceptions_result, events_result, di_result,
                config_result, validation_result
            ])
            
            self._print_final_results(overall_success)
            
            return overall_success
            
        except Exception as e:
            print(f"❌ Критическая ошибка этапа 2: {e}")
            self.results['critical_error'] = {'success': False, 'error': str(e)}
            return False
    
    def _create_core_structure(self) -> bool:
        """📁 Создание структуры директорий Core слоя"""
        try:
            # Создаем основные директории
            core_dirs = [
                "src",
                "src/core", 
                "src/config",
                "src/domain",
                "src/application", 
                "src/infrastructure",
                "src/presentation"
            ]
            
            created_dirs = []
            for dir_path in core_dirs:
                full_path = self.root_path / dir_path
                if not full_path.exists():
                    full_path.mkdir(parents=True, exist_ok=True)
                    created_dirs.append(dir_path)
            
            # Создаем __init__.py файлы
            init_files = [
                "src/__init__.py",
                "src/core/__init__.py",
                "src/config/__init__.py",
                "src/domain/__init__.py",
                "src/application/__init__.py",
                "src/infrastructure/__init__.py",
                "src/presentation/__init__.py"
            ]
            
            created_inits = []
            for init_file in init_files:
                init_path = self.root_path / init_file
                if not init_path.exists():
                    init_path.write_text('"""📦 Модуль торговой системы"""\n')
                    created_inits.append(init_file)
            
            self.results['structure'] = {
                'success': True,
                'created_directories': created_dirs,
                'created_init_files': created_inits,
                'total_dirs': len(core_dirs),
                'total_inits': len(init_files)
            }
            
            print(f"✅ Структура создана:")
            print(f"   📁 Директорий: {len(core_dirs)}")
            print(f"   📄 __init__.py файлов: {len(init_files)}")
            if created_dirs:
                print(f"   🆕 Новых директорий: {len(created_dirs)}")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка создания структуры: {e}")
            self.results['structure'] = {'success': False, 'error': str(e)}
            return False
    
    def _check_interfaces(self) -> bool:
        """🎯 Проверка файла интерфейсов"""
        try:
            interfaces_file = self.src_path / "core" / "interfaces.py"
            
            if not interfaces_file.exists():
                print("❌ Файл interfaces.py не найден")
                return False
            
            # Проверяем синтаксис
            try:
                with open(interfaces_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                compile(content, str(interfaces_file), 'exec')
                
                # Ищем ключевые интерфейсы
                required_interfaces = [
                    'IExchangeAPI', 'ITradingStrategy', 'IRiskManager',
                    'IPositionManager', 'ITradeExecutor', 'IMarketDataProvider'
                ]
                
                found_interfaces = [iface for iface in required_interfaces if iface in content]
                
                self.results['interfaces'] = {
                    'success': True,
                    'file_size': len(content),
                    'found_interfaces': found_interfaces,
                    'total_required': len(required_interfaces),
                    'coverage_percent': (len(found_interfaces) / len(required_interfaces)) * 100
                }
                
                print(f"✅ Интерфейсы проверены:")
                print(f"   📄 Размер файла: {len(content)} символов")
                print(f"   🎯 Найдено интерфейсов: {len(found_interfaces)}/{len(required_interfaces)}")
                
                return len(found_interfaces) >= len(required_interfaces) // 2
                
            except SyntaxError as e:
                print(f"❌ Синтаксическая ошибка в interfaces.py: {e}")
                self.results['interfaces'] = {'success': False, 'error': f"Syntax error: {e}"}
                return False
                
        except Exception as e:
            print(f"❌ Ошибка проверки интерфейсов: {e}")
            self.results['interfaces'] = {'success': False, 'error': str(e)}
            return False
    
    def _check_models(self) -> bool:
        """🏗️ Проверка файла моделей"""
        try:
            models_file = self.src_path / "core" / "models.py"
            
            if not models_file.exists():
                print("❌ Файл models.py не найден")
                return False
            
            try:
                with open(models_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                compile(content, str(models_file), 'exec')
                
                # Ищем ключевые модели
                required_models = [
                    'TradingPair', 'Position', 'TradeSignal', 'MarketData',
                    'OrderResult', 'Money', 'Price'
                ]
                
                found_models = [model for model in required_models if model in content]
                
                self.results['models'] = {
                    'success': True,
                    'file_size': len(content),
                    'found_models': found_models,
                    'total_required': len(required_models),
                    'coverage_percent': (len(found_models) / len(required_models)) * 100
                }
                
                print(f"✅ Модели проверены:")
                print(f"   📄 Размер файла: {len(content)} символов")
                print(f"   🏗️ Найдено моделей: {len(found_models)}/{len(required_models)}")
                
                return len(found_models) >= len(required_models) // 2
                
            except SyntaxError as e:
                print(f"❌ Синтаксическая ошибка в models.py: {e}")
                self.results['models'] = {'success': False, 'error': f"Syntax error: {e}"}
                return False
                
        except Exception as e:
            print(f"❌ Ошибка проверки моделей: {e}")
            self.results['models'] = {'success': False, 'error': str(e)}
            return False
    
    def _check_exceptions(self) -> bool:
        """🚨 Проверка файла исключений"""
        try:
            exceptions_file = self.src_path / "core" / "exceptions.py"
            
            if not exceptions_file.exists():
                print("❌ Файл exceptions.py не найден")
                return False
            
            try:
                with open(exceptions_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                compile(content, str(exceptions_file), 'exec')
                
                # Ищем ключевые исключения
                required_exceptions = [
                    'TradingSystemError', 'APIError', 'TradingError',
                    'RiskManagementError', 'ValidationError', 'ConfigurationError'
                ]
                
                found_exceptions = [exc for exc in required_exceptions if exc in content]
                
                self.results['exceptions'] = {
                    'success': True,
                    'file_size': len(content),
                    'found_exceptions': found_exceptions,
                    'total_required': len(required_exceptions),
                    'coverage_percent': (len(found_exceptions) / len(required_exceptions)) * 100
                }
                
                print(f"✅ Исключения проверены:")
                print(f"   📄 Размер файла: {len(content)} символов")
                print(f"   🚨 Найдено исключений: {len(found_exceptions)}/{len(required_exceptions)}")
                
                return len(found_exceptions) >= len(required_exceptions) // 2
                
            except SyntaxError as e:
                print(f"❌ Синтаксическая ошибка в exceptions.py: {e}")
                self.results['exceptions'] = {'success': False, 'error': f"Syntax error: {e}"}
                return False
                
        except Exception as e:
            print(f"❌ Ошибка проверки исключений: {e}")
            self.results['exceptions'] = {'success': False, 'error': str(e)}
            return False
    
    def _check_events(self) -> bool:
        """📡 Проверка файла событий"""
        try:
            events_file = self.src_path / "core" / "events.py"
            
            if not events_file.exists():
                print("❌ Файл events.py не найден")
                return False
            
            try:
                with open(events_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                compile(content, str(events_file), 'exec')
                
                # Ищем ключевые компоненты событий
                required_components = [
                    'IEventBus', 'EventBus', 'DomainEvent',
                    'EventSubscription', 'EventDispatcher'
                ]
                
                found_components = [comp for comp in required_components if comp in content]
                
                self.results['events'] = {
                    'success': True,
                    'file_size': len(content),
                    'found_components': found_components,
                    'total_required': len(required_components),
                    'coverage_percent': (len(found_components) / len(required_components)) * 100
                }
                
                print(f"✅ События проверены:")
                print(f"   📄 Размер файла: {len(content)} символов")
                print(f"   📡 Найдено компонентов: {len(found_components)}/{len(required_components)}")
                
                return len(found_components) >= len(required_components) // 2
                
            except SyntaxError as e:
                print(f"❌ Синтаксическая ошибка в events.py: {e}")
                self.results['events'] = {'success': False, 'error': f"Syntax error: {e}"}
                return False
                
        except Exception as e:
            print(f"❌ Ошибка проверки событий: {e}")
            self.results['events'] = {'success': False, 'error': str(e)}
            return False
    
    def _check_di_container(self) -> bool:
        """💉 Проверка DI контейнера"""
        try:
            di_file = self.src_path / "core" / "di_container.py"
            
            if not di_file.exists():
                print("❌ Файл di_container.py не найден")
                return False
            
            try:
                with open(di_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                compile(content, str(di_file), 'exec')
                
                # Ищем ключевые компоненты DI
                required_components = [
                    'DependencyContainer', 'ServiceDescriptor', 'ServiceLifetime',
                    'ContainerBuilder', 'ServiceLocator'
                ]
                
                found_components = [comp for comp in required_components if comp in content]
                
                self.results['di_container'] = {
                    'success': True,
                    'file_size': len(content),
                    'found_components': found_components,
                    'total_required': len(required_components),
                    'coverage_percent': (len(found_components) / len(required_components)) * 100
                }
                
                print(f"✅ DI контейнер проверен:")
                print(f"   📄 Размер файла: {len(content)} символов")
                print(f"   💉 Найдено компонентов: {len(found_components)}/{len(required_components)}")
                
                return len(found_components) >= len(required_components) // 2
                
            except SyntaxError as e:
                print(f"❌ Синтаксическая ошибка в di_container.py: {e}")
                self.results['di_container'] = {'success': False, 'error': f"Syntax error: {e}"}
                return False
                
        except Exception as e:
            print(f"❌ Ошибка проверки DI контейнера: {e}")
            self.results['di_container'] = {'success': False, 'error': str(e)}
            return False
    
    def _check_config(self) -> bool:
        """⚙️ Проверка системы конфигурации"""
        try:
            config_file = self.src_path / "config" / "settings.py"
            
            if not config_file.exists():
                print("❌ Файл config/settings.py не найден")
                return False
            
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                compile(content, str(config_file), 'exec')
                
                # Ищем ключевые компоненты конфигурации
                required_components = [
                    'TradingSystemSettings', 'ConfigProvider', 'TradingProfile',
                    'APISettings', 'TradingSettings', 'RiskSettings'
                ]
                
                found_components = [comp for comp in required_components if comp in content]
                
                self.results['config'] = {
                    'success': True,
                    'file_size': len(content),
                    'found_components': found_components,
                    'total_required': len(required_components),
                    'coverage_percent': (len(found_components) / len(required_components)) * 100
                }
                
                print(f"✅ Конфигурация проверена:")
                print(f"   📄 Размер файла: {len(content)} символов")
                print(f"   ⚙️ Найдено компонентов: {len(found_components)}/{len(required_components)}")
                
                return len(found_components) >= len(required_components) // 2
                
            except SyntaxError as e:
                print(f"❌ Синтаксическая ошибка в settings.py: {e}")
                self.results['config'] = {'success': False, 'error': f"Syntax error: {e}"}
                return False
                
        except Exception as e:
            print(f"❌ Ошибка проверки конфигурации: {e}")
            self.results['config'] = {'success': False, 'error': str(e)}
            return False
    
    def _run_validation_tests(self) -> bool:
        """🧪 Запуск валидационных тестов"""
        try:
            test_results = {
                'import_tests': self._test_imports(),
                'instantiation_tests': self._test_instantiation(),
                'integration_tests': self._test_basic_integration()
            }
            
            all_passed = all(test_results.values())
            
            self.results['validation'] = {
                'success': all_passed,
                'test_results': test_results,
                'total_tests': len(test_results),
                'passed_tests': sum(test_results.values())
            }
            
            print(f"✅ Валидация завершена:")
            print(f"   🧪 Тестов пройдено: {sum(test_results.values())}/{len(test_results)}")
            
            for test_name, result in test_results.items():
                status = "✅" if result else "❌"
                print(f"   {status} {test_name}")
            
            return all_passed
            
        except Exception as e:
            print(f"❌ Ошибка валидации: {e}")
            self.results['validation'] = {'success': False, 'error': str(e)}
            return False
    
    def _test_imports(self) -> bool:
        """📥 Тест импортов"""
        try:
            # Добавляем src в путь
            sys.path.insert(0, str(self.src_path))
            
            # Тестируем импорты core модулей
            core_modules = [
                'core.interfaces',
                'core.models', 
                'core.exceptions',
                'core.events',
                'core.di_container',
                'config.settings'
            ]
            
            import_errors = []
            for module_name in core_modules:
                try:
                    __import__(module_name)
                except Exception as e:
                    import_errors.append(f"{module_name}: {e}")
            
            if import_errors:
                print(f"⚠️ Ошибки импорта: {len(import_errors)}")
                for error in import_errors[:3]:  # Показываем первые 3
                    print(f"     {error}")
                return False
            
            return True
            
        except Exception as e:
            print(f"❌ Критическая ошибка тестирования импортов: {e}")
            return False
    
    def _test_instantiation(self) -> bool:
        """🏭 Тест создания экземпляров"""
        try:
            # Импортируем модули
            from core.models import TradingPair, Money, Position, TradeSignal
            from core.di_container import DependencyContainer, ContainerBuilder
            from config.settings import TradingSystemSettings, ConfigProvider
            
            # Тестируем создание базовых объектов
            test_objects = []
            
            # TradingPair
            pair = TradingPair("DOGE", "EUR")
            test_objects.append(("TradingPair", pair))
            
            # Money
            money = Money(amount=100, currency="EUR")
            test_objects.append(("Money", money))
            
            # Position
            position = Position(currency="DOGE")
            test_objects.append(("Position", position))
            
            # TradeSignal
            signal = TradeSignal()
            test_objects.append(("TradeSignal", signal))
            
            # DependencyContainer
            container = DependencyContainer()
            test_objects.append(("DependencyContainer", container))
            
            # ConfigProvider
            config_provider = ConfigProvider()
            test_objects.append(("ConfigProvider", config_provider))
            
            print(f"✅ Создано объектов: {len(test_objects)}")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка создания экземпляров: {e}")
            return False
    
    def _test_basic_integration(self) -> bool:
        """🔗 Тест базовой интеграции"""
        try:
            from core.models import TradingPair, Money, Position
            from core.di_container import DependencyContainer
            from config.settings import TradingSystemSettings
            
            # Тест работы с моделями
            pair = TradingPair.from_string("DOGE_EUR")
            money1 = Money(100, "EUR")
            money2 = Money(50, "EUR")
            total = money1 + money2
            
            # Тест позиции
            position = Position(currency="DOGE", quantity=1000, avg_price=0.18)
            profit = position.calculate_profit_loss(0.20)
            
            # Тест DI контейнера
            container = DependencyContainer()
            container.register_instance(str, "test_string")
            resolved = container.resolve(str)
            
            # Тест конфигурации
            settings = TradingSystemSettings()
            settings.validate()
            
            print(f"✅ Интеграционные тесты прошли успешно")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка интеграционного тестирования: {e}")
            return False
    
    def _generate_stage2_summary(self) -> None:
        """📋 Генерация итогового отчета этапа 2"""
        
        elapsed_time = time.time() - self.start_time
        
        # Подсчитываем общую статистику
        total_files = 0
        total_size = 0
        
        for component, result in self.results.items():
            if result.get('success') and 'file_size' in result:
                total_files += 1
                total_size += result['file_size']
        
        summary = {
            'stage': 2,
            'name': 'Создание ядра новой архитектуры',
            'execution_time_minutes': round(elapsed_time / 60, 2),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'results': self.results,
            'overall_success': all(
                result.get('success', False) 
                for result in self.results.values()
            ),
            'statistics': {
                'total_core_files': total_files,
                'total_code_size': total_size,
                'components_created': list(self.results.keys()),
                'success_rate': sum(1 for r in self.results.values() if r.get('success', False)) / max(len(self.results), 1) * 100
            },
            'next_steps': self._generate_next_steps(),
            'critical_findings': self._extract_critical_findings(),
            'architecture_readiness': self._assess_architecture_readiness()
        }
        
        # Сохраняем отчет
        output_file = "stage2_core_creation_summary.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        print(f"📄 Итоговый отчет этапа 2 сохранен в {output_file}")
        
        self.results['summary'] = summary
    
    def _generate_next_steps(self) -> List[str]:
        """🚀 Генерация следующих шагов"""
        next_steps = []
        
        # На основе результатов этапа 2
        failed_components = [
            name for name, result in self.results.items() 
            if not result.get('success', False)
        ]
        
        if failed_components:
            next_steps.append(f"🔴 КРИТИЧНО: Исправьте компоненты: {', '.join(failed_components)}")
        
        validation_success = self.results.get('validation', {}).get('success', False)
        if not validation_success:
            next_steps.append("🧪 Исправьте ошибки валидации и тестирования")
        
        # Если все хорошо - переходим к следующему этапу
        if not failed_components and validation_success:
            next_steps.extend([
                "🎯 Готов к Этапу 3: Создание Domain слоя",
                "🏛️ Создайте доменные сервисы торговли",
                "🎯 Реализуйте торговые стратегии",
                "🛡️ Добавьте риск-менеджмент сервисы",
                "📊 Создайте аналитические сервисы"
            ])
        else:
            next_steps.extend([
                "🔄 Повторите этап 2 после исправления ошибок",
                "📝 Изучите логи ошибок в деталях",
                "🧪 Запустите unit тесты для каждого компонента"
            ])
        
        return next_steps
    
    def _extract_critical_findings(self) -> List[str]:
        """🎯 Извлечение критических находок"""
        findings = []
        
        # Анализ покрытия компонентов
        for component, result in self.results.items():
            if result.get('success') and 'coverage_percent' in result:
                coverage = result['coverage_percent']
                if coverage < 80:
                    findings.append(f"📊 {component}: покрытие {coverage:.1f}% (низкое)")
        
        # Проверка размеров файлов
        large_files = []
        for component, result in self.results.items():
            if result.get('success') and 'file_size' in result:
                size = result['file_size']
                if size > 15000:  # > 15KB
                    large_files.append(f"{component} ({size} символов)")
        
        if large_files:
            findings.append(f"📄 Большие файлы: {', '.join(large_files)}")
        
        # Ошибки валидации
        validation_result = self.results.get('validation', {})
        if not validation_result.get('success', False):
            test_results = validation_result.get('test_results', {})
            failed_tests = [name for name, passed in test_results.items() if not passed]
            if failed_tests:
                findings.append(f"🧪 Провалены тесты: {', '.join(failed_tests)}")
        
        return findings
    
    def _assess_architecture_readiness(self) -> Dict[str, Any]:
        """🏗️ Оценка готовности архитектуры"""
        
        # Подсчитываем готовность по компонентам
        component_readiness = {}
        for component, result in self.results.items():
            if 'coverage_percent' in result:
                component_readiness[component] = result['coverage_percent']
        
        overall_readiness = sum(component_readiness.values()) / max(len(component_readiness), 1)
        
        # Оценка по критериям
        criteria = {
            'core_structure_exists': self.results.get('structure', {}).get('success', False),
            'interfaces_complete': self.results.get('interfaces', {}).get('coverage_percent', 0) >= 80,
            'models_complete': self.results.get('models', {}).get('coverage_percent', 0) >= 80,
            'exceptions_complete': self.results.get('exceptions', {}).get('coverage_percent', 0) >= 80,
            'di_container_works': self.results.get('di_container', {}).get('success', False),
            'config_system_works': self.results.get('config', {}).get('success', False),
            'validation_passes': self.results.get('validation', {}).get('success', False)
        }
        
        passed_criteria = sum(criteria.values())
        total_criteria = len(criteria)
        criteria_score = (passed_criteria / total_criteria) * 100
        
        return {
            'overall_readiness_percent': round(overall_readiness, 1),
            'criteria_score_percent': round(criteria_score, 1),
            'passed_criteria': passed_criteria,
            'total_criteria': total_criteria,
            'component_readiness': component_readiness,
            'criteria_details': criteria,
            'ready_for_stage3': (criteria_score >= 85 and overall_readiness >= 80)
        }
    
    def _print_final_results(self, overall_success: bool) -> None:
        """📊 Печать итоговых результатов"""
        
        elapsed_time = time.time() - self.start_time
        
        print("\n" + "="*60)
        print("📋 ИТОГИ ЭТАПА 2: СОЗДАНИЕ ЯДРА")
        print("="*60)
        
        print(f"⏱️ Время выполнения: {elapsed_time/60:.1f} минут")
        print(f"📊 Статус этапа: {'✅ УСПЕШНО' if overall_success else '❌ ТРЕБУЕТ ДОРАБОТКИ'}")
        
        # Результаты по компонентам
        print(f"\n📋 РЕЗУЛЬТАТЫ ПО КОМПОНЕНТАМ:")
        components = [
            ("2.1 Структура", "structure"),
            ("2.2 Интерфейсы", "interfaces"),
            ("2.3 Модели", "models"),
            ("2.4 Исключения", "exceptions"),
            ("2.5 События", "events"),
            ("2.6 DI контейнер", "di_container"),
            ("2.7 Конфигурация", "config"),
            ("2.8 Валидация", "validation")
        ]
        
        for comp_name, comp_key in components:
            result = self.results.get(comp_key, {})
            status = "✅" if result.get('success', False) else "❌"
            coverage = result.get('coverage_percent', 0)
            coverage_str = f" ({coverage:.0f}%)" if coverage > 0 else ""
            print(f"  {status} {comp_name}{coverage_str}")
        
        # Архитектурная готовность
        readiness = self._assess_architecture_readiness()
        print(f"\n🏗️ ГОТОВНОСТЬ АРХИТЕКТУРЫ:")
        print(f"  📊 Общая готовность: {readiness['overall_readiness_percent']}%")
        print(f"  ✅ Критерии выполнены: {readiness['passed_criteria']}/{readiness['total_criteria']}")
        print(f"  🎯 Готов к Этапу 3: {'✅ ДА' if readiness['ready_for_stage3'] else '❌ НЕТ'}")
        
        # Критические находки
        findings = self._extract_critical_findings()
        if findings:
            print(f"\n🎯 КРИТИЧЕСКИЕ НАХОДКИ:")
            for finding in findings[:3]:
                print(f"  • {finding}")
        
        # Следующие шаги
        next_steps = self._generate_next_steps()
        print(f"\n🚀 СЛЕДУЮЩИЕ ШАГИ:")
        for i, step in enumerate(next_steps[:5], 1):
            print(f"  {i}. {step}")
        
        print("="*60)


def main():
    """🚀 Главная функция"""
    
    print("🚀 Запуск создания ядра новой архитектуры (Этап 2)")
    print("⏱️ Ожидаемое время выполнения: 2-5 минут")
    
    try:
        runner = Stage2Runner()
        success = runner.run_complete_stage2()
        
        if success:
            print(f"\n🎉 ЭТАП 2 ЗАВЕРШЕН УСПЕШНО!")
            print(f"🏗️ Core слой новой архитектуры создан:")
            print(f"  • src/core/interfaces.py - Все интерфейсы системы")
            print(f"  • src/core/models.py - Базовые модели данных")
            print(f"  • src/core/exceptions.py - Система исключений")
            print(f"  • src/core/events.py - Система событий")
            print(f"  • src/core/di_container.py - Dependency Injection")
            print(f"  • src/config/settings.py - Система конфигурации")
            print(f"\n🚀 Готов к переходу на Этап 3: Domain слой")
            return True
        else:
            print(f"\n⚠️ ЭТАП 2 ТРЕБУЕТ ДОРАБОТКИ")
            print(f"🔍 Изучите отчет stage2_core_creation_summary.json")
            print(f"🔄 Исправьте ошибки и повторите этап")
            return False
    
    except KeyboardInterrupt:
        print(f"\n⌨️ Выполнение прервано пользователем")
        return False
    
    except Exception as e:
        print(f"\n💥 Критическая ошибка: {e}")
        print(f"🔍 Проверьте наличие всех файлов Core слоя")
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"💥 Неожиданная ошибка: {e}")
        sys.exit(1)