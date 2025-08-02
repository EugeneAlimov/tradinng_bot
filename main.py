#!/usr/bin/env python3
"""🚀 Новая точка входа торговой системы"""

import sys
import os
import argparse
import asyncio
from pathlib import Path

# Добавляем src в путь
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

def parse_arguments():
    """📋 Парсинг аргументов командной строки"""
    parser = argparse.ArgumentParser(description="🤖 DOGE Trading Bot v4.1-refactored")

    parser.add_argument(
        '--mode', '-m',
        choices=['new', 'legacy', 'hybrid'],
        default='hybrid',
        help='Режим работы: new (новая архитектура), legacy (старый бот), hybrid (адаптер)'
    )

    parser.add_argument(
        '--profile', '-p',
        choices=['conservative', 'balanced', 'aggressive'],
        default='balanced',
        help='Профиль торговли'
    )

    parser.add_argument(
        '--config', '-c',
        help='Путь к файлу конфигурации'
    )

    parser.add_argument(
        '--validate', '-v',
        action='store_true',
        help='Только валидация конфигурации'
    )

    parser.add_argument(
        '--test-mode', '-t',
        action='store_true',
        help='Тестовый режим без реальных сделок'
    )

    return parser.parse_args()

async def run_new_architecture(args):
    """🆕 Запуск новой архитектуры"""
    print("🆕 Запуск новой архитектуры...")
    print("⚠️ Новая архитектура находится в разработке")
    print("🔄 Переключаемся на гибридный режим")
    return await run_hybrid_mode(args)

async def run_legacy_mode(args):
    """📜 Запуск старого бота"""
    print("📜 Запуск в legacy режиме...")

    try:
        # Пытаемся запустить старый бот
        if Path("hybrid_bot.py").exists():
            from hybrid_bot import HybridTradingBot
            bot = HybridTradingBot()
        elif Path("bot.py").exists():
            from bot import TradingBot
            bot = TradingBot()
        else:
            raise ImportError("Старые файлы бота не найдены")

        print("✅ Старый бот загружен, запускаем...")
        bot.run()

    except ImportError as e:
        print(f"❌ Ошибка загрузки старого бота: {e}")
        print("💡 Попробуйте режим --mode hybrid")
        return False
    except Exception as e:
        print(f"❌ Ошибка запуска: {e}")
        return False

    return True

async def run_hybrid_mode(args):
    """🎭 Запуск в гибридном режиме"""
    print("🎭 Запуск в гибридном режиме...")

    try:
        # Загружаем новую конфигурацию
        from config.settings import get_settings
        settings = get_settings()
        settings.validate()

        print("✅ Новая конфигурация загружена")

        # Загружаем адаптер
        from adapters import LegacyBotAdapter
        adapter = LegacyBotAdapter(use_hybrid=True)

        print("🔄 Запуск через адаптер...")

        # Простой цикл для демонстрации
        cycles = 0
        while cycles < 5:  # Ограничиваем для теста
            try:
                result = await adapter.run_trading_cycle()
                print(f"📊 Цикл {cycles + 1}: {result.get('reason', 'OK')}")

                cycles += 1
                await asyncio.sleep(10)  # 10 секунд между циклами

            except KeyboardInterrupt:
                print("\n⌨️ Остановка по Ctrl+C")
                break
            except Exception as e:
                print(f"❌ Ошибка цикла: {e}")
                break

        print("✅ Гибридный режим завершен")
        return True

    except Exception as e:
        print(f"❌ Ошибка гибридного режима: {e}")
        print("🔄 Пытаемся запустить legacy режим...")
        return await run_legacy_mode(args)

async def validate_configuration(args):
    """✅ Валидация конфигурации"""
    print("✅ Валидация конфигурации...")

    try:
        from config.settings import get_settings
        settings = get_settings()
        settings.validate()

        print("✅ Конфигурация корректна")
        print(f"📊 Профиль: {getattr(settings, 'profile_name', 'unknown')}")
        print(f"💱 API ключ: {settings.exmo_api_key[:8]}..." if settings.exmo_api_key else "❌ API ключ не настроен")

        return True

    except Exception as e:
        print(f"❌ Ошибка конфигурации: {e}")
        return False

async def main():
    """🚀 Главная функция"""
    print("🤖 DOGE TRADING BOT v4.1-refactored")
    print("=" * 50)

    args = parse_arguments()

    print(f"🎯 Режим: {args.mode}")
    print(f"📊 Профиль: {args.profile}")

    # Валидация конфигурации
    if args.validate:
        success = await validate_configuration(args)
        return 0 if success else 1

    # Запуск в выбранном режиме
    try:
        if args.mode == 'new':
            success = await run_new_architecture(args)
        elif args.mode == 'legacy':
            success = await run_legacy_mode(args)
        else:  # hybrid
            success = await run_hybrid_mode(args)

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n⌨️ Завершение по запросу пользователя")
        return 0
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
