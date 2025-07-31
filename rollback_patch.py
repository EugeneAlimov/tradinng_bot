#!/usr/bin/env python3
"""🔄 Скрипт отката патча"""

import os
import shutil

def rollback():
    backup_dir = "backup_20250730_194618"

    if not os.path.exists(backup_dir):
        print(f"❌ Бэкап {backup_dir} не найден")
        return

    files_to_restore = [
        "config.py",
        "adaptive_dca_strategy.py",
        "main.py",
        "bot.py",
        "improved_bot.py"
    ]

    restored = 0
    for filename in files_to_restore:
        backup_file = os.path.join(backup_dir, filename)
        if os.path.exists(backup_file):
            shutil.copy2(backup_file, filename)
            print(f"✅ Восстановлен: {filename}")
            restored += 1

    # Удаляем созданные файлы
    patch_files = [
        "smart_logger.py",
        "trend_analyzer.py",
        "partial_trading.py"
    ]

    for filename in patch_files:
        if os.path.exists(filename):
            os.remove(filename)
            print(f"🗑️ Удален: {filename}")

    print(f"\n✅ Откат завершен! Восстановлено {restored} файлов")

if __name__ == "__main__":
    rollback()
