#!/usr/bin/env python3
"""🚀 Запускатель этапа 2: Быстрый запуск создания ядра архитектуры"""

import sys
import os
from pathlib import Path

def main():
    """🚀 Основная функция запуска"""
    
    print("🚀 ЗАПУСК ЭТАПА 2: СОЗДАНИЕ ЯДРА НОВОЙ АРХИТЕКТУРЫ")
    print("=" * 60)
    
    # Проверяем наличие stage2_runner.py
    runner_file = Path("stage2_runner.py")
    
    if not runner_file.exists():
        print("❌ Файл stage2_runner.py не найден!")
        print("🔍 Убедитесь что файл stage2_runner.py находится в текущей директории")
        return False
    
    try:
        # Импортируем и запускаем runner
        print("📦 Импортируем stage2_runner...")
        
        # Добавляем текущую директорию в путь
        current_dir = str(Path(".").resolve())
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        
        # Импортируем runner
        import stage2_runner
        
        print("✅ stage2_runner успешно импортирован")
        print("🏗️ Запускаем создание ядра архитектуры...")
        print("-" * 60)
        
        # Запускаем основную функцию
        success = stage2_runner.main()
        
        print("-" * 60)
        
        if success:
            print("🎉 ЭТАП 2 ЗАВЕРШЕН УСПЕШНО!")
            print("📊 Core слой новой архитектуры создан")
            print("🚀 Готов к переходу на Этап 3: Domain слой")
            
            # Показываем что создано
            src_path = Path("src")
            if src_path.exists():
                print(f"\n📁 Создана структура:")
                for item in sorted(src_path.rglob("*.py")):
                    relative_path = item.relative_to(Path("."))
                    file_size = item.stat().st_size
                    print(f"  ✅ {relative_path} ({file_size} байт)")
        else:
            print("⚠️ ЭТАП 2 ЗАВЕРШЕН С ОШИБКАМИ")
            print("🔍 Проверьте отчет stage2_core_creation_summary.json")
            print("🔄 Исправьте ошибки и повторите запуск")
        
        return success
        
    except ImportError as e:
        print(f"❌ Ошибка импорта stage2_runner: {e}")
        print("🔍 Убедитесь что файл stage2_runner.py синтаксически корректен")
        return False
    
    except Exception as e:
        print(f"💥 Неожиданная ошибка: {e}")
        print("🔍 Проверьте логи для детальной информации")
        return False


def show_help():
    """📚 Показать справку"""
    print("🚀 ЗАПУСКАТЕЛЬ ЭТАПА 2 - СОЗДАНИЕ ЯДРА АРХИТЕКТУРЫ")
    print("=" * 60)
    print("📋 Описание:")
    print("  Этот скрипт запускает процесс создания ядра новой архитектуры")
    print("  торговой системы. Создаются основные компоненты Core слоя.")
    print()
    print("🎯 Что создается:")
    print("  • src/core/interfaces.py - Основные интерфейсы системы")
    print("  • src/core/models.py - Базовые модели данных")
    print("  • src/core/exceptions.py - Система исключений")
    print("  • src/core/events.py - Система событий")
    print("  • src/core/di_container.py - Dependency Injection")
    print("  • src/config/settings.py - Система конфигурации")
    print()
    print("📝 Использование:")
    print("  python run_stage2.py           # Обычный запуск")
    print("  python run_stage2.py --help    # Показать эту справку")
    print("  python run_stage2.py --check   # Проверка готовности")
    print()
    print("📊 После выполнения:")
    print("  • Будет создана папка src/ с новой архитектурой")
    print("  • Сгенерирован отчет stage2_core_creation_summary.json")
    print("  • Система готова к Этапу 3: Domain слой")


def check_prerequisites():
    """🔍 Проверка готовности к запуску этапа 2"""
    print("🔍 ПРОВЕРКА ГОТОВНОСТИ К ЭТАПУ 2")
    print("=" * 40)
    
    checks = []
    
    # 1. Проверка Python версии
    python_version = sys.version_info
    if python_version >= (3, 8):
        checks.append(("✅", f"Python {python_version.major}.{python_version.minor} (OK)"))
    else:
        checks.append(("❌", f"Python {python_version.major}.{python_version.minor} (требуется >= 3.8)"))
    
    # 2. Проверка stage2_runner.py
    runner_file = Path("stage2_runner.py")
    if runner_file.exists():
        checks.append(("✅", "stage2_runner.py найден"))
        
        # Проверяем синтаксис
        try:
            with open(runner_file, 'r', encoding='utf-8') as f:
                content = f.read()
            compile(content, str(runner_file), 'exec')
            checks.append(("✅", "stage2_runner.py синтаксически корректен"))
        except SyntaxError as e:
            checks.append(("❌", f"stage2_runner.py имеет синтаксические ошибки: {e}"))
    else:
        checks.append(("❌", "stage2_runner.py не найден"))
    
    # 3. Проверка директорий
    current_dir = Path(".")
    if current_dir.is_dir() and os.access(current_dir, os.W_OK):
        checks.append(("✅", "Директория доступна для записи"))
    else:
        checks.append(("❌", "Нет прав на запись в текущую директорию"))
    
    # 4. Проверка существующих файлов Core
    core_files_exist = False
    src_path = Path("src")
    if src_path.exists():
        core_path = src_path / "core"
        if core_path.exists():
            core_files = list(core_path.glob("*.py"))
            if core_files:
                checks.append(("⚠️", f"Существующие Core файлы: {len(core_files)} (будут проверены)"))
                core_files_exist = True
    
    if not core_files_exist:
        checks.append(("ℹ️", "Core файлы будут созданы с нуля"))
    
    # 5. Проверка дискового пространства
    try:
        import shutil
        disk_usage = shutil.disk_usage(".")
        free_gb = disk_usage.free / (1024**3)
        if free_gb >= 0.1:  # 100MB должно хватить
            checks.append(("✅", f"Свободного места: {free_gb:.1f} ГБ"))
        else:
            checks.append(("⚠️", f"Мало свободного места: {free_gb:.1f} ГБ"))
    except Exception:
        checks.append(("⚠️", "Не удалось проверить дисковое пространство"))
    
    # Выводим результаты
    for status, message in checks:
        print(f"  {status} {message}")
    
    # Подсчитываем готовность
    success_count = sum(1 for status, _ in checks if status == "✅")
    warning_count = sum(1 for status, _ in checks if status == "⚠️")
    error_count = sum(1 for status, _ in checks if status == "❌")
    
    print(f"\n📊 РЕЗУЛЬТАТ ПРОВЕРКИ:")
    print(f"  ✅ Успешно: {success_count}")
    print(f"  ⚠️ Предупреждения: {warning_count}")
    print(f"  ❌ Ошибки: {error_count}")
    
    ready = error_count == 0
    if ready:
        print(f"  🎯 Готовность: ✅ ГОТОВ К ЗАПУСКУ")
    else:
        print(f"  🎯 Готовность: ❌ ТРЕБУЕТ ИСПРАВЛЕНИЯ")
        print(f"\n🔧 Исправьте ошибки перед запуском этапа 2")
    
    return ready


def show_status():
    """📊 Показать статус текущего этапа"""
    print("📊 СТАТУС ЭТАПА 2")
    print("=" * 30)
    
    # Проверяем отчет предыдущего запуска
    report_file = Path("stage2_core_creation_summary.json")
    if report_file.exists():
        try:
            import json
            with open(report_file, 'r', encoding='utf-8') as f:
                report = json.load(f)
            
            print(f"📄 Найден отчет предыдущего запуска:")
            print(f"  🕐 Время: {report.get('timestamp', 'неизвестно')}")
            print(f"  ⏱️ Длительность: {report.get('execution_time_minutes', 0)} мин")
            print(f"  📊 Статус: {'✅ УСПЕШНО' if report.get('overall_success', False) else '❌ С ОШИБКАМИ'}")
            
            if 'statistics' in report:
                stats = report['statistics']
                print(f"  📁 Файлов создано: {stats.get('total_core_files', 0)}")
                print(f"  📏 Размер кода: {stats.get('total_code_size', 0)} символов")
                print(f"  📈 Успешность: {stats.get('success_rate', 0):.1f}%")
            
            # Показываем статус компонентов
            if 'results' in report:
                print(f"\n📋 Статус компонентов:")
                for component, result in report['results'].items():
                    if isinstance(result, dict):
                        status = "✅" if result.get('success', False) else "❌"
                        coverage = result.get('coverage_percent', 0)
                        coverage_str = f" ({coverage:.0f}%)" if coverage > 0 else ""
                        print(f"    {status} {component}{coverage_str}")
            
        except Exception as e:
            print(f"⚠️ Ошибка чтения отчета: {e}")
    else:
        print("📄 Отчет предыдущего запуска не найден")
    
    # Проверяем текущее состояние файлов
    src_path = Path("src")
    if src_path.exists():
        print(f"\n📁 Текущие файлы Core:")
        core_files = [
            "core/interfaces.py",
            "core/models.py", 
            "core/exceptions.py",
            "core/events.py",
            "core/di_container.py",
            "config/settings.py"
        ]
        
        for file_path in core_files:
            full_path = src_path / file_path
            if full_path.exists():
                size = full_path.stat().st_size
                print(f"    ✅ {file_path} ({size} байт)")
            else:
                print(f"    ❌ {file_path} (отсутствует)")
    else:
        print(f"\n📁 Папка src/ не существует")


if __name__ == "__main__":
    # Парсим аргументы командной строки
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        
        if arg in ['--help', '-h', 'help']:
            show_help()
            sys.exit(0)
        elif arg in ['--check', '-c', 'check']:
            ready = check_prerequisites()
            sys.exit(0 if ready else 1)
        elif arg in ['--status', '-s', 'status']:
            show_status()
            sys.exit(0)
        else:
            print(f"❌ Неизвестный аргумент: {arg}")
            print("📚 Используйте --help для справки")
            sys.exit(1)
    
    # Обычный запуск
    try:
        # Быстрая проверка готовности
        print("🔍 Быстрая проверка готовности...")
        ready = check_prerequisites()
        
        if not ready:
            print("\n❌ Система не готова к запуску")
            print("🔧 Запустите 'python run_stage2.py --check' для детальной диагностики")
            sys.exit(1)
        
        print("✅ Проверка пройдена, запускаем этап 2...\n")
        
        # Запускаем основную функцию
        success = main()
        
        if success:
            print(f"\n🎉 ЭТАП 2 ЗАВЕРШЕН УСПЕШНО!")
            print(f"📋 Для просмотра деталей: python run_stage2.py --status")
            print(f"🚀 Следующий шаг: запуск Этапа 3 (Domain слой)")
            sys.exit(0)
        else:
            print(f"\n❌ ЭТАП 2 ЗАВЕРШЕН С ОШИБКАМИ")
            print(f"🔍 Изучите отчет stage2_core_creation_summary.json")
            print(f"🔄 Исправьте ошибки и повторите запуск")
            sys.exit(1)
    
    except KeyboardInterrupt:
        print(f"\n⌨️ Выполнение прервано пользователем")
        sys.exit(130)  # Стандартный код для Ctrl+C
    
    except Exception as e:
        print(f"\n💥 Критическая ошибка запуска: {e}")
        print(f"🔍 Проверьте файл stage2_runner.py и попробуйте снова")
        sys.exit(1)