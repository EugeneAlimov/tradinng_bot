#!/usr/bin/env python3
"""🚀 Запускатель этапа 1: Анализ и планирование"""

import sys
import os
import time
from pathlib import Path
from typing import Dict, Any
import json


class Stage1Runner:
    """🚀 Координатор выполнения этапа 1"""
    
    def __init__(self):
        self.root_path = Path(".")
        self.results = {}
        self.start_time = time.time()
        
        print("🔍 ЭТАП 1: АНАЛИЗ И ПЛАНИРОВАНИЕ")
        print("=" * 50)
        print("📋 Задачи этапа:")
        print("  1.1 📊 Инвентаризация компонентов")
        print("  1.2 🏗️ Архитектурное планирование") 
        print("  1.3 🔗 Анализ зависимостей")
        print("  1.4 🔍 Проверка готовности к интеграции")
        print("=" * 50)
    
    def run_complete_stage1(self) -> bool:
        """🎯 Выполнение полного этапа 1"""
        
        success = True
        
        try:
            # 1.1 Инвентаризация компонентов
            print("\n📊 Шаг 1.1: Инвентаризация компонентов...")
            inventory_result = self._run_component_inventory()
            success = success and inventory_result
            
            # 1.2 Архитектурное планирование
            print("\n🏗️ Шаг 1.2: Архитектурное планирование...")
            architecture_result = self._run_architecture_planning()
            success = success and architecture_result
            
            # 1.3 Анализ зависимостей
            print("\n🔗 Шаг 1.3: Анализ зависимостей...")
            dependency_result = self._run_dependency_analysis()
            success = success and dependency_result
            
            # 1.4 Проверка готовности
            print("\n🔍 Шаг 1.4: Проверка готовности к интеграции...")
            readiness_result = self._run_integration_check()
            
            # Генерируем итоговый отчет
            self._generate_stage1_summary()
            
            # Определяем общий результат
            overall_success = (inventory_result and architecture_result and 
                             dependency_result and readiness_result)
            
            self._print_final_results(overall_success)
            
            return overall_success
            
        except Exception as e:
            print(f"❌ Критическая ошибка этапа 1: {e}")
            return False
    
    def _run_component_inventory(self) -> bool:
        """📊 Запуск инвентаризации компонентов"""
        try:
            # Проверяем наличие файла инвентаризации
            inventory_file = self.root_path / "component_inventory.py"
            if not inventory_file.exists():
                print("❌ Файл component_inventory.py не найден")
                return False
            
            # Импортируем и запускаем
            sys.path.insert(0, str(self.root_path))
            
            from component_inventory import ComponentInventory
            
            inventory = ComponentInventory()
            report = inventory.analyze_project()
            
            self.results['inventory'] = {
                'success': True,
                'metrics': report['metrics'],
                'issues_count': sum(len(issues) for issues in report['issues'].values()),
                'critical_path_length': len(report['critical_path']),
                'recommendations_count': len(report['migration_recommendations'])
            }
            
            print(f"✅ Инвентаризация завершена:")
            print(f"   📦 Компонентов найдено: {report['metrics']['total_components']}")
            print(f"   📜 Legacy компонентов: {report['metrics']['legacy_components']}")
            print(f"   🎯 Критических: {report['metrics']['critical_components']}")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка инвентаризации: {e}")
            self.results['inventory'] = {'success': False, 'error': str(e)}
            return False
    
    def _run_architecture_planning(self) -> bool:
        """🏗️ Запуск архитектурного планирования"""
        try:
            architecture_file = self.root_path / "architecture_planner.py"
            if not architecture_file.exists():
                print("❌ Файл architecture_planner.py не найден")
                return False
            
            from architecture_planner import ArchitecturePlanner
            
            planner = ArchitecturePlanner()
            plan = planner.create_clean_architecture_plan()
            timeline = planner.generate_migration_timeline()
            
            # Подсчитываем компоненты по слоям
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
                layer_stats[layer] = layer_stats.get(layer, 0) + 1
            
            self.results['architecture'] = {
                'success': True,
                'contexts_count': len(plan.contexts),
                'total_components': len(all_components),
                'layer_distribution': layer_stats,
                'estimated_days': timeline['total_estimate']['days'],
                'estimated_lines': timeline['total_estimate']['total_lines_estimate']
            }
            
            print(f"✅ Архитектурное планирование завершено:")
            print(f"   🗂️ Bounded contexts: {len(plan.contexts)}")
            print(f"   🏗️ Компонентов запланировано: {len(all_components)}")
            print(f"   ⏱️ Оценка времени: {timeline['total_estimate']['days']} дней")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка планирования: {e}")
            self.results['architecture'] = {'success': False, 'error': str(e)}
            return False
    
    def _run_dependency_analysis(self) -> bool:
        """🔗 Запуск анализа зависимостей"""
        try:
            dependency_file = self.root_path / "dependency_analyzer.py"
            if not dependency_file.exists():
                print("❌ Файл dependency_analyzer.py не найден")
                return False
            
            from dependency_analyzer import DependencyAnalyzer
            
            analyzer = DependencyAnalyzer()
            analysis = analyzer.analyze_dependencies()
            
            self.results['dependencies'] = {
                'success': True,
                'components_count': analysis['metrics']['total_components'],
                'dependencies_count': analysis['metrics']['total_dependencies'],
                'cycles_count': len(analysis['cycles']),
                'critical_path_length': len(analysis['critical_path']),
                'coupling_ratio': analysis['metrics']['coupling_ratio'],
                'migration_batches': len(analysis['migration_order'])
            }
            
            print(f"✅ Анализ зависимостей завершен:")
            print(f"   🔗 Зависимостей найдено: {analysis['metrics']['total_dependencies']}")
            print(f"   🔄 Циклических зависимостей: {len(analysis['cycles'])}")
            print(f"   📊 Коэффициент связанности: {analysis['metrics']['coupling_ratio']}")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка анализа зависимостей: {e}")
            self.results['dependencies'] = {'success': False, 'error': str(e)}
            return False
    
    def _run_integration_check(self) -> bool:
        """🔍 Запуск проверки готовности к интеграции"""
        try:
            integration_file = self.root_path / "integration_checker.py"
            if not integration_file.exists():
                print("❌ Файл integration_checker.py не найден")
                return False
            
            from integration_checker import IntegrationChecker
            
            checker = IntegrationChecker()
            report = checker.run_comprehensive_check()
            
            summary = report['summary']
            issues = report['issues']
            
            self.results['integration'] = {
                'success': True,
                'readiness_score': summary['readiness_score'],
                'readiness_level': summary['readiness_level'],
                'total_checks': summary['total_checks'],
                'passed_checks': summary['passed_checks'],
                'critical_issues': issues['critical'],
                'warnings': issues['warnings']
            }
            
            print(f"✅ Проверка готовности завершена:")
            print(f"   📈 Готовность: {summary['readiness_score']}%")
            print(f"   🚨 Критичных проблем: {issues['critical']}")
            print(f"   ⚠️ Предупреждений: {issues['warnings']}")
            
            # Возвращаем True если готовность > 60% и нет критичных проблем
            return (summary['readiness_score'] >= 60 and issues['critical'] == 0)
            
        except Exception as e:
            print(f"❌ Ошибка проверки готовности: {e}")
            self.results['integration'] = {'success': False, 'error': str(e)}
            return False
    
    def _generate_stage1_summary(self) -> None:
        """📋 Генерация итогового отчета этапа 1"""
        
        elapsed_time = time.time() - self.start_time
        
        summary = {
            'stage': 1,
            'name': 'Анализ и планирование',
            'execution_time_minutes': round(elapsed_time / 60, 2),
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'results': self.results,
            'overall_success': all(
                result.get('success', False) 
                for result in self.results.values()
            ),
            'next_steps': self._generate_next_steps(),
            'critical_findings': self._extract_critical_findings(),
            'recommendations': self._generate_recommendations()
        }
        
        # Сохраняем отчет
        output_file = "stage1_analysis_summary.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        print(f"📄 Итоговый отчет этапа 1 сохранен в {output_file}")
        
        self.results['summary'] = summary
    
    def _generate_next_steps(self) -> list:
        """🚀 Генерация следующих шагов"""
        next_steps = []
        
        # На основе результатов анализа
        if not self.results.get('integration', {}).get('success', False):
            next_steps.append("🔴 КРИТИЧНО: Исправьте проблемы интеграции")
        
        cycles_count = self.results.get('dependencies', {}).get('cycles_count', 0)
        if cycles_count > 3:
            next_steps.append("🔄 ВАЖНО: Разрешите циклические зависимости")
        
        readiness_score = self.results.get('integration', {}).get('readiness_score', 0)
        if readiness_score < 80:
            next_steps.append("⚠️ Повысьте готовность системы до 80%+")
        
        # Общие следующие шаги
        next_steps.extend([
            "📁 Создайте структуру директорий новой архитектуры",
            "🎯 Начните Этап 2: Создание ядра (Core слой)",
            "🏗️ Реализуйте интерфейсы и базовые модели",
            "💉 Настройте Dependency Injection",
            "🧪 Добавьте unit тесты для критических компонентов"
        ])
        
        return next_steps
    
    def _extract_critical_findings(self) -> list:
        """🎯 Извлечение критических находок"""
        findings = []
        
        # Из инвентаризации
        inventory = self.results.get('inventory', {})
        if inventory.get('success'):
            issues_count = inventory.get('issues_count', 0)
            if issues_count > 10:
                findings.append(f"📊 Найдено {issues_count} проблем в компонентах")
        
        # Из анализа зависимостей
        dependencies = self.results.get('dependencies', {})
        if dependencies.get('success'):
            cycles = dependencies.get('cycles_count', 0)
            coupling = dependencies.get('coupling_ratio', 0)
            
            if cycles > 0:
                findings.append(f"🔄 {cycles} циклических зависимостей требуют рефакторинга")
            if coupling > 3:
                findings.append(f"🔗 Высокая связанность (коэффициент {coupling})")
        
        # Из проверки готовности
        integration = self.results.get('integration', {})
        if integration.get('success'):
            critical_issues = integration.get('critical_issues', 0)
            if critical_issues > 0:
                findings.append(f"🚨 {critical_issues} критических проблем интеграции")
        
        return findings
    
    def _generate_recommendations(self) -> list:
        """💡 Генерация рекомендаций"""
        recommendations = []
        
        # На основе результатов анализа
        coupling_ratio = self.results.get('dependencies', {}).get('coupling_ratio', 0)
        if coupling_ratio > 2:
            recommendations.append("🔗 Разбейте высокосвязанные компоненты на модули")
        
        cycles_count = self.results.get('dependencies', {}).get('cycles_count', 0)
        if cycles_count > 0:
            recommendations.append("🔄 Используйте паттерн Dependency Inversion для разрыва циклов")
        
        legacy_percentage = 70  # Примерное значение
        if legacy_percentage > 60:
            recommendations.append("📜 Создайте адаптеры для постепенной миграции legacy кода")
        
        # Общие рекомендации
        recommendations.extend([
            "🏗️ Начните с реализации Core слоя (интерфейсы, модели)",
            "💉 Внедрите Dependency Injection для управления зависимостями",
            "🧪 Добавьте unit тесты перед рефакторингом",
            "📚 Обновите документацию архитектуры",
            "🔍 Проводите code review для новых компонентов"
        ])
        
        return recommendations
    
    def _print_final_results(self, overall_success: bool) -> None:
        """📊 Печать итоговых результатов"""
        
        elapsed_time = time.time() - self.start_time
        
        print("\n" + "="*60)
        print("📋 ИТОГИ ЭТАПА 1: АНАЛИЗ И ПЛАНИРОВАНИЕ")
        print("="*60)
        
        print(f"⏱️ Время выполнения: {elapsed_time/60:.1f} минут")
        print(f"📊 Статус этапа: {'✅ УСПЕШНО' if overall_success else '❌ ТРЕБУЕТ ДОРАБОТКИ'}")
        
        # Результаты по шагам
        print(f"\n📋 РЕЗУЛЬТАТЫ ПО ШАГАМ:")
        steps = [
            ("1.1 Инвентаризация", "inventory"),
            ("1.2 Архитектура", "architecture"), 
            ("1.3 Зависимости", "dependencies"),
            ("1.4 Готовность", "integration")
        ]
        
        for step_name, step_key in steps:
            result = self.results.get(step_key, {})
            status = "✅" if result.get('success', False) else "❌"
            print(f"  {status} {step_name}")
        
        # Ключевые находки
        findings = self._extract_critical_findings()
        if findings:
            print(f"\n🎯 КЛЮЧЕВЫЕ НАХОДКИ:")
            for finding in findings[:5]:
                print(f"  • {finding}")
        
        # Следующие шаги
        next_steps = self._generate_next_steps()
        print(f"\n🚀 СЛЕДУЮЩИЕ ШАГИ:")
        for i, step in enumerate(next_steps[:5], 1):
            print(f"  {i}. {step}")
        
        # Рекомендации по готовности
        if overall_success:
            print(f"\n🎉 ГОТОВНОСТЬ К ЭТАПУ 2:")
            print(f"  ✅ Система проанализирована")
            print(f"  ✅ План архитектуры создан")
            print(f"  ✅ Зависимости проанализированы")
            print(f"  ✅ Можно переходить к Этапу 2: Создание ядра")
        else:
            print(f"\n⚠️ ТРЕБУЕТСЯ ДОРАБОТКА:")
            print(f"  🔴 Исправьте критические проблемы")
            print(f"  🔄 Повторите проверки")
            print(f"  📋 Дождитесь готовности >= 80%")
        
        print("="*60)


def main():
    """🚀 Главная функция"""
    
    print("🚀 Запуск полного анализа и планирования (Этап 1)")
    print("⏱️ Ожидаемое время выполнения: 5-10 минут")
    
    try:
        runner = Stage1Runner()
        success = runner.run_complete_stage1()
        
        if success:
            print(f"\n🎉 ЭТАП 1 ЗАВЕРШЕН УСПЕШНО!")
            print(f"📋 Изучите созданные отчеты:")
            print(f"  • component_inventory_report.json")
            print(f"  • architecture_plan.json")
            print(f"  • dependency_analysis.json")
            print(f"  • integration_readiness_report.json")
            print(f"  • stage1_analysis_summary.json")
            print(f"\n🚀 Готов к переходу на Этап 2: Создание ядра")
            return True
        else:
            print(f"\n⚠️ ЭТАП 1 ТРЕБУЕТ ДОРАБОТКИ")
            print(f"🔍 Изучите отчеты и исправьте проблемы")
            print(f"🔄 Повторите выполнение этапа")
            return False
    
    except KeyboardInterrupt:
        print(f"\n⌨️ Выполнение прервано пользователем")
        return False
    
    except Exception as e:
        print(f"\n💥 Критическая ошибка: {e}")
        print(f"🔍 Проверьте наличие всех файлов анализа")
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"💥 Неожиданная ошибка: {e}")
        sys.exit(1)