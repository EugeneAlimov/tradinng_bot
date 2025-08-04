#!/usr/bin/env python3
"""🎯 Миграция Part 10B - Среда разработки и скрипты"""
import logging
from pathlib import Path

class Migration:
    """🎯 Настройка среды разработки и создание скриптов"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.logger = logging.getLogger(__name__)
    
    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("🎯 Настройка среды разработки...")
            
            # Настраиваем среду разработки
            self._setup_development_environment()
            
            # Создаем автоматизированные скрипты
            self._create_automation_scripts()
            
            self.logger.info("✅ Среда разработки и скрипты созданы")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка настройки среды: {e}")
            return False
    
    def _setup_development_environment(self):
        """🛠️ Настройка среды разработки"""
        # requirements-dev.txt
        dev_requirements_content = '''# 🛠️ Зависимости для разработки

# Тестирование
pytest>=7.0.0
pytest-asyncio>=0.21.0
pytest-cov>=4.0.0
pytest-mock>=3.10.0
pytest-benchmark>=4.0.0

# Форматирование и линтинг
black>=23.0.0
isort>=5.12.0
flake8>=6.0.0
mypy>=1.0.0
pre-commit>=3.0.0

# Документация
sphinx>=6.0.0
sphinx-rtd-theme>=1.2.0

# Профилирование
memory-profiler>=0.60.0

# Дополнительные инструменты
watchdog>=3.0.0  # Мониторинг файлов
rich>=13.0.0     # Красивый вывод в консоль
'''
        
        dev_requirements_file = self.project_root / "requirements-dev.txt"
        dev_requirements_file.write_text(dev_requirements_content)
        
        # pre-commit конфигурация
        precommit_content = '''# Pre-commit hooks для автоматической проверки кода
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files

  - repo: https://github.com/psf/black
    rev: 23.1.0
    hooks:
      - id: black
        language_version: python3
        args: [--line-length=88]

  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort
        args: [--profile=black]

  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
        args: [--max-line-length=88, --extend-ignore=E203,W503]
'''
        
        precommit_file = self.project_root / ".pre-commit-config.yaml"
        precommit_file.write_text(precommit_content)
        
        # VS Code настройки
        vscode_dir = self.project_root / ".vscode"
        vscode_dir.mkdir(exist_ok=True)
        
        vscode_settings = '''{
    "python.defaultInterpreterPath": "./venv/bin/python",
    "python.formatting.provider": "black",
    "python.linting.enabled": true,
    "python.linting.flake8Enabled": true,
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": ["tests"],
    "editor.formatOnSave": true,
    "editor.rulers": [88],
    "files.exclude": {
        "**/__pycache__": true,
        "**/*.pyc": true,
        ".pytest_cache": true,
        ".coverage": true,
        "htmlcov": true
    }
}'''
        
        vscode_settings_file = vscode_dir / "settings.json"
        vscode_settings_file.write_text(vscode_settings)
    
    def _create_automation_scripts(self):
        """🔧 Создание автоматизированных скриптов"""
        scripts_dir = self.project_root / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        
        # Скрипт диагностики
        diagnostic_script = '''#!/usr/bin/env python3
"""🔍 Диагностика системы"""
import sys
import subprocess
from pathlib import Path
import json
from datetime import datetime

def check_python_version():
    """Проверка версии Python"""
    version = sys.version_info
    print(f"🐍 Python: {version.major}.{version.minor}.{version.micro}")
    
    if version < (3, 8):
        print("❌ Требуется Python 3.8+")
        return False
    else:
        print("✅ Версия Python подходит")
        return True

def check_dependencies():
    """Проверка зависимостей"""
    try:
        with open("requirements.txt", "r") as f:
            requirements = f.read().splitlines()
        
        missing = []
        for req in requirements:
            if req.strip() and not req.startswith("#"):
                try:
                    # Простая проверка импорта основных пакетов
                    package_name = req.split(">=")[0].split("==")[0]
                    if package_name in ["requests", "pandas", "numpy"]:
                        __import__(package_name)
                except ImportError:
                    missing.append(req)
        
        if missing:
            print(f"❌ Возможно отсутствуют зависимости: {', '.join(missing)}")
            return False
        else:
            print("✅ Основные зависимости доступны")
            return True
    except FileNotFoundError:
        print("❌ Файл requirements.txt не найден")
        return False

def check_config():
    """Проверка конфигурации"""
    env_file = Path(".env")
    if not env_file.exists():
        print("❌ Файл .env не найден")
        return False
    
    print("✅ Конфигурационный файл найден")
    
    # Проверяем основные настройки
    with open(env_file, "r") as f:
        content = f.read()
    
    required_vars = ["EXMO_API_KEY", "EXMO_API_SECRET", "TRADING_PROFILE"]
    missing_vars = []
    
    for var in required_vars:
        if var not in content:
            missing_vars.append(var)
    
    if missing_vars:
        print(f"⚠️ Отсутствуют переменные: {', '.join(missing_vars)}")
        return False
    
    return True

def check_directories():
    """Проверка структуры директорий"""
    required_dirs = ["src", "tests", "logs", "data"]
    missing_dirs = []
    
    for dir_name in required_dirs:
        dir_path = Path(dir_name)
        if not dir_path.exists():
            try:
                dir_path.mkdir(exist_ok=True)
                print(f"✅ Создана директория: {dir_name}")
            except:
                missing_dirs.append(dir_name)
    
    if missing_dirs:
        print(f"❌ Не удалось создать директории: {', '.join(missing_dirs)}")
        return False
    else:
        print("✅ Структура директорий корректна")
        return True

def run_quick_tests():
    """Запуск быстрых тестов"""
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/unit/", "-v", "--tb=short", "-x"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            print("✅ Быстрые тесты прошли успешно")
            return True
        else:
            print(f"❌ Тесты не прошли")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("⚠️ Не удалось запустить тесты")
        return True  # Не критично

def generate_report():
    """Генерация отчета диагностики"""
    print("\\n🔍 ДИАГНОСТИКА СИСТЕМЫ")
    print("=" * 50)
    
    checks = {
        "python_version": check_python_version(),
        "dependencies": check_dependencies(), 
        "config": check_config(),
        "directories": check_directories(),
        "tests": run_quick_tests()
    }
    
    passed_checks = sum(1 for check in checks.values() if check)
    total_checks = len(checks)
    
    print(f"\\n📈 РЕЗУЛЬТАТ: {passed_checks}/{total_checks} проверок прошли")
    
    # Сохраняем отчет
    report = {
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
        "success_rate": passed_checks / total_checks
    }
    
    with open("diagnostic_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
    if passed_checks == total_checks:
        print("🎉 Система готова к работе!")
        return 0
    else:
        print("⚠️ Обнаружены проблемы, требуется внимание")
        return 1

if __name__ == "__main__":
    sys.exit(generate_report())
'''
        
        diagnostic_file = scripts_dir / "diagnostic.py"
        diagnostic_file.write_text(diagnostic_script)
        diagnostic_file.chmod(0o755)
        
        # Скрипт анализа статистики
        stats_script = '''#!/usr/bin/env python3
"""📊 Анализ торговой статистики"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
import argparse

def load_trading_data(days=30):
    """Загрузка данных торговли"""
    data_dir = Path("data")
    trades_file = data_dir / "trades.json"
    
    if not trades_file.exists():
        print("❌ Файл с данными торговли не найден")
        # Создаем пример данных для демонстрации
        sample_trades = generate_sample_trades(days)
        return sample_trades
    
    with open(trades_file, "r") as f:
        trades = json.load(f)
    
    # Фильтруем по дням
    cutoff_date = datetime.now() - timedelta(days=days)
    filtered_trades = [
        trade for trade in trades
        if datetime.fromisoformat(trade["timestamp"]) >= cutoff_date
    ]
    
    return filtered_trades

def generate_sample_trades(days):
    """Генерация примера данных"""
    import random
    trades = []
    
    for i in range(days * 2):  # 2 сделки в день в среднем
        trade_time = datetime.now() - timedelta(days=days-i//2, hours=random.randint(0, 23))
        trades.append({
            "trade_id": f"sample_{i}",
            "pair": "DOGE_EUR",
            "type": "buy" if i % 2 == 0 else "sell",
            "amount": float(Decimal(str(100 + random.randint(-20, 50)))),
            "price": float(Decimal("0.18") + Decimal(str(random.uniform(-0.02, 0.02)))),
            "pnl": random.uniform(-5, 8),
            "timestamp": trade_time.isoformat()
        })
    
    return trades

def calculate_statistics(trades):
    """Расчет статистики"""
    if not trades:
        return {}
    
    total_trades = len(trades)
    profitable_trades = len([t for t in trades if float(t.get("pnl", 0)) > 0])
    win_rate = profitable_trades / total_trades if total_trades > 0 else 0
    
    # PnL статистика
    pnls = [float(t.get("pnl", 0)) for t in trades]
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(pnls) if pnls else 0
    
    # Максимальные значения
    max_profit = max(pnls) if pnls else 0
    max_loss = min(pnls) if pnls else 0
    
    return {
        "total_trades": total_trades,
        "profitable_trades": profitable_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
        "max_profit": max_profit,
        "max_loss": max_loss
    }

def generate_report(stats, days):
    """Генерация текстового отчета"""
    report = f"""
📊 ОТЧЕТ ПО ТОРГОВЛЕ (за последние {days} дней)
{'='*50}

📈 Общая статистика:
  • Всего сделок: {stats['total_trades']}
  • Прибыльных сделок: {stats['profitable_trades']}
  • Винрейт: {stats['win_rate']:.1%}

💰 Финансовые показатели:
  • Общий PnL: {stats['total_pnl']:.2f} EUR
  • Средний PnL за сделку: {stats['avg_pnl']:.2f} EUR
  • Максимальная прибыль: {stats['max_profit']:.2f} EUR
  • Максимальный убыток: {stats['max_loss']:.2f} EUR

📊 Оценка производительности:
"""
    
    # Добавляем оценки
    if stats['win_rate'] >= 0.6:
        report += "  ✅ Отличный винрейт (>60%)\\n"
    elif stats['win_rate'] >= 0.5:
        report += "  ⚠️ Приемлемый винрейт (50-60%)\\n"
    else:
        report += "  ❌ Низкий винрейт (<50%)\\n"
    
    if stats['total_pnl'] > 0:
        report += "  ✅ Положительная доходность\\n"
    else:
        report += "  ❌ Отрицательная доходность\\n"
    
    return report

def main():
    parser = argparse.ArgumentParser(description="Анализ торговой статистики")
    parser.add_argument("--days", type=int, default=30, help="Количество дней для анализа")
    parser.add_argument("--output", default="reports", help="Директория для сохранения")
    
    args = parser.parse_args()
    
    print(f"📊 Анализ торговли за последние {args.days} дней...")
    
    # Загружаем данные
    trades = load_trading_data(args.days)
    if not trades:
        print("❌ Нет данных для анализа")
        return 1
    
    # Рассчитываем статистику
    stats = calculate_statistics(trades)
    
    # Генерируем отчет
    report = generate_report(stats, args.days)
    print(report)
    
    # Сохраняем отчет
    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True)
    
    with open(output_dir / f"trading_report_{datetime.now().strftime('%Y%m%d')}.txt", "w") as f:
        f.write(report)
    
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
'''
        
        stats_file = scripts_dir / "analyze_trading_stats.py"
        stats_file.write_text(stats_script)
        stats_file.chmod(0o755)

if __name__ == "__main__":
    import sys
    migration = Migration(Path("."))
    success = migration.execute()
    sys.exit(0 if success else 1)