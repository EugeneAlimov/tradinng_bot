#!/usr/bin/env python3
"""🔍 Проверка готовности системы после миграции"""

import sys
import os
from pathlib import Path
import importlib.util
from typing import List, Tuple, Dict, Any

class SystemChecker:
    """🔍 Проверщик готовности системы"""
    
    def __init__(self):
        self.root_dir = Path(".")
        self.src_dir = Path("src")
        self.checks_passed = 0
        self.checks_total = 0
        self.warnings = []
        self.errors = []
    
    def run_all_checks(self) -> bool:
        """🔍 Запуск всех проверок"""
        print("🔍 ПРОВЕРКА ГОТОВНОСТИ СИСТЕМЫ")
        print("=" * 50)
        
        checks = [
            ("📁 Структура директорий", self._check_directory_structure),
            ("📄 Основные файлы", self._check_core_files),
            ("🐍 Python модули", self._check_python_modules),
            ("⚙️ Конфигурация", self._check_configuration),
            ("🔄 Адаптеры", self._check_adapters),
            ("💾 Бэкапы", self._check_backups),
            ("🧪 Тесты", self._check_tests),
            ("📚 Документация", self._check_documentation)
        ]
        
        for check_name, check_func in checks:
            self._run_check(check_name, check_func)
        
        self._print_summary()
        return self.checks_passed == self.checks_total
    
    def _run_check(self, name: str, check_func) -> None:
        """🔍 Выполнение отдельной проверки"""
        self.checks_total += 1
        
        try:
            result = check_func()
            if result:
                print(f"✅ {name}")
                self.checks_passed += 1
            else:
                print(f"❌ {name}")
        except Exception as e:
            print(f"❌ {name}: {e}")
            self.errors.append(f"{name}: {e}")
    
    def _check_directory_structure(self) -> bool:
        """📁 Проверка структуры директорий"""
        required_dirs = [
            "src", "src/core", "src/config", "src/infrastructure",
            "src/domain", "src/application", "src/presentation",
            "tests", "backup_before_migration"
        ]
        
        missing_dirs = []
        for dir_path in required_dirs:
            if not (self.root_dir / dir_path).exists():
                missing_dirs.append(dir_path)
        
        if missing_dirs:
            self.errors.append(f"Отсутствуют директории: {', '.join(missing_dirs)}")
            return False
        
        return True
    
    def _check_core_files(self) -> bool:
        """📄 Проверка основных файлов"""
        required_files = [
            "main.py",
            "requirements.txt", 
            ".env.example",
            "src/core/interfaces.py",
            "src/core/models.py",
            "src/core/exceptions.py",
            "src/config/settings.py",
            "src/adapters.py"
        ]
        
        missing_files = []
        for file_path in required_files:
            if not (self.root_dir / file_path).exists():
                missing_files.append(file_path)
        
        if missing_files:
            self.errors.append(f"Отсутствуют файлы: {', '.join(missing_files)}")
            return False
        
        return True
    
    def _check_python_modules(self) -> bool:
        """🐍 Проверка Python модулей"""
        # Добавляем src в путь
        src_path = str(self.src_dir.absolute())
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        
        modules_to_check = [
            ("core.interfaces", "Основные интерфейсы"),
            ("core.models", "Модели данных"),
            ("core.exceptions", "Исключения"),
            ("config.settings", "Конфигурация"),
            ("adapters", "Адаптеры")
        ]
        
        failed_imports = []
        for module_name, description in modules_to_check:
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                failed_imports.append(f"{description} ({module_name}): {e}")
        
        if failed_imports:
            self.errors.extend(failed_imports)
            return False
        
        return True
    
    def _check_configuration(self) -> bool:
        """⚙️ Проверка конфигурации"""
        try:
            # Добавляем src в путь если не добавлен
            src_path = str(self.src_dir.absolute())
            if src_path not in sys.path:
                sys.path.insert(0, src_path)
            
            from config.settings import get_settings
            
            # Пытаемся загрузить настройки
            settings = get_settings()
            
            # Проверяем .env файл
            env_file = self.root_dir / ".env"
            if not env_file.exists():
                self.warnings.append("Файл .env не найден. Скопируйте .env.example в .env")
            
            # Проверяем API ключи
            if not settings.exmo_api_key or not settings.exmo_api_secret:
                self.warnings.append("API ключи не настроены в .env файле")
            
            return True
            
        except Exception as e:
            self.errors.append(f"Ошибка конфигурации: {e}")
            return False
    
    def _check_adapters(self) -> bool:
        """🔄 Проверка адаптеров"""
        try:
            from adapters import LegacyBotAdapter, StrategyAdapter
            
            # Проверяем LegacyBotAdapter
            adapter = LegacyBotAdapter(use_hybrid=False)
            
            # Проверяем доступность старых ботов
            old_bots_available = []
            if (self.root_dir / "bot.py").exists():
                old_bots_available.append("bot.py")
            if (self.root_dir / "hybrid_bot.py").exists():
                old_bots_available.append("hybrid_bot.py")
            
            if not old_bots_available:
                self.warnings.append("Старые файлы ботов не найдены - legacy режим недоступен")
            
            return True
            
        except Exception as e:
            self.errors.append(f"Ошибка адаптеров: {e}")
            return False
    
    def _check_backups(self) -> bool:
        """💾 Проверка бэкапов"""
        backup_dir = self.root_dir / "backup_before_migration"
        
        if not backup_dir.exists():
            self.warnings.append("Директория бэкапа не найдена")
            return True  # Не критично
        
        # Проверяем важные файлы в бэкапе
        important_backups = ["bot.py", "config.py", "main.py"]
        missing_backups = []
        
        for file_name in important_backups:
            if not (backup_dir / file_name).exists():
                # Проверяем есть ли этот файл в корне (возможно не был скопирован)
                if (self.root_dir / file_name).exists():
                    missing_backups.append(file_name)
        
        if missing_backups:
            self.warnings.append(f"Не сохранены в бэкапе: {', '.join(missing_backups)}")
        
        return True
    
    def _check_tests(self) -> bool:
        """🧪 Проверка тестов"""
        test_files = [
            "tests/conftest.py",
            "tests/test_config.py", 
            "tests/test_adapters.py",
            "pytest.ini"
        ]
        
        missing_tests = []
        for test_file in test_files:
            if not (self.root_dir / test_file).exists():
                missing_tests.append(test_file)
        
        if missing_tests:
            self.warnings.append(f"Отсутствуют тестовые файлы: {', '.join(missing_tests)}")
        
        # Проверяем можно ли запустить pytest
        try:
            import pytest
        except ImportError:
            self.warnings.append("pytest не установлен. Установите: pip install pytest")
        
        return True
    
    def _check_documentation(self) -> bool:
        """📚 Проверка документации"""
        docs = [
            "README_NEW.md",
            "CHANGELOG.md"
        ]
        
        missing_docs = []
        for doc in docs:
            if not (self.root_dir / doc).exists():
                missing_docs.append(doc)
        
        if missing_docs:
            self.warnings.append(f"Отсутствует документация: {', '.join(missing_docs)}")
        
        return True
    
    def _print_summary(self) -> None:
        """📋 Вывод сводки проверки"""
        print("\n📋 СВОДКА ПРОВЕРКИ")
        print("=" * 30)
        
        success_rate = (self.checks_passed / self.checks_total) * 100 if self.checks_total > 0 else 0
        
        print(f"✅ Пройдено: {self.checks_passed}/{self.checks_total} ({success_rate:.0f}%)")
        
        if self.warnings:
            print(f"\n⚠️ ПРЕДУПРЕЖДЕНИЯ ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  • {warning}")
        
        if self.errors:
            print(f"\n❌ ОШИБКИ ({len(self.errors)}):")
            for error in self.errors:
                print(f"  • {error}")
        
        print("\n🎯 СТАТУС ГОТОВНОСТИ:")
        if self.checks_passed == self.checks_total:
            print("✅ Система полностью готова к работе")
        elif self.checks_passed >= self.checks_total * 0.8:
            print("⚠️ Система готова с предупреждениями")
        else:
            print("❌ Система требует исправления ошибок")
    
    def run_mode_compatibility_check(self) -> Dict[str, bool]:
        """🎭 Проверка совместимости режимов"""
        print("\n🎭 ПРОВЕРКА РЕЖИМОВ РАБОТЫ")
        print("=" * 30)
        
        modes = {
            "hybrid": self._check_hybrid_mode(),
            "legacy": self._check_legacy_mode(), 
            "new": self._check_new_mode()
        }
        
        for mode, available in modes.items():
            status = "✅ Доступен" if available else "❌ Недоступен"
            print(f"  {mode}: {status}")
        
        return modes
    
    def _check_hybrid_mode(self) -> bool:
        """🎭 Проверка гибридного режима"""
        try:
            # Проверяем новую конфигурацию
            src_path = str(self.src_dir.absolute())
            if src_path not in sys.path:
                sys.path.insert(0, src_path)
            
            from config.settings import get_settings
            from adapters import LegacyBotAdapter
            
            settings = get_settings()
            adapter = LegacyBotAdapter()
            
            return True
        except Exception:
            return False
    
    def _check_legacy_mode(self) -> bool:
        """📜 Проверка legacy режима"""
        # Проверяем наличие старых файлов
        legacy_files = ["bot.py", "config.py"]
        
        for file_name in legacy_files:
            if not (self.root_dir / file_name).exists():
                return False
        
        # Пытаемся импортировать
        try:
            if (self.root_dir / "hybrid_bot.py").exists():
                spec = importlib.util.spec_from_file_location("hybrid_bot", "hybrid_bot.py")
                module = importlib.util.module_from_spec(spec)
                return True
            elif (self.root_dir / "bot.py").exists():
                spec = importlib.util.spec_from_file_location("bot", "bot.py")
                module = importlib.util.module_from_spec(spec)
                return True
        except Exception:
            pass
        
        return False
    
    def _check_new_mode(self) -> bool:
        """🆕 Проверка нового режима"""
        # Новый режим пока в разработке
        return False
    
    def generate_startup_script(self) -> None:
        """🚀 Генерация скрипта запуска"""
        print("\n🚀 ГЕНЕРАЦИЯ СКРИПТА ЗАПУСКА")
        print("=" * 30)
        
        startup_script = '''#!/bin/bash
# 🚀 Скрипт запуска DOGE Trading Bot v4.1-refactored

echo "🤖 DOGE Trading Bot v4.1-refactored"
echo "=================================="

# Проверяем зависимости
echo "📦 Проверка зависимостей..."
if ! pip list | grep -q "requests"; then
    echo "📦 Устанавливаем зависимости..."
    pip install -r requirements.txt
fi

# Проверяем конфигурацию
echo "⚙️ Проверка конфигурации..."
python main.py --validate

if [ $? -ne 0 ]; then
    echo "❌ Ошибка конфигурации!"
    echo "💡 Проверьте файл .env"
    exit 1
fi

# Запускаем бота
echo "🚀 Запуск бота в гибридном режиме..."
python main.py --mode hybrid --profile balanced

'''
        
        with open("start_bot.sh", "w") as f:
            f.write(startup_script)
        
        # Делаем исполняемым
        os.chmod("start_bot.sh", 0o755)
        
        print("✅ Создан: start_bot.sh")
        print("🚀 Запуск: ./start_bot.sh")


def main():
    """🚀 Главная функция"""
    checker = SystemChecker()
    
    # Основная проверка
    all_checks_passed = checker.run_all_checks()
    
    # Проверка режимов
    modes = checker.run_mode_compatibility_check()
    
    # Генерируем скрипт запуска
    checker.generate_startup_script()
    
    print("\n🎯 РЕКОМЕНДАЦИИ:")
    
    if all_checks_passed:
        print("✅ Система готова к работе!")
        print("🚀 Запустите: python main.py --mode hybrid")
    else:
        print("⚠️ Обнаружены проблемы:")
        if checker.errors:
            print("  1. Исправьте ошибки выше")
        if checker.warnings:
            print("  2. Рассмотрите предупреждения")
        
        # Предлагаем альтернативы
        if modes.get("legacy", False):
            print("  3. Или используйте: python main.py --mode legacy")
    
    if not (Path(".env").exists()):
        print("📝 Не забудьте:")
        print("  • Скопировать .env.example в .env")
        print("  • Настроить API ключи в .env")
    
    print("\n📚 Документация:")
    print("  📖 README_NEW.md - руководство")
    print("  📋 CHANGELOG.md - изменения")
    print("  🧪 pytest tests/ - запуск тестов")


if __name__ == "__main__":
    main()