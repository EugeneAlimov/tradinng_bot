import sys
import os

# Добавляем путь к исходникам
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

if __name__ == "__main__":
    print("🚀 ТОРГОВЫЙ БОТ DOGE")
    print("=" * 30)
    
    try:
        from bot import TradingBot
        bot = TradingBot()
        bot.run()
    except KeyboardInterrupt:
        print("\n⌨️ Остановка по запросу пользователя")
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        print("💡 Убедитесь что все файлы на месте в директории src/")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
