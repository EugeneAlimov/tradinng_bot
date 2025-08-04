#!/usr/bin/env python3
"""🚀 Главная точка входа торгового бота v4.1-refactored"""

import sys
import os
import argparse
from pathlib import Path

# Добавляем src в путь
sys.path.insert(0, str(Path(__file__).parent / "src"))

def main():
    parser = argparse.ArgumentParser(description="Торговый бот DOGE v4.1-refactored")
    parser.add_argument("--mode", choices=["hybrid", "legacy", "new"], 
                       default="hybrid", help="Режим работы")
    parser.add_argument("--validate", action="store_true", help="Проверка конфигурации")
    
    args = parser.parse_args()
    
    print("🚀 ТОРГОВЫЙ БОТ DOGE v4.1-refactored")
    print("=" * 40)
    
    if args.validate:
        print("✅ Проверка конфигурации...")
        try:
            from config.settings import get_settings
            settings = get_settings()
            settings.validate()
            print("✅ Конфигурация валидна")
            return
        except Exception as e:
            print(f"❌ Ошибка конфигурации: {e}")
            sys.exit(1)
    
    if args.mode == "legacy":
        print("🔄 Запуск в legacy режиме...")
        try:
            # Попытка запуска старого бота
            if os.path.exists("main_old.py"):
                exec(open("main_old.py").read())
            else:
                print("❌ Legacy файлы не найдены")
        except Exception as e:
            print(f"❌ Ошибка legacy режима: {e}")
    
    elif args.mode == "hybrid":
        print("🔧 Запуск в гибридном режиме...")
        try:
            # Здесь будет импорт гибридного бота
            print("⚠️ Гибридный режим в разработке")
            print("💡 Используйте --mode legacy для старого бота")
        except Exception as e:
            print(f"❌ Ошибка гибридного режима: {e}")
    
    elif args.mode == "new":
        print("🆕 Запуск новой архитектуры...")
        try:
            # Здесь будет импорт нового бота
            print("⚠️ Новая архитектура в разработке")
            print("💡 Используйте --mode legacy для старого бота")
        except Exception as e:
            print(f"❌ Ошибка новой архитектуры: {e}")

if __name__ == "__main__":
    main()
