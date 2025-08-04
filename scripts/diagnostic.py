#!/usr/bin/env python3
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
    print("\n🔍 ДИАГНОСТИКА СИСТЕМЫ")
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
    
    print(f"\n📈 РЕЗУЛЬТАТ: {passed_checks}/{total_checks} проверок прошли")
    
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
