#!/usr/bin/env python3
"""🎯 Менеджер для работы с историей сделок - быстрый доступ ко всем функциям"""

import os
import sys
import subprocess
import glob
from datetime import datetime


class TradesManager:
    """🎯 Менеджер истории сделок"""
    
    def __init__(self):
        self.data_dir = 'data'
        self.scripts = {
            'fetcher': 'trades_history_fetcher.py',
            'analyzer': 'trades_analyzer.py'
        }
        
        # Создаем директории если нужно
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs('logs', exist_ok=True)
    
    def show_menu(self):
        """📋 Главное меню"""
        print("\n🎯 МЕНЕДЖЕР ИСТОРИИ СДЕЛОК EXMO")
        print("=" * 50)
        print("1. 📊 Получить историю сделок с биржи")
        print("2. 📈 Анализировать существующие данные")
        print("3. 📂 Показать доступные файлы")
        print("4. 🧹 Очистка старых файлов")
        print("5. ℹ️  Информация о системе")
        print("0. 🚪 Выход")
        print("=" * 50)
    
    def fetch_trades(self):
        """📊 Запуск получения сделок"""
        print("\n📊 ПОЛУЧЕНИЕ ИСТОРИИ СДЕЛОК")
        print("-" * 30)
        
        if not os.path.exists(self.scripts['fetcher']):
            print(f"❌ Скрипт {self.scripts['fetcher']} не найден")
            return
        
        try:
            # Проверяем конфигурацию
            if not self._check_config():
                return
            
            print("🚀 Запуск получения истории сделок...")
            result = subprocess.run([sys.executable, self.scripts['fetcher']], 
                                  capture_output=False, text=True)
            
            if result.returncode == 0:
                print("✅ Получение сделок завершено успешно")
            else:
                print(f"❌ Ошибка выполнения (код: {result.returncode})")
                
        except Exception as e:
            print(f"❌ Ошибка запуска: {e}")
    
    def analyze_trades(self):
        """📈 Запуск анализа сделок"""
        print("\n📈 АНАЛИЗ ИСТОРИИ СДЕЛОК")
        print("-" * 30)
        
        if not os.path.exists(self.scripts['analyzer']):
            print(f"❌ Скрипт {self.scripts['analyzer']} не найден")
            return
        
        # Проверяем наличие файлов для анализа
        trade_files = self._find_trade_files()
        
        if not trade_files:
            print("❌ Файлы с историей сделок не найдены")
            print("💡 Сначала выполните получение истории (опция 1)")
            return
        
        try:
            print("🚀 Запуск анализа сделок...")
            result = subprocess.run([sys.executable, self.scripts['analyzer']], 
                                  capture_output=False, text=True)
            
            if result.returncode == 0:
                print("✅ Анализ завершен успешно")
            else:
                print(f"❌ Ошибка анализа (код: {result.returncode})")
                
        except Exception as e:
            print(f"❌ Ошибка запуска анализа: {e}")
    
    def show_files(self):
        """📂 Показать доступные файлы"""
        print("\n📂 ДОСТУПНЫЕ ФАЙЛЫ")
        print("-" * 30)
        
        # Файлы истории сделок
        trade_files = self._find_trade_files()
        print(f"📊 Файлы истории сделок ({len(trade_files)}):")
        
        if trade_files:
            for i, file in enumerate(trade_files, 1):
                file_size = os.path.getsize(file) / 1024  # KB
                mod_time = datetime.fromtimestamp(os.path.getmtime(file))
                print(f"   {i}. {os.path.basename(file)}")
                print(f"      Размер: {file_size:.1f} KB, изменен: {mod_time.strftime('%Y-%m-%d %H:%M')}")
        else:
            print("   Нет файлов")
        
        # Файлы анализа
        analysis_files = self._find_analysis_files()
        print(f"\n📈 Файлы анализа ({len(analysis_files)}):")
        
        if analysis_files:
            for i, file in enumerate(analysis_files, 1):
                file_size = os.path.getsize(file) / 1024  # KB
                mod_time = datetime.fromtimestamp(os.path.getmtime(file))
                print(f"   {i}. {os.path.basename(file)}")
                print(f"      Размер: {file_size:.1f} KB, изменен: {mod_time.strftime('%Y-%m-%d %H:%M')}")
        else:
            print("   Нет файлов анализа")
        
        # CSV файлы
        csv_files = glob.glob(os.path.join(self.data_dir, '*.csv'))
        if csv_files:
            print(f"\n📊 CSV файлы ({len(csv_files)}):")
            for i, file in enumerate(csv_files, 1):
                file_size = os.path.getsize(file) / 1024  # KB
                print(f"   {i}. {os.path.basename(file)} ({file_size:.1f} KB)")
    
    def cleanup_files(self):
        """🧹 Очистка старых файлов"""
        print("\n🧹 ОЧИСТКА СТАРЫХ ФАЙЛОВ")
        print("-" * 30)
        
        # Показываем что будем удалять
        all_files = []
        all_files.extend(self._find_trade_files())
        all_files.extend(self._find_analysis_files())
        all_files.extend(glob.glob(os.path.join(self.data_dir, '*.csv')))
        
        if not all_files:
            print("✅ Нет файлов для очистки")
            return
        
        print(f"📁 Найдено {len(all_files)} файлов:")
        
        # Группируем файлы по возрасту
        now = datetime.now()
        old_files = []  # > 30 дней
        recent_files = []  # <= 30 дней
        
        for file in all_files:
            mod_time = datetime.fromtimestamp(os.path.getmtime(file))
            age_days = (now - mod_time).days
            
            if age_days > 30:
                old_files.append((file, age_days))
            else:
                recent_files.append((file, age_days))
        
        print(f"📅 Свежие файлы (≤30 дней): {len(recent_files)}")
        print(f"🗂️ Старые файлы (>30 дней): {len(old_files)}")
        
        if old_files:
            print("\n🗑️ Старые файлы для удаления:")
            for file, age in old_files:
                file_size = os.path.getsize(file) / 1024
                print(f"   - {os.path.basename(file)} ({age} дней, {file_size:.1f} KB)")
            
            confirm = input(f"\n❓ Удалить {len(old_files)} старых файлов? (y/N): ").lower()
            
            if confirm == 'y':
                deleted = 0
                total_size = 0
                
                for file, age in old_files:
                    try:
                        file_size = os.path.getsize(file)
                        os.remove(file)
                        deleted += 1
                        total_size += file_size
                        print(f"🗑️ Удален: {os.path.basename(file)}")
                    except Exception as e:
                        print(f"❌ Ошибка удаления {file}: {e}")
                
                print(f"\n✅ Удалено {deleted} файлов, освобождено {total_size/1024:.1f} KB")
            else:
                print("❌ Очистка отменена")
        else:
            print("✅ Нет старых файлов для удаления")
    
    def show_system_info(self):
        """ℹ️ Информация о системе"""
        print("\nℹ️ ИНФОРМАЦИЯ О СИСТЕМЕ")
        print("-" * 30)
        
        # Проверяем наличие скриптов
        print("📄 Скрипты:")
        for name, script in self.scripts.items():
            status = "✅" if os.path.exists(script) else "❌"
            print(f"   {status} {script}")
        
        # Проверяем конфигурацию
        print("\n⚙️ Конфигурация:")
        config_status = "✅" if self._check_config_exists() else "❌"
        print(f"   {config_status} config.py")
        
        env_status = "✅" if os.path.exists('.env') else "❌"
        print(f"   {env_status} .env файл")
        
        # Проверяем директории
        print("\n📁 Директории:")
        data_status = "✅" if os.path.exists(self.data_dir) else "❌"
        print(f"   {data_status} {self.data_dir}/")
        
        logs_status = "✅" if os.path.exists('logs') else "❌"
        print(f"   {logs_status} logs/")
        
        # Статистика файлов
        trade_files = len(self._find_trade_files())
        analysis_files = len(self._find_analysis_files())
        
        print(f"\n📊 Статистика:")
        print(f"   Файлов истории: {trade_files}")
        print(f"   Файлов анализа: {analysis_files}")
        
        # Проверяем зависимости
        print(f"\n🐍 Python модули:")
        modules = ['requests', 'json', 'datetime', 'logging']
        
        for module in modules:
            try:
                __import__(module)
                print(f"   ✅ {module}")
            except ImportError:
                print(f"   ❌ {module}")
    
    def _find_trade_files(self):
        """🔍 Поиск файлов истории сделок"""
        pattern = os.path.join(self.data_dir, 'trades_history_*.json')
        files = glob.glob(pattern)
        return sorted(files, key=os.path.getmtime, reverse=True)
    
    def _find_analysis_files(self):
        """🔍 Поиск файлов анализа"""
        pattern = os.path.join(self.data_dir, 'trades_analysis_*.json')
        files = glob.glob(pattern)
        return sorted(files, key=os.path.getmtime, reverse=True)
    
    def _check_config_exists(self):
        """⚙️ Проверка наличия конфигурации"""
        return os.path.exists('config.py')
    
    def _check_config(self):
        """⚙️ Проверка корректности конфигурации"""
        if not self._check_config_exists():
            print("❌ Файл config.py не найден")
            return False
        
        try:
            # Пытаемся импортировать конфигурацию
            from config import TradingConfig
            config = TradingConfig()
            
            if not config.API_KEY or not config.API_SECRET:
                print("❌ API ключи не настроены в конфигурации")
                print("💡 Проверьте .env файл или config.py")
                return False
            
            print("✅ Конфигурация корректна")
            return True
            
        except ImportError as e:
            print(f"❌ Ошибка импорта конфигурации: {e}")
            return False
        except Exception as e:
            print(f"❌ Ошибка конфигурации: {e}")
            return False
    
    def run(self):
        """🚀 Главный цикл программы"""
        print("🎯 Добро пожаловать в менеджер истории сделок!")
        
        while True:
            try:
                self.show_menu()
                choice = input("\n👉 Выберите действие (0-5): ").strip()
                
                if choice == '0':
                    print("👋 До свидания!")
                    break
                elif choice == '1':
                    self.fetch_trades()
                elif choice == '2':
                    self.analyze_trades()
                elif choice == '3':
                    self.show_files()
                elif choice == '4':
                    self.cleanup_files()
                elif choice == '5':
                    self.show_system_info()
                else:
                    print("❌ Неверный выбор. Пожалуйста, выберите 0-5")
                
                input("\n📱 Нажмите Enter для продолжения...")
                
            except KeyboardInterrupt:
                print("\n\n⌨️ Выход по Ctrl+C")
                break
            except Exception as e:
                print(f"\n❌ Неожиданная ошибка: {e}")
                input("📱 Нажмите Enter для продолжения...")


def main():
    """🚀 Главная функция"""
    manager = TradesManager()
    manager.run()


if __name__ == "__main__":
    main()