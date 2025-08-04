#!/usr/bin/env python3
"""🔍 Исправленный проверщик готовности к интеграции - Этап 1.4"""

import sys
import os
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
import importlib.util


@dataclass
class IntegrationCheck:
    """✅ Результат проверки интеграции"""
    name: str
    description: str
    status: bool
    details: str
    severity: str  # critical, warning, info
    recommendations: List[str]


class IntegrationChecker:
    """🔍 Проверщик готовности к интеграции"""
    
    def __init__(self, root_path: str = "."):
        self.root_path = Path(root_path)
        self.checks: List[IntegrationCheck] = []
        
        # Критичные файлы для работы системы
        self.critical_files = [
            'config.py', 'main.py', 'api_client.py', 
            'position_manager.py', 'risk_management.py'
        ]
        
        # Критичные модули Python
        self.required_modules = [
            'requests', 'json', 'time', 'logging', 
            'decimal', 'datetime', 'pathlib'
        ]
        
        # Опциональные модули (для полной функциональности)
        self.optional_modules = [
            'pandas', 'numpy', 'matplotlib', 'seaborn'
        ]
    
    def run_comprehensive_check(self) -> Dict[str, Any]:
        """🔍 Комплексная проверка готовности"""
        print("🔍 Запуск комплексной проверки интеграции...")
        
        # Очищаем предыдущие результаты
        self.checks.clear()
        
        # Группы проверок
        self._check_environment()
        self._check_file_structure()
        self._check_python_modules()
        self._check_configuration()
        self._check_legacy_compatibility()
        self._check_new_architecture_readiness()
        self._check_dependencies_integrity()
        self._check_api_integration()
        self._check_data_migration_readiness()
        
        # Генерируем отчет
        report = self._generate_integration_report()
        
        print("✅ Проверка интеграции завершена")
        return report
    
    def _check_environment(self) -> None:
        """🐍 Проверка окружения Python"""
        # Версия Python
        python_version = sys.version_info
        if python_version >= (3, 8):
            self._add_check(
                "python_version", "Версия Python",
                True, f"Python {python_version.major}.{python_version.minor}.{python_version.micro}",
                "info", []
            )
        else:
            self._add_check(
                "python_version", "Версия Python",
                False, f"Python {python_version.major}.{python_version.minor} < 3.8",
                "critical", ["Обновите Python до версии 3.8+"]
            )
        
        # Права доступа
        try:
            test_file = self.root_path / "test_write_access.tmp"
            test_file.write_text("test")
            test_file.unlink()
            
            self._add_check(
                "write_permissions", "Права записи",
                True, "Права записи в рабочую директорию есть",
                "info", []
            )
        except Exception as e:
            self._add_check(
                "write_permissions", "Права записи",
                False, f"Нет прав записи: {e}",
                "critical", ["Проверьте права доступа к директории"]
            )
        
        # Доступное место на диске
        try:
            stat = os.statvfs(self.root_path)
            free_space_gb = (stat.f_frsize * stat.f_bavail) / (1024**3)
            
            if free_space_gb > 1.0:
                self._add_check(
                    "disk_space", "Место на диске",
                    True, f"Доступно {free_space_gb:.1f} GB",
                    "info", []
                )
            else:
                self._add_check(
                    "disk_space", "Место на диске",
                    False, f"Мало места: {free_space_gb:.1f} GB",
                    "warning", ["Освободите место на диске (рекомендуется >1GB)"]
                )
        except Exception:
            # На Windows может не работать statvfs
            self._add_check(
                "disk_space", "Место на диске",
                True, "Проверка недоступна (Windows?)",
                "info", []
            )
    
    def _check_file_structure(self) -> None:
        """📁 Проверка структуры файлов"""
        
        # Критичные файлы - ИСПРАВЛЕНО
        missing_critical = []
        for file_name in self.critical_files:
            file_path = self.root_path / file_name
            if not file_path.exists():
                missing_critical.append(file_name)
        
        if not missing_critical:
            self._add_check(
                "critical_files", "Критичные файлы",
                True, f"Все {len(self.critical_files)} критичных файлов найдены",
                "info", []
            )
        else:
            self._add_check(
                "critical_files", "Критичные файлы",
                False, f"Отсутствуют: {', '.join(missing_critical)}",
                "critical", [f"Создайте отсутствующие файлы: {', '.join(missing_critical)}"]
            )
        
        # Структура новой архитектуры
        new_arch_dirs = [
            "src", "src/core", "src/domain", "src/application", 
            "src/infrastructure", "src/presentation"
        ]
        
        existing_dirs = []
        missing_dirs = []
        
        for dir_name in new_arch_dirs:
            dir_path = self.root_path / dir_name
            if dir_path.exists():
                existing_dirs.append(dir_name)
            else:
                missing_dirs.append(dir_name)
        
        if len(existing_dirs) >= len(new_arch_dirs) // 2:
            self._add_check(
                "new_architecture_structure", "Структура новой архитектуры",
                True, f"Найдено {len(existing_dirs)} из {len(new_arch_dirs)} директорий",
                "info", []
            )
        else:
            self._add_check(
                "new_architecture_structure", "Структура новой архитектуры",
                False, f"Недостает директорий: {', '.join(missing_dirs)}",
                "warning", ["Создайте структуру директорий: mkdir -p " + " ".join(missing_dirs)]
            )
        
        # Backup директория
        backup_dir = self.root_path / "backup_before_migration"
        if backup_dir.exists():
            backup_files = list(backup_dir.glob("*.py"))
            self._add_check(
                "backup_exists", "Backup файлы",
                True, f"Найдено {len(backup_files)} backup файлов",
                "info", []
            )
        else:
            self._add_check(
                "backup_exists", "Backup файлы",
                False, "Backup директория не найдена",
                "warning", ["Создайте backup перед миграцией"]
            )
    
    def _check_python_modules(self) -> None:
        """📦 Проверка Python модулей"""
        
        # Критичные модули
        missing_critical = []
        for module_name in self.required_modules:
            if not self._check_module_available(module_name):
                missing_critical.append(module_name)
        
        if not missing_critical:
            self._add_check(
                "required_modules", "Обязательные модули",
                True, f"Все {len(self.required_modules)} модулей доступны",
                "info", []
            )
        else:
            self._add_check(
                "required_modules", "Обязательные модули",
                False, f"Отсутствуют: {', '.join(missing_critical)}",
                "critical", [f"Установите модули: pip install {' '.join(missing_critical)}"]
            )
        
        # Опциональные модули
        missing_optional = []
        for module_name in self.optional_modules:
            if not self._check_module_available(module_name):
                missing_optional.append(module_name)
        
        available_optional = len(self.optional_modules) - len(missing_optional)
        if available_optional >= len(self.optional_modules) // 2:
            self._add_check(
                "optional_modules", "Опциональные модули",
                True, f"Доступно {available_optional} из {len(self.optional_modules)}",
                "info", []
            )
        else:
            self._add_check(
                "optional_modules", "Опциональные модули",
                False, f"Мало модулей: {available_optional}/{len(self.optional_modules)}",
                "warning", [f"Для полной функциональности: pip install {' '.join(missing_optional)}"]
            )
    
    def _check_configuration(self) -> None:
        """⚙️ Проверка конфигурации"""
        
        # Проверка .env файла
        env_file = self.root_path / ".env"
        if env_file.exists():
            try:
                env_content = env_file.read_text()
                has_api_key = "EXMO_API_KEY" in env_content
                has_api_secret = "EXMO_API_SECRET" in env_content
                
                if has_api_key and has_api_secret:
                    self._add_check(
                        "env_config", "Конфигурация .env",
                        True, "API ключи настроены",
                        "info", []
                    )
                else:
                    missing = []
                    if not has_api_key:
                        missing.append("EXMO_API_KEY")
                    if not has_api_secret:
                        missing.append("EXMO_API_SECRET")
                    
                    self._add_check(
                        "env_config", "Конфигурация .env",
                        False, f"Отсутствуют: {', '.join(missing)}",
                        "critical", ["Добавьте API ключи в .env файл"]
                    )
            except Exception as e:
                self._add_check(
                    "env_config", "Конфигурация .env",
                    False, f"Ошибка чтения .env: {e}",
                    "warning", ["Проверьте формат .env файла"]
                )
        else:
            self._add_check(
                "env_config", "Конфигурация .env",
                False, ".env файл не найден",
                "critical", ["Создайте .env файл с API ключами"]
            )
        
        # Проверка config.py
        config_file = self.root_path / "config.py"
        if config_file.exists():
            try:
                # Проверяем основные классы/переменные
                expected_items = ['TradingConfig', 'API_KEY', 'API_SECRET']
                config_content = config_file.read_text()
                
                found_items = [item for item in expected_items if item in config_content]
                
                if len(found_items) >= 1:
                    self._add_check(
                        "config_file", "Файл config.py",
                        True, f"Найдены элементы: {', '.join(found_items)}",
                        "info", []
                    )
                else:
                    self._add_check(
                        "config_file", "Файл config.py",
                        False, f"Неполная конфигурация: {', '.join(found_items)}",
                        "warning", ["Проверьте структуру config.py"]
                    )
                    
            except Exception as e:
                self._add_check(
                    "config_file", "Файл config.py",
                    False, f"Ошибка загрузки: {e}",
                    "warning", ["Исправьте синтаксические ошибки в config.py"]
                )
        else:
            self._add_check(
                "config_file", "Файл config.py",
                False, "config.py не найден",
                "critical", ["Создайте файл config.py с настройками торговли"]
            )
    
    def _check_legacy_compatibility(self) -> None:
        """📜 Проверка совместимости с legacy кодом"""
        
        # Основные legacy файлы
        legacy_files = [
            'improved_bot.py', 'hybrid_bot.py', 'bot.py',
            'trade_orchestrator.py', 'strategies.py'
        ]
        
        found_legacy = []
        for file_name in legacy_files:
            if (self.root_path / file_name).exists():
                found_legacy.append(file_name)
        
        if found_legacy:
            self._add_check(
                "legacy_files", "Legacy файлы",
                True, f"Найдено {len(found_legacy)} legacy файлов",
                "info", []
            )
        else:
            self._add_check(
                "legacy_files", "Legacy файлы",
                False, "Legacy файлы не найдены",
                "critical", ["Восстановите legacy файлы из backup или репозитория"]
            )
        
        # Проверка адаптеров
        adapters_file = self.root_path / "src" / "adapters.py"
        if adapters_file.exists():
            self._add_check(
                "adapters", "Адаптеры совместимости",
                True, "Файл адаптеров найден",
                "info", []
            )
        else:
            self._add_check(
                "adapters", "Адаптеры совместимости",
                False, "Адаптеры не найдены",
                "warning", ["Создайте адаптеры для совместимости с legacy кодом"]
            )
    
    def _check_new_architecture_readiness(self) -> None:
        """🏗️ Проверка готовности новой архитектуры"""
        
        # Core компоненты
        core_files = [
            "src/core/interfaces.py",
            "src/core/models.py", 
            "src/core/exceptions.py"
        ]
        
        existing_core = []
        for file_path in core_files:
            if (self.root_path / file_path).exists():
                existing_core.append(file_path)
        
        if len(existing_core) >= 1:
            self._add_check(
                "core_components", "Core компоненты",
                True, f"Найдено {len(existing_core)} из {len(core_files)} файлов",
                "info", []
            )
        else:
            self._add_check(
                "core_components", "Core компоненты",
                False, f"Недостает core файлов: {len(core_files)}",
                "warning", ["Создайте основные core файлы (interfaces, models, exceptions)"]
            )
        
        # DI контейнер
        di_file = self.root_path / "src" / "core" / "di_container.py"
        if di_file.exists():
            self._add_check(
                "dependency_injection", "Dependency Injection",
                True, "DI контейнер найден",
                "info", []
            )
        else:
            self._add_check(
                "dependency_injection", "Dependency Injection",
                False, "DI контейнер отсутствует",
                "warning", ["Создайте DI контейнер для управления зависимостями"]
            )
    
    def _check_dependencies_integrity(self) -> None:
        """🔗 Проверка целостности зависимостей"""
        
        # Проверяем наличие анализа зависимостей
        dep_analysis_file = self.root_path / "dependency_analysis.json"
        if dep_analysis_file.exists():
            try:
                with open(dep_analysis_file, 'r', encoding='utf-8') as f:
                    analysis = json.load(f)
                
                cycles_count = len(analysis.get('cycles', []))
                components_count = analysis.get('metrics', {}).get('total_components', 0)
                
                if cycles_count == 0:
                    self._add_check(
                        "dependency_cycles", "Циклические зависимости",
                        True, "Циклические зависимости не найдены",
                        "info", []
                    )
                elif cycles_count <= 3:
                    self._add_check(
                        "dependency_cycles", "Циклические зависимости",
                        False, f"Найдено {cycles_count} циклов",
                        "warning", ["Разрешите циклические зависимости перед миграцией"]
                    )
                else:
                    self._add_check(
                        "dependency_cycles", "Циклические зависимости",
                        False, f"Много циклов: {cycles_count}",
                        "critical", ["Критически важно разрешить циклические зависимости"]
                    )
                
                if components_count > 0:
                    self._add_check(
                        "dependency_analysis", "Анализ зависимостей",
                        True, f"Проанализировано {components_count} компонентов",
                        "info", []
                    )
                
            except Exception as e:
                self._add_check(
                    "dependency_analysis", "Анализ зависимостей",
                    False, f"Ошибка чтения анализа: {e}",
                    "warning", ["Запустите dependency_analyzer.py для анализа"]
                )
        else:
            self._add_check(
                "dependency_analysis", "Анализ зависимостей",
                False, "Анализ зависимостей не проводился",
                "warning", ["Запустите dependency_analyzer.py перед миграцией"]
            )
    
    def _check_api_integration(self) -> None:
        """🌐 Проверка API интеграции"""
        
        # Проверяем API клиент
        api_client_file = self.root_path / "api_client.py"
        if api_client_file.exists():
            try:
                content = api_client_file.read_text()
                
                # Ищем основные методы EXMO API
                required_methods = [
                    'user_info', 'order_create', 'order_cancel', 
                    'user_trades', 'ticker'
                ]
                
                found_methods = [method for method in required_methods if method in content]
                
                if len(found_methods) >= len(required_methods) // 2:
                    self._add_check(
                        "api_methods", "API методы",
                        True, f"Найдено методов: {len(found_methods)}/{len(required_methods)}",
                        "info", []
                    )
                else:
                    self._add_check(
                        "api_methods", "API методы",
                        False, f"Мало API методов: {len(found_methods)}/{len(required_methods)}",
                        "warning", ["Добавьте недостающие API методы"]
                    )
                
            except Exception as e:
                self._add_check(
                    "api_client", "API клиент",
                    False, f"Ошибка анализа API клиента: {e}",
                    "warning", ["Проверьте структуру api_client.py"]
                )
        else:
            self._add_check(
                "api_client", "API клиент", 
                False, "api_client.py не найден",
                "critical", ["Создайте API клиент для работы с биржей"]
            )
        
        # Rate Limiter
        rate_limiter_file = self.root_path / "rate_limiter.py"
        if rate_limiter_file.exists():
            self._add_check(
                "rate_limiter", "Rate Limiter",
                True, "Rate Limiter найден",
                "info", []
            )
        else:
            self._add_check(
                "rate_limiter", "Rate Limiter",
                False, "Rate Limiter отсутствует",
                "critical", ["Rate Limiter критически важен для работы с API"]
            )
    
    def _check_data_migration_readiness(self) -> None:
        """💾 Проверка готовности миграции данных"""
        
        # Проверяем существующие данные
        data_dir = self.root_path / "data"
        if data_dir.exists():
            data_files = list(data_dir.glob("*.json"))
            
            if data_files:
                self._add_check(
                    "existing_data", "Существующие данные",
                    True, f"Найдено {len(data_files)} файлов данных",
                    "info", []
                )
                
                # Проверяем важные файлы данных
                important_files = ['positions.json', 'trades_history.json']
                found_important = [f for f in important_files 
                                 if (data_dir / f).exists()]
                
                if found_important:
                    self._add_check(
                        "important_data", "Важные данные",
                        True, f"Найдены: {', '.join(found_important)}",
                        "info", []
                    )
                else:
                    self._add_check(
                        "important_data", "Важные данные",
                        False, "Важные файлы данных не найдены",
                        "warning", ["Убедитесь что данные позиций и торгов сохранены"]
                    )
            else:
                self._add_check(
                    "existing_data", "Существующие данные",
                    False, "Файлы данных не найдены",
                    "warning", ["Возможно, бот еще не запускался или данные в другом месте"]
                )
        else:
            self._add_check(
                "existing_data", "Существующие данные",
                False, "Директория data не найдена",
                "warning", ["Создайте директорию data для сохранения данных"]
            )
        
        # Проверяем backup данных
        backup_data_dir = self.root_path / "backup_before_migration" / "data"
        if backup_data_dir.exists():
            backup_files = list(backup_data_dir.glob("*.json"))
            self._add_check(
                "data_backup", "Backup данных",
                True, f"Backup содержит {len(backup_files)} файлов",
                "info", []
            )
        else:
            self._add_check(
                "data_backup", "Backup данных",
                False, "Backup данных не найден",
                "warning", ["Создайте backup данных перед миграцией"]
            )
    
    def _check_module_available(self, module_name: str) -> bool:
        """📦 Проверка доступности модуля"""
        try:
            __import__(module_name)
            return True
        except ImportError:
            return False
    
    def _add_check(self, name: str, description: str, status: bool, 
                   details: str, severity: str, recommendations: List[str]) -> None:
        """➕ Добавление результата проверки"""
        check = IntegrationCheck(
            name=name,
            description=description,
            status=status,
            details=details,
            severity=severity,
            recommendations=recommendations
        )
        self.checks.append(check)
    
    def _generate_integration_report(self) -> Dict[str, Any]:
        """📋 Генерация отчета интеграции"""
        
        # Подсчет результатов
        total_checks = len(self.checks)
        passed_checks = sum(1 for check in self.checks if check.status)
        failed_checks = total_checks - passed_checks
        
        # Группировка по серьезности
        critical_issues = [c for c in self.checks if not c.status and c.severity == "critical"]
        warnings = [c for c in self.checks if not c.status and c.severity == "warning"]
        
        # Определение готовности
        readiness_score = (passed_checks / max(total_checks, 1)) * 100
        
        if len(critical_issues) == 0 and readiness_score >= 80:
            readiness_level = "ready"
            readiness_message = "✅ Система готова к миграции"
        elif len(critical_issues) <= 2 and readiness_score >= 60:
            readiness_level = "conditionally_ready"
            readiness_message = "⚠️ Система условно готова (исправьте критичные проблемы)"
        else:
            readiness_level = "not_ready"
            readiness_message = "❌ Система не готова к миграции"
        
        # Приоритетные действия
        priority_actions = []
        for issue in critical_issues[:3]:  # Топ 3 критичных
            priority_actions.extend(issue.recommendations)
        
        # Следующие шаги
        next_steps = []
        if critical_issues:
            next_steps.append("1. Исправьте критичные проблемы")
        if warnings:
            next_steps.append("2. Рассмотрите предупреждения")
        next_steps.extend([
            "3. Запустите component_inventory.py",
            "4. Выполните dependency_analyzer.py", 
            "5. Создайте архитектурный план",
            "6. Начните миграцию с Core слоя"
        ])
        
        return {
            'summary': {
                'total_checks': total_checks,
                'passed_checks': passed_checks,
                'failed_checks': failed_checks,
                'readiness_score': round(readiness_score, 1),
                'readiness_level': readiness_level,
                'readiness_message': readiness_message
            },
            'issues': {
                'critical': len(critical_issues),
                'warnings': len(warnings),
                'critical_details': [
                    {
                        'name': issue.name,
                        'description': issue.description,
                        'details': issue.details,
                        'recommendations': issue.recommendations
                    }
                    for issue in critical_issues
                ],
                'warning_details': [
                    {
                        'name': warning.name,
                        'description': warning.description,
                        'details': warning.details,
                        'recommendations': warning.recommendations
                    }
                    for warning in warnings
                ]
            },
            'checks_by_category': {
                'environment': [self._check_to_dict(c) for c in self.checks if c.name in ['python_version', 'write_permissions', 'disk_space']],
                'files': [self._check_to_dict(c) for c in self.checks if 'file' in c.name or 'structure' in c.name],
                'modules': [self._check_to_dict(c) for c in self.checks if 'module' in c.name],
                'configuration': [self._check_to_dict(c) for c in self.checks if 'config' in c.name or 'env' in c.name],
                'architecture': [self._check_to_dict(c) for c in self.checks if 'architecture' in c.name or 'core' in c.name],
                'integration': [self._check_to_dict(c) for c in self.checks if 'api' in c.name or 'dependency' in c.name]
            },
            'priority_actions': priority_actions[:5],
            'next_steps': next_steps,
            'all_checks': [self._check_to_dict(check) for check in self.checks]
        }
    
    def _check_to_dict(self, check: IntegrationCheck) -> Dict[str, Any]:
        """📄 Конвертация проверки в словарь"""
        return {
            'name': check.name,
            'description': check.description,
            'status': check.status,
            'details': check.details,
            'severity': check.severity,
            'recommendations': check.recommendations
        }
    
    def save_report(self, report: Dict[str, Any], output_file: str = "integration_readiness_report.json") -> None:
        """💾 Сохранение отчета"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"📄 Отчет готовности сохранен в {output_file}")


def main():
    """🚀 Главная функция"""
    checker = IntegrationChecker()
    report = checker.run_comprehensive_check()
    
    # Печатаем краткий отчет
    print("\n" + "="*60)
    print("🔍 ОТЧЕТ О ГОТОВНОСТИ К ИНТЕГРАЦИИ")
    print("="*60)
    
    summary = report['summary']
    print(f"📊 Проверок выполнено: {summary['total_checks']}")
    print(f"✅ Успешно: {summary['passed_checks']}")
    print(f"❌ Не пройдено: {summary['failed_checks']}")
    print(f"📈 Готовность: {summary['readiness_score']}%")
    print(f"🎯 Статус: {summary['readiness_message']}")
    
    # Критичные проблемы
    issues = report['issues']
    if issues['critical'] > 0:
        print(f"\n🚨 КРИТИЧНЫЕ ПРОБЛЕМЫ ({issues['critical']}):")
        for issue in issues['critical_details'][:3]:
            print(f"  ❌ {issue['description']}: {issue['details']}")
    
    # Предупреждения
    if issues['warnings'] > 0:
        print(f"\n⚠️ ПРЕДУПРЕЖДЕНИЯ ({issues['warnings']}):")
        for warning in issues['warning_details'][:3]:
            print(f"  ⚠️ {warning['description']}: {warning['details']}")
    
    # Приоритетные действия
    priority_actions = report['priority_actions']
    if priority_actions:
        print(f"\n🎯 ПРИОРИТЕТНЫЕ ДЕЙСТВИЯ:")
        for i, action in enumerate(priority_actions[:3], 1):
            print(f"  {i}. {action}")
    
    # Следующие шаги
    next_steps = report['next_steps']
    print(f"\n🚀 СЛЕДУЮЩИЕ ШАГИ:")
    for step in next_steps[:5]:
        print(f"  {step}")
    
    # Сохраняем отчет
    checker.save_report(report)
    
    # Возвращаем код выхода
    if summary['readiness_level'] == 'ready':
        print(f"\n🎉 Система готова к миграции!")
        return True
    elif summary['readiness_level'] == 'conditionally_ready':
        print(f"\n⚠️ Исправьте критичные проблемы перед миграцией")
        return False
    else:
        print(f"\n❌ Система требует серьезной подготовки")
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⌨️ Проверка прервана пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Неожиданная ошибка: {e}")
        sys.exit(1)