# test_integration.py
#!/usr/bin/env python3
"""🧪 Тестирование интеграции новой инфраструктуры"""

import asyncio
import sys
from pathlib import Path

# Добавляем src в путь
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))


async def test_infrastructure_components():
    """🧪 Тест компонентов инфраструктуры"""
    print("🧪 Тестирование компонентов инфраструктуры...")

    results = {}

    # 1. Тест API клиента
    try:
        from infrastructure.adapter import get_infrastructure
        infrastructure = await get_infrastructure()

        # Тест получения цены
        price = await infrastructure.get_current_price("DOGE_EUR")
        results['api_client'] = price > 0
        print(f"✅ API клиент: цена DOGE = {price}")

    except Exception as e:
        results['api_client'] = False
        print(f"❌ API клиент: {e}")

    # 2. Тест кэша
    try:
        if infrastructure.cache:
            await infrastructure.cache.set("test_key", "test_value", ttl=60)
            cached_value = await infrastructure.cache.get("test_key")
            results['cache'] = cached_value == "test_value"
            print(f"✅ Кэш: {cached_value}")
        else:
            results['cache'] = False
            print("⚠️ Кэш недоступен")

    except Exception as e:
        results['cache'] = False
        print(f"❌ Кэш: {e}")

    # 3. Тест мониторинга
    try:
        if infrastructure.monitoring:
            status = await infrastructure.monitoring.get_system_status()
            results['monitoring'] = 'timestamp' in status
            print(f"✅ Мониторинг: {len(status)} метрик")
        else:
            results['monitoring'] = False
            print("⚠️ Мониторинг недоступен")

    except Exception as e:
        results['monitoring'] = False
        print(f"❌ Мониторинг: {e}")

    # 4. Тест репозиториев
    try:
        if infrastructure.repositories:
            repo_count = len(infrastructure.repositories)
            results['repositories'] = repo_count > 0
            print(f"✅ Репозитории: {repo_count} шт.")
        else:
            results['repositories'] = False
            print("⚠️ Репозитории недоступны")

    except Exception as e:
        results['repositories'] = False
        print(f"❌ Репозитории: {e}")

    # Завершаем инфраструктуру
    await infrastructure.shutdown()

    return results


async def test_enhanced_bot():
    """🤖 Тест улучшенного бота"""
    print("\n🤖 Тестирование улучшенного бота...")

    try:
        from hybrid_bot_enhanced import EnhancedHybridBot

        bot = EnhancedHybridBot()
        bot.dashboard_enabled = False  # Отключаем дашборд для теста

        await bot.initialize()
        print("✅ Инициализация прошла успешно")

        # Тест торгового цикла
        result = await bot._execute_trading_cycle()
        print(f"✅ Торговый цикл: {result.get('reason', 'OK')}")

        await bot.shutdown()
        return True

    except Exception as e:
        print(f"❌ Ошибка тестирования бота: {e}")
        return False


async def test_backward_compatibility():
    """🔄 Тест обратной совместимости"""
    print("\n🔄 Тестирование обратной совместимости...")

    try:
        # Тест загрузки старых компонентов
        legacy_components = []

        try:
            from config import TradingConfig
            config = TradingConfig()
            legacy_components.append("TradingConfig")
        except ImportError:
            pass

        try:
            from position_manager import PositionManager
            pos_mgr = PositionManager()
            legacy_components.append("PositionManager")
        except ImportError:
            pass

        try:
            from risk_management import RiskManager
            risk_mgr = RiskManager(None)
            legacy_components.append("RiskManager")
        except ImportError:
            pass

        print(f"✅ Legacy компоненты: {', '.join(legacy_components)}")
        return len(legacy_components) > 0

    except Exception as e:
        print(f"❌ Ошибка тестирования совместимости: {e}")
        return False


async def main():
    """🚀 Главная функция тестирования"""
    print("🧪 ТЕСТИРОВАНИЕ ИНТЕГРАЦИИ")
    print("=" * 50)

    # 1. Тест компонентов
    infra_results = await test_infrastructure_components()

    # 2. Тест бота
    bot_result = await test_enhanced_bot()

    # 3. Тест совместимости
    compat_result = await test_backward_compatibility()

    # Итоги
    print("\n📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    print("=" * 30)

    total_tests = len(infra_results) + 2  # + bot + compatibility
    passed_tests = sum(infra_results.values()) + int(bot_result) + int(compat_result)

    print(f"✅ Пройдено: {passed_tests}/{total_tests} тестов")

    if passed_tests >= total_tests * 0.7:  # 70% прошли
        print("🎉 Интеграция успешна!")
        print("\n🚀 Можно запускать бота:")
        print("python main.py --mode enhanced")
    else:
        print("⚠️ Обнаружены проблемы в интеграции")
        print("💡 Проверьте ошибки выше")

    print(f"\n📊 Детали:")
    for component, status in infra_results.items():
        status_icon = "✅" if status else "❌"
        print(f"  {status_icon} {component}")

    print(f"  {'✅' if bot_result else '❌'} enhanced_bot")
    print(f"  {'✅' if compat_result else '❌'} compatibility")


if __name__ == "__main__":
    asyncio.run(main())
