#!/usr/bin/env python3
"""🚀 Точка входа для гибридного торгового бота"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("🚀 ЗАПУСК ГИБРИДНОГО ТОРГОВОГО БОТА DOGE")
    print("=" * 60)

    try:
        from hybrid_bot import HybridTradingBot

        print("✅ Гибридный бот загружен успешно")
        print("🔧 Доступные улучшения:")
        print("   🚨 Система аварийного выхода")
        print("   🛡️ Ограничитель DCA покупок")
        print("   📊 Гибридная аналитика") 
        print("   ⚡ Продвинутый rate limiting")
        print("=" * 60)

        bot = HybridTradingBot()
        bot.run()

    except ImportError as e:
        print(f"❌ Ошибка импорта гибридного бота: {e}")
        print("🔄 Попытка запуска базового бота...")

        try:
            from bot import TradingBot
            print("✅ Базовый бот загружен")
            bot = TradingBot()
            bot.run()
        except ImportError as e2:
            print(f"❌ Ошибка импорта базового бота: {e2}")
            print("💡 Убедитесь что все файлы на месте")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n⌨️ Остановка по запросу пользователя")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
