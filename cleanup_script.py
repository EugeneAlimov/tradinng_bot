#!/usr/bin/env python3
"""🧹 Скрипт очистки торгового бота от мусора"""

import os
import shutil
import json
import glob
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Set
import logging

class BotCleaner:
    """🧹 Класс для очистки торгового бота от мусора"""
    
    def __init__(self):
        self.root_dir = Path(".")
        self.logger = self._setup_logger()
        
        # Цветовые коды для вывода
        self.GREEN = "\033[92m"
        self.RED = "\033[91m"
        self.YELLOW = "\033[93m"
        self.BLUE = "\033[94m"
        self.END = "\033[0m"
        
        # Статистика очистки
        self.stats = {
            'files_removed': 0,
            'directories_removed': 0,
            'bytes_freed': 0,
            'duplicates_removed': 0
        }
    
    def _setup_logger(self):
        """📝 Настройка логирования"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('cleanup.log'),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger(__name__)
    
    def analyze_project(self) -> Dict[str, List[str]]:
        """🔍 Анализ проекта для выявления мусора"""
        print(f"{self.BLUE}🔍 Анализ проекта...{self.END}")
        
        analysis = {
            'duplicate_files': [],
            'unused_files': [],
            'old_backups': [],
            'temp_files': [],
            'large_files': [],
            'broken_imports': [],
            'empty_directories': [],
            'migration_artifacts': []
        }
        
        # Поиск дубликатов
        analysis['duplicate_files'] = self._find_duplicate_files()
        
        # Поиск неиспользуемых файлов
        analysis['unused_files'] = self._find_unused_files()
        
        # Поиск старых бэкапов
        analysis['old_backups'] = self._find_old_backups()
        
        # Поиск временных файлов
        analysis['temp_files'] = self._find_temp_files()
        
        # Поиск больших файлов
        analysis['large_files'] = self._find_large_files()
        
        # Поиск пустых директорий
        analysis['empty_directories'] = self._find_empty_directories()
        
        # Поиск артефактов миграции
        analysis['migration_artifacts'] = self._find_migration_artifacts()
        
        return analysis
    
    def _find_duplicate_files(self) -> List[Dict[str, str]]:
        """🔍 Поиск дублирующихся файлов"""
        duplicates = []
        
        # Известные дубликаты в проекте
        known_duplicates = [
            ('main.py', 'main_old.py'),
            ('bot.py', 'hybrid_bot.py'),
            ('config.py', 'hybrid_config.py'),
            ('improved_bot.py', 'bot.py')
        ]
        
        for original, duplicate in known_duplicates:
            if (self.root_dir / original).exists() and (self.root_dir / duplicate).exists():
                duplicates.append({
                    'original': original,
                    'duplicate': duplicate,
                    'reason': 'Legacy файл'
                })
        
        return duplicates
    
    def _find_unused_files(self) -> List[str]:
        """🔍 Поиск неиспользуемых файлов"""
        unused = []
        
        # Файлы, которые могут быть неиспользуемыми
        potentially_unused = [
            'test_*.py',
            '*_test.py',
            '*.pyc',
            '__pycache__/*',
            '*.log.old',
            '*.bak',
            'trades_manager.py',  # Утилита, не основной функционал
            'simple_analytics.py',  # Если есть улучшенная версия
            'basic_*.py'  # Базовые версии
        ]
        
        for pattern in potentially_unused:
            files = glob.glob(str(self.root_dir / pattern), recursive=True)
            unused.extend([str(Path(f).relative_to(self.root_dir)) for f in files])
        
        return unused
    
    def _find_old_backups(self) -> List[str]:
        """🔍 Поиск старых бэкапов"""
        backups = []
        
        # Паттерны бэкапов
        backup_patterns = [
            '*_old.py',
            '*_backup.py',
            '*.old',
            '*.bak',
            'backup_*',
            '*_copy.py'
        ]
        
        for pattern in backup_patterns:
            files = glob.glob(str(self.root_dir / pattern))
            backups.extend([str(Path(f).relative_to(self.root_dir)) for f in files])
        
        # Директории бэкапов
        backup_dirs = ['backup_before_migration', 'old_files', 'backups']
        for backup_dir in backup_dirs:
            if (self.root_dir / backup_dir).exists():
                backups.append(backup_dir)
        
        return backups
    
    def _find_temp_files(self) -> List[str]:
        """🔍 Поиск временных файлов"""
        temp_files = []
        
        # Паттерны временных файлов
        temp_patterns = [
            '*.tmp',
            '*.temp',
            '.DS_Store',
            'Thumbs.db',
            '*.swp',
            '*.swo',
            '*~',
            '.pytest_cache/*',
            '__pycache__/*',
            '*.pyc'
        ]
        
        for pattern in temp_patterns:
            files = glob.glob(str(self.root_dir / pattern), recursive=True)
            temp_files.extend([str(Path(f).relative_to(self.root_dir)) for f in files])
        
        return temp_files
    
    def _find_large_files(self, size_limit_mb: int = 10) -> List[Dict[str, any]]:
        """🔍 Поиск больших файлов"""
        large_files = []
        size_limit = size_limit_mb * 1024 * 1024  # Конвертируем в байты
        
        for file_path in self.root_dir.rglob('*'):
            if file_path.is_file():
                try:
                    file_size = file_path.stat().st_size
                    if file_size > size_limit:
                        large_files.append({
                            'path': str(file_path.relative_to(self.root_dir)),
                            'size_mb': file_size / (1024 * 1024),
                            'size_bytes': file_size
                        })
                except (OSError, PermissionError):
                    continue
        
        return sorted(large_files, key=lambda x: x['size_bytes'], reverse=True)
    
    def _find_empty_directories(self) -> List[str]:
        """🔍 Поиск пустых директорий"""
        empty_dirs = []
        
        for dir_path in self.root_dir.rglob('*'):
            if dir_path.is_dir():
                try:
                    # Проверяем, пустая ли директория
                    if not any(dir_path.iterdir()):
                        empty_dirs.append(str(dir_path.relative_to(self.root_dir)))
                except (OSError, PermissionError):
                    continue
        
        return empty_dirs
    
    def _find_migration_artifacts(self) -> List[str]:
        """🔍 Поиск артефактов миграции"""
        artifacts = []
        
        # Файлы миграции
        migration_patterns = [
            'migration_*.py',
            '*_migration.py',
            'auto_fix_patch.py',
            'migration_patch.py',
            'migration_report.json',
            'diagnostic_report.json'
        ]
        
        for pattern in migration_patterns:
            files = glob.glob(str(self.root_dir / pattern))
            artifacts.extend([str(Path(f).relative_to(self.root_dir)) for f in files])
        
        return artifacts
    
    def clean_project(self, analysis: Dict[str, List], interactive: bool = True) -> None:
        """🧹 Очистка проекта"""
        print(f"{self.YELLOW}🧹 Начинаем очистку проекта...{self.END}")
        
        # Создаем бэкап перед очисткой
        if interactive:
            create_backup = input(f"{self.BLUE}💾 Создать бэкап перед очисткой? (Y/n): {self.END}").lower()
            if create_backup != 'n':
                self._create_cleanup_backup()
        
        # Очищаем по категориям
        if analysis['temp_files']:
            self._clean_temp_files(analysis['temp_files'], interactive)
        
        if analysis['duplicate_files']:
            self._clean_duplicates(analysis['duplicate_files'], interactive)
        
        if analysis['empty_directories']:
            self._clean_empty_directories(analysis['empty_directories'], interactive)
        
        if analysis['migration_artifacts']:
            self._clean_migration_artifacts(analysis['migration_artifacts'], interactive)
        
        if analysis['old_backups']:
            self._clean_old_backups(analysis['old_backups'], interactive)
        
        # Показываем статистику
        self._show_cleanup_stats()
    
    def _create_cleanup_backup(self) -> None:
        """💾 Создание бэкапа перед очисткой"""
        backup_dir = self.root_dir / f"cleanup_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_dir.mkdir(exist_ok=True)
        
        # Копируем важные файлы
        important_files = [
            '*.py',
            '*.json',
            '.env*',
            'requirements*.txt',
            'README*',
            'config/*'
        ]
        
        for pattern in important_files:
            files = glob.glob(str(self.root_dir / pattern))
            for file_path in files:
                if Path(file_path).is_file():
                    rel_path = Path(file_path).relative_to(self.root_dir)
                    dest_path = backup_dir / rel_path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file_path, dest_path)
        
        print(f"{self.GREEN}💾 Бэкап создан: {backup_dir}{self.END}")
    
    def _clean_temp_files(self, temp_files: List[str], interactive: bool) -> None:
        """🗑️ Очистка временных файлов"""
        if not temp_files:
            return
        
        print(f"\n{self.YELLOW}🗑️ Очистка временных файлов ({len(temp_files)} найдено):{self.END}")
        
        if interactive:
            print("Найдены временные файлы:")
            for file_path in temp_files[:10]:  # Показываем первые 10
                print(f"  • {file_path}")
            if len(temp_files) > 10:
                print(f"  ... и еще {len(temp_files) - 10} файлов")
            
            confirm = input(f"{self.BLUE}Удалить временные файлы? (Y/n): {self.END}").lower()
            if confirm == 'n':
                return
        
        for file_path in temp_files:
            try:
                full_path = self.root_dir / file_path
                if full_path.exists():
                    if full_path.is_file():
                        size = full_path.stat().st_size
                        full_path.unlink()
                        self.stats['files_removed'] += 1
                        self.stats['bytes_freed'] += size
                    elif full_path.is_dir():
                        shutil.rmtree(full_path)
                        self.stats['directories_removed'] += 1
                    
                    print(f"  ✅ Удален: {file_path}")
            except Exception as e:
                print(f"  ❌ Ошибка удаления {file_path}: {e}")
    
    def _clean_duplicates(self, duplicates: List[Dict[str, str]], interactive: bool) -> None:
        """🗑️ Очистка дубликатов"""
        if not duplicates:
            return
        
        print(f"\n{self.YELLOW}🗑️ Очистка дубликатов ({len(duplicates)} найдено):{self.END}")
        
        for dup_info in duplicates:
            original = dup_info['original']
            duplicate = dup_info['duplicate']
            reason = dup_info['reason']
            
            print(f"  Дубликат: {duplicate} (оригинал: {original}) - {reason}")
            
            if interactive:
                action = input(f"    Удалить {duplicate}? (y/N/s-skip): ").lower()
                if action == 's':
                    continue
                elif action != 'y':
                    continue
            
            try:
                duplicate_path = self.root_dir / duplicate
                if duplicate_path.exists():
                    size = duplicate_path.stat().st_size
                    duplicate_path.unlink()
                    self.stats['files_removed'] += 1
                    self.stats['duplicates_removed'] += 1
                    self.stats['bytes_freed'] += size
                    print(f"    ✅ Удален дубликат: {duplicate}")
            except Exception as e:
                print(f"    ❌ Ошибка удаления {duplicate}: {e}")
    
    def _clean_empty_directories(self, empty_dirs: List[str], interactive: bool) -> None:
        """🗑️ Очистка пустых директорий"""
        if not empty_dirs:
            return
        
        print(f"\n{self.YELLOW}🗑️ Очистка пустых директорий ({len(empty_dirs)} найдено):{self.END}")
        
        if interactive:
            print("Найдены пустые директории:")
            for dir_path in empty_dirs:
                print(f"  • {dir_path}/")
            
            confirm = input(f"{self.BLUE}Удалить пустые директории? (Y/n): {self.END}").lower()
            if confirm == 'n':
                return
        
        # Сортируем по глубине (сначала самые глубокие)
        empty_dirs.sort(key=lambda x: len(Path(x).parts), reverse=True)
        
        for dir_path in empty_dirs:
            try:
                full_path = self.root_dir / dir_path
                if full_path.exists() and full_path.is_dir():
                    full_path.rmdir()
                    self.stats['directories_removed'] += 1
                    print(f"  ✅ Удалена директория: {dir_path}/")
            except Exception as e:
                print(f"  ❌ Ошибка удаления {dir_path}: {e}")
    
    def _clean_migration_artifacts(self, artifacts: List[str], interactive: bool) -> None:
        """🗑️ Очистка артефактов миграции"""
        if not artifacts:
            return
        
        print(f"\n{self.YELLOW}🗑️ Очистка артефактов миграции ({len(artifacts)} найдено):{self.END}")
        
        if interactive:
            print("Найдены артефакты миграции:")
            for artifact in artifacts:
                print(f"  • {artifact}")
            
            confirm = input(f"{self.BLUE}Удалить артефакты миграции? (Y/n): {self.END}").lower()
            if confirm == 'n':
                return
        
        for artifact in artifacts:
            try:
                artifact_path = self.root_dir / artifact
                if artifact_path.exists():
                    size = artifact_path.stat().st_size
                    artifact_path.unlink()
                    self.stats['files_removed'] += 1
                    self.stats['bytes_freed'] += size
                    print(f"  ✅ Удален артефакт: {artifact}")
            except Exception as e:
                print(f"  ❌ Ошибка удаления {artifact}: {e}")
    
    def _clean_old_backups(self, backups: List[str], interactive: bool) -> None:
        """🗑️ Очистка старых бэкапов"""
        if not backups:
            return
        
        print(f"\n{self.YELLOW}🗑️ Очистка старых бэкапов ({len(backups)} найдено):{self.END}")
        
        if interactive:
            print("Найдены старые бэкапы:")
            for backup in backups:
                print(f"  • {backup}")
            
            confirm = input(f"{self.BLUE}Удалить старые бэкапы? (y/N): {self.END}").lower()
            if confirm != 'y':
                return
        
        for backup in backups:
            try:
                backup_path = self.root_dir / backup
                if backup_path.exists():
                    if backup_path.is_file():
                        size = backup_path.stat().st_size
                        backup_path.unlink()
                        self.stats['files_removed'] += 1
                        self.stats['bytes_freed'] += size
                    elif backup_path.is_dir():
                        # Подсчитываем размер директории перед удалением
                        total_size = sum(f.stat().st_size for f in backup_path.rglob('*') if f.is_file())
                        shutil.rmtree(backup_path)
                        self.stats['directories_removed'] += 1
                        self.stats['bytes_freed'] += total_size
                    
                    print(f"  ✅ Удален бэкап: {backup}")
            except Exception as e:
                print(f"  ❌ Ошибка удаления {backup}: {e}")
    
    def _show_cleanup_stats(self) -> None:
        """📊 Показ статистики очистки"""
        print(f"\n{self.GREEN}📊 СТАТИСТИКА ОЧИСТКИ{self.END}")
        print("=" * 30)
        print(f"Удалено файлов: {self.stats['files_removed']}")
        print(f"Удалено директорий: {self.stats['directories_removed']}")
        print(f"Удалено дубликатов: {self.stats['duplicates_removed']}")
        print(f"Освобождено места: {self.stats['bytes_freed'] / (1024*1024):.2f} MB")
    
    def show_analysis_report(self, analysis: Dict[str, List]) -> None:
        """📋 Показ отчета анализа"""
        print(f"\n{self.BLUE}📋 ОТЧЕТ АНАЛИЗА ПРОЕКТА{self.END}")
        print("=" * 40)
        
        categories = [
            ('duplicate_files', 'Дубликаты файлов', '🔄'),
            ('unused_files', 'Неиспользуемые файлы', '❌'),
            ('old_backups', 'Старые бэкапы', '📦'),
            ('temp_files', 'Временные файлы', '🗑️'),
            ('large_files', 'Большие файлы', '📊'),
            ('empty_directories', 'Пустые директории', '📁'),
            ('migration_artifacts', 'Артефакты миграции', '🔄')
        ]
        
        total_issues = 0
        
        for key, title, emoji in categories:
            items = analysis[key]
            if items:
                print(f"\n{emoji} {title}: {len(items)}")
                
                if key == 'large_files':
                    for item in items[:5]:  # Показываем топ-5 больших файлов
                        print(f"  • {item['path']} ({item['size_mb']:.2f} MB)")
                    if len(items) > 5:
                        print(f"  ... и еще {len(items) - 5} файлов")
                elif key == 'duplicate_files':
                    for item in items:
                        print(f"  • {item['duplicate']} (дубликат {item['original']})")
                else:
                    for item in items[:10]:  # Показываем первые 10
                        print(f"  • {item}")
                    if len(items) > 10:
                        print(f"  ... и еще {len(items) - 10} элементов")
                
                total_issues += len(items)
            else:
                print(f"{emoji} {title}: ✅ Чисто")
        
        print(f"\n{'='*40}")
        print(f"Всего найдено проблем: {total_issues}")
        
        if total_issues > 0:
            print(f"{self.YELLOW}💡 Рекомендуется провести очистку{self.END}")
        else:
            print(f"{self.GREEN}🎉 Проект уже чистый!{self.END}")
    
    def run_interactive_cleanup(self) -> None:
        """🚀 Интерактивная очистка"""
        print(f"{self.BLUE}🧹 ИНТЕРАКТИВНАЯ ОЧИСТКА ТОРГОВОГО БОТА{self.END}")
        print("=" * 50)
        
        # Анализируем проект
        analysis = self.analyze_project()
        
        # Показываем отчет
        self.show_analysis_report(analysis)
        
        # Предлагаем очистку
        total_issues = sum(len(items) for items in analysis.values())
        if total_issues > 0:
            print(f"\n{self.YELLOW}Найдено {total_issues} проблем для очистки{self.END}")
            proceed = input(f"{self.BLUE}Продолжить с очисткой? (Y/n): {self.END}").lower()
            
            if proceed != 'n':
                self.clean_project(analysis, interactive=True)
            else:
                print("Очистка отменена")
        else:
            print(f"{self.GREEN}Проект уже чистый! 🎉{self.END}")


def main():
    """🚀 Главная функция"""
    cleaner = BotCleaner()
    
    try:
        cleaner.run_interactive_cleanup()
    except KeyboardInterrupt:
        print(f"\n{cleaner.YELLOW}⌨️ Очистка прервана пользователем{cleaner.END}")
    except Exception as e:
        print(f"\n{cleaner.RED}❌ Ошибка очистки: {e}{cleaner.END}")
        cleaner.logger.error(f"Cleanup error: {e}")


if __name__ == "__main__":
    main()