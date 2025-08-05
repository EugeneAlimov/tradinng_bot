import shutil
import sys
from pathlib import Path
from datetime import datetime
import argparse

def list_backups():
    """Список доступных бэкапов"""
    backup_dir = Path("backup_before_migration")
    if not backup_dir.exists():
        print("❌ Директория бэкапов не найдена")
        return []
    
    backups = []
    for item in backup_dir.iterdir():
        if item.is_file() and item.suffix == '.py':
            backups.append(item)
    
    return sorted(backups)

def restore_file(backup_file, target_file=None):
    """Восстановление файла из бэкапа"""
    if not backup_file.exists():
        print(f"❌ Бэкап файл не найден: {backup_file}")
        return False
    
    if target_file is None:
        # Убираем _old из имени
        target_name = backup_file.name.replace('_old', '')
        target_file = Path(target_name)
    
    try:
        # Создаем бэкап текущего файла
        if target_file.exists():
            backup_name = f"{target_file.name}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(target_file, backup_name)
            print(f"📦 Создан бэкап: {backup_name}")
        
        # Восстанавливаем из бэкапа
        shutil.copy2(backup_file, target_file)
        print(f"✅ Восстановлен: {target_file}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка восстановления {backup_file}: {e}")
        return False

def restore_main_files():
    """Восстановление основных файлов"""
    backup_dir = Path("backup_before_migration")
    
    # Основные файлы для восстановления
    restore_map = {
        "main_old.py": "main.py",
        "config_old.py": "config.py",
        "bot_old.py": "bot.py"
    }
    
    restored = 0
    total = len(restore_map)
    
    for backup_name, target_name in restore_map.items():
        backup_file = backup_dir / backup_name
        target_file = Path(target_name)
        
        if backup_file.exists() and restore_file(backup_file, target_file):
            restored += 1
    
    print(f"\n📊 Восстановлено {restored}/{total} файлов")
    
    if restored > 0:
        print("🎉 Восстановление завершено!")
        print("\n🔧 Следующие шаги:")
        print("  1. Проверьте конфигурацию: python main.py --validate")
        print("  2. Запустите в тестовом режиме: python main.py --mode paper")
        return True
    else:
        print("⚠️ Файлы для восстановления не найдены")
        return False

def main():
    parser = argparse.ArgumentParser(description="Восстановление из бэкапа")
    parser.add_argument("--list", action="store_true", help="Показать список бэкапов")
    parser.add_argument("--restore-main", action="store_true", help="Восстановить основные файлы")
    
    args = parser.parse_args()
    
    if args.list:
        print("📦 Доступные бэкапы:")
        backups = list_backups()
        for backup in backups:
            print(f"  • {backup.name}")
        return 0
    
    if args.restore_main:
        print("🔄 Восстановление основных файлов...")
        success = restore_main_files()
        return 0 if success else 1
    
    # Интерактивный режим
    print("🔄 ВОССТАНОВЛЕНИЕ ИЗ БЭКАПА")
    print("=" * 30)
    print("1. Восстановить основные файлы")
    print("2. Показать список бэкапов")
    print("3. Выход")
    
    try:
        choice = input("\nВыберите действие (1-3): ")
        
        if choice == "1":
            return 0 if restore_main_files() else 1
        elif choice == "2":
            backups = list_backups()
            for backup in backups:
                print(f"  • {backup.name}")
            return 0
        else:
            print("Выход")
            return 0
            
    except KeyboardInterrupt:
        print("\n❌ Операция отменена")
        return 1

if __name__ == "__main__":
    sys.exit(main())
