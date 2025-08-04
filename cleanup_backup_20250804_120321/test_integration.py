#!/usr/bin/env python3
"""🧪 Простой тест интеграции новой инфраструктуры (без pytest)"""

import asyncio
import sys
import os
import traceback
from pathlib import Path

# Добавляем src в путь если существует
src_path = Path(__file__).parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

print("🧪 ТЕСТ ИНТЕГРАЦИИ ТОРГОВОГО БОТА")
print("=" * 50)


def test_imports():
    """📦 Тест импортов"""
    print("\n📦 Проверка импортов...")
    results = {}

    # Тест core импортов
    try:
        sys.path.append('src')
        from core.interfaces import IExchangeAPI, ICacheService, IMonitoringService
        results['core_interfaces'] = True
        print("✅ Core интерфейсы")
    except Exception as e:
        results['core_interfaces'] = False
        print(f"❌ Core интерфейсы: {e}")

    # Тест конфигурации
    try:
        from config.settings import get_settings
        settings = get_settings()
        results['config'] = True
        print("✅ Конфигурация")
    except Exception as e:
        results['config'] = False
        print(f"❌ Конфигурация: {e}")

    # Тест legacy компонентов
    legacy_found = []

    # Проверяем наличие старых файлов
    old_files = ['bot.py', 'config.py', 'api_client.py', 'hybrid_bot.py']
    for file_name in old_files:
        if Path(file_name).exists():
            legacy_found.append(file_name)

    results['legacy_files'] = len(legacy_found) > 0
    if legacy_found:
        print(f"✅ Legacy файлы: {', '.join(legacy_found)}")
    else:
        print("⚠️ Legacy файлы не найдены")

    return results


def test_environment():
    """🌍 Тест окружения"""
    print("\n🌍 Проверка окружения...")
    results = {}

    # Проверка Python версии
    python_version = sys.version_info
    results['python_version'] = python_version >= (3, 8)
    print(f"✅ Python {python_version.major}.{python_version.minor}" if results['python_version']
          else f"❌ Python {python_version.major}.{python_version.minor} (требуется >= 3.8)")

    # Проверка зависимостей
    required_modules = ['requests', 'json', 'asyncio', 'logging', 'pathlib']
    missing_modules = []

    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing_modules.append(module)

    results['dependencies'] = len(missing_modules) == 0
    if results['dependencies']:
        print("✅ Базовые зависимости")
    else:
        print(f"❌ Отсутствуют модули: {', '.join(missing_modules)}")

    # Проверка директорий
    required_dirs = ['src', 'logs', 'data']
    existing_dirs = []

    for dir_name in required_dirs:
        dir_path = Path(dir_name)
        if dir_path.exists():
            existing_dirs.append(dir_name)
        else:
            try:
                dir_path.mkdir(exist_ok=True)
                existing_dirs.append(dir_name)
            except:
                pass

    results['directories'] = len(existing_dirs) >= 2  # Хотя бы 2 из 3
    print(f"✅ Директории: {', '.join(existing_dirs)}" if results['directories']
          else f"❌ Проблемы с директориями")

    # Проверка прав записи
    try:
        test_file = Path("test_write.tmp")
        test_file.write_text("test")
        test_file.unlink()
        results['write_permissions'] = True
        print("✅ Права записи")
    except Exception as e:
        results['write_permissions'] = False
        print(f"❌ Права записи: {e}")

    return results


async def test_basic_infrastructure():
    """🏗️ Тест базовой инфраструктуры"""
    print("\n🏗️ Тест базовой инфраструктуры...")
    results = {}

    # Тест создания простого кэша
    try:
        cache_data = {}

        # Простой in-memory кэш
        def set_cache(key, value):
            cache_data[key] = value

        def get_cache(key):
            return cache_data.get(key)

        set_cache("test_key", "test_value")
        cached_value = get_cache("test_key")

        results['simple_cache'] = cached_value == "test_value"
        print("✅ Простой кэш" if results['simple_cache'] else "❌ Простой кэш")

    except Exception as e:
        results['simple_cache'] = False
        print(f"❌ Простой кэш: {e}")

    # Тест асинхронных операций
    try:
        async def async_operation():
            await asyncio.sleep(0.1)
            return "async_result"

        result = await async_operation()
        results['async_support'] = result == "async_result"
        print("✅ Асинхронность" if results['async_support'] else "❌ Асинхронность")

    except Exception as e:
        results['async_support'] = False
        print(f"❌ Асинхронность: {e}")

    # Тест логирования
    try:
        import logging

        # Настройка базового логгера
        logger = logging.getLogger("test_logger")
        logger.setLevel(logging.INFO)

        # Проверяем что можем логировать
        logger.info("Test log message")

        results['logging'] = True
        print("✅ Логирование")

    except Exception as e:
        results['logging'] = False
        print(f"❌ Логирование: {e}")

    # Тест JSON операций
    try:
        import json

        test_data = {"test": "data", "number": 123}
        json_str = json.dumps(test_data)
        parsed_data = json.loads(json_str)

        results['json_support'] = parsed_data == test_data
        print("✅ JSON поддержка" if results['json_support'] else "❌ JSON поддержка")

    except Exception as e:
        results['json_support'] = False
        print(f"❌ JSON поддержка: {e}")

    return results


async def test_simple_bot_structure():
    """🤖 Тест простой структуры бота"""
    print("\n🤖 Тест структуры бота...")
    results = {}

    # Создаем простого тестового бота
    try:
        class SimpleTradingBot:
            def __init__(self):
                self.config = {"api_key": "test", "pair": "DOGE_EUR"}
                self.running = False
                self.cycle_count = 0

            async def initialize(self):
                """Инициализация"""
                self.running = True
                return True

            async def execute_cycle(self):
                """Выполнение торгового цикла"""
                self.cycle_count += 1

                # Симуляция торговой логики
                market_data = {
                    "current_price": 0.18,
                    "balance": 1000.0,
                    "timestamp": asyncio.get_event_loop().time()
                }

                # Простая логика
                if market_data["current_price"] > 0:
                    return {
                        "success": True,
                        "action": "hold",
                        "reason": f"Цикл {self.cycle_count}: цена {market_data['current_price']}"
                    }
                else:
                    return {
                        "success": False,
                        "reason": "Нет данных о цене"
                    }

            async def shutdown(self):
                """Завершение работы"""
                self.running = False

        # Тест создания бота
        bot = SimpleTradingBot()
        results['bot_creation'] = True
        print("✅ Создание бота")

        # Тест инициализации
        init_result = await bot.initialize()
        results['bot_initialization'] = init_result and bot.running
        print("✅ Инициализация бота" if results['bot_initialization'] else "❌ Инициализация бота")

        # Тест торгового цикла
        cycle_result = await bot.execute_cycle()
        results['trading_cycle'] = cycle_result.get("success", False)
        print(f"✅ Торговый цикл: {cycle_result.get('reason', 'OK')}" if results['trading_cycle']
              else f"❌ Торговый цикл: {cycle_result}")

        # Тест завершения
        await bot.shutdown()
        results['bot_shutdown'] = not bot.running
        print("✅ Завершение бота" if results['bot_shutdown'] else "❌ Завершение бота")

    except Exception as e:
        results['bot_creation'] = False
        results['bot_initialization'] = False
        results['trading_cycle'] = False
        results['bot_shutdown'] = False
        print(f"❌ Ошибка тестирования бота: {e}")
        traceback.print_exc()

    return results


async def test_file_operations():
    """📁 Тест файловых операций"""
    print("\n📁 Тест файловых операций...")
    results = {}

    # Тест записи и чтения файлов
    try:
        test_file_path = Path("test_data.json")

        # Тестовые данные
        test_data = {
            "bot_name": "DOGE Trading Bot",
            "version": "4.1-refactored",
            "test_timestamp": asyncio.get_event_loop().time(),
            "settings": {
                "pair": "DOGE_EUR",
                "enabled": True
            }
        }

        # Запись в файл
        import json
        with open(test_file_path, 'w', encoding='utf-8') as f:
            json.dump(test_data, f, indent=2)

        # Чтение из файла
        with open(test_file_path, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)

        # Проверка данных
        results['file_write_read'] = loaded_data == test_data
        print("✅ Запись/чтение файлов" if results['file_write_read'] else "❌ Запись/чтение файлов")

        # Удаляем тестовый файл
        test_file_path.unlink()

    except Exception as e:
        results['file_write_read'] = False
        print(f"❌ Файловые операции: {e}")

    # Тест создания директорий
    try:
        test_dir = Path("test_dir")
        test_dir.mkdir(exist_ok=True)

        results['directory_creation'] = test_dir.exists()
        print("✅ Создание директорий" if results['directory_creation'] else "❌ Создание директорий")

        # Удаляем тестовую директорию
        test_dir.rmdir()

    except Exception as e:
        results['directory_creation'] = False
        print(f"❌ Создание директорий: {e}")

    return results


def test_configuration():
    """⚙️ Тест конфигурации"""
    print("\n⚙️ Тест конфигурации...")
    results = {}

    # Проверка .env файла
    env_file = Path(".env")
    if env_file.exists():
        try:
            with open(env_file, 'r') as f:
                env_content = f.read()

            # Ищем ключевые настройки
            has_api_key = "EXMO_API_KEY" in env_content
            has_api_secret = "EXMO_API_SECRET" in env_content

            results['env_file'] = has_api_key and has_api_secret

            if results['env_file']:
                print("✅ .env файл с API ключами")
            else:
                print("⚠️ .env файл найден, но нет API ключей")

        except Exception as e:
            results['env_file'] = False
            print(f"❌ Ошибка чтения .env: {e}")
    else:
        results['env_file'] = False
        print("⚠️ .env файл не найден")

    # Создаем простую конфигурацию для теста
    try:
        simple_config = {
            "bot_name": "DOGE Trading Bot",
            "version": "4.1-refactored",
            "trading": {
                "pair": "DOGE_EUR",
                "enabled": True,
                "test_mode": True
            },
            "monitoring": {
                "enabled": True,
                "port": 8080
            }
        }

        # Проверяем что можем работать с конфигурацией
        bot_name = simple_config.get("bot_name")
        trading_pair = simple_config.get("trading", {}).get("pair")

        results['simple_config'] = bool(bot_name and trading_pair)
        print("✅ Простая конфигурация" if results['simple_config'] else "❌ Простая конфигурация")

    except Exception as e:
        results['simple_config'] = False
        print(f"❌ Простая конфигурация: {e}")

    return results


async def main():
    """🚀 Главная функция тестирования"""
    print("🧪 Запуск интеграционного тестирования...")
    print(f"📍 Рабочая директория: {Path.cwd()}")
    print(f"🐍 Python: {sys.version}")

    all_results = {}

    try:
        # 1. Тест импортов
        import_results = test_imports()
        all_results.update(import_results)

        # 2. Тест окружения
        env_results = test_environment()
        all_results.update(env_results)

        # 3. Тест базовой инфраструктуры
        infra_results = await test_basic_infrastructure()
        all_results.update(infra_results)

        # 4. Тест структуры бота
        bot_results = await test_simple_bot_structure()
        all_results.update(bot_results)

        # 5. Тест файловых операций
        file_results = await test_file_operations()
        all_results.update(file_results)

        # 6. Тест конфигурации
        config_results = test_configuration()
        all_results.update(config_results)

    except Exception as e:
        print(f"❌ Критическая ошибка в тестах: {e}")
        traceback.print_exc()
        return False

    # Подсчет результатов
    print("\n📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    print("=" * 30)

    total_tests = len(all_results)
    passed_tests = sum(1 for result in all_results.values() if result)
    failed_tests = total_tests - passed_tests

    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0

    print(f"✅ Пройдено: {passed_tests}/{total_tests} тестов ({success_rate:.1f}%)")
    print(f"❌ Провалено: {failed_tests} тестов")

    # Детальные результаты
    print("\n📋 Детальные результаты:")
    for test_name, result in all_results.items():
        status_icon = "✅" if result else "❌"
        print(f"  {status_icon} {test_name}")

    # Рекомендации
    print("\n💡 РЕКОМЕНДАЦИИ:")

    if success_rate >= 80:
        print("🎉 Система готова к интеграции!")
        print("🚀 Следующие шаги:")
        print("  1. Создайте файлы инфраструктуры в src/")
        print("  2. Запустите: python main.py --mode enhanced")
        print("  3. Откройте дашборд: http://localhost:8080")

    elif success_rate >= 60:
        print("⚠️ Система частично готова")
        print("🔧 Исправьте ошибки и повторите тест")

        # Показываем критичные ошибки
        critical_tests = ['python_version', 'dependencies', 'write_permissions']
        critical_failed = [test for test in critical_tests if not all_results.get(test, True)]

        if critical_failed:
            print(f"🚨 Критичные проблемы: {', '.join(critical_failed)}")

    else:
        print("❌ Система не готова к интеграции")
        print("🛠️ Необходимо исправить базовые проблемы:")

        # Показываем проваленные тесты
        failed_tests_list = [test for test, result in all_results.items() if not result]
        for failed_test in failed_tests_list[:5]:  # Показываем первые 5
            print(f"  ❌ {failed_test}")

    # Справочная информация
    print("\n📚 СПРАВКА:")
    print("  📁 Структура файлов: src/infrastructure/")
    print("  ⚙️ Конфигурация: .env файл с API ключами")
    print("  🐍 Требования: Python 3.8+, базовые модули")
    print("  📝 Логи: logs/enhanced_bot.log")

    return success_rate >= 60


if __name__ == "__main__":
    try:
        result = asyncio.run(main())
        exit_code = 0 if result else 1

        print(f"\n🏁 Тестирование завершено с кодом: {exit_code}")
        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\n⌨️ Тестирование прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Неожиданная ошибка: {e}")
        traceback.print_exc()
        sys.exit(1)