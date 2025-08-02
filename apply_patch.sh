#!/bin/bash

# 🔄 Скрипт автоматического применения патча миграции
# DOGE Trading Bot v4.1 → v4.1-refactored

echo "🔄 АВТОМАТИЧЕСКИЙ ПАТЧ МИГРАЦИИ"
echo "🤖 DOGE Trading Bot v4.1 → v4.1-refactored"
echo "=============================================="

# Проверяем наличие Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден!"
    echo "💡 Установите Python 3.8+ для продолжения"
    exit 1
fi

# Проверяем что мы в правильной директории
if [ ! -f "bot.py" ] && [ ! -f "hybrid_bot.py" ] && [ ! -f "config.py" ]; then
    echo "❌ Не найдены файлы торгового бота!"
    echo "💡 Убедитесь что вы запускаете скрипт в директории с ботом"
    exit 1
fi

echo "✅ Найдены файлы торгового бота"

# Показываем что будет сделано
echo ""
echo "🎯 ЧТО БУДЕТ СДЕЛАНО:"
echo "  📦 Создание новой архитектуры src/"
echo "  💾 Бэкап всех существующих файлов"
echo "  🔄 Создание адаптеров совместимости"
echo "  🧪 Добавление тестов"
echo "  📚 Обновление документации"
echo "  🚀 Новый main.py с выбором режимов"

# Спрашиваем подтверждение
echo ""
read -p "❓ Продолжить миграцию? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Миграция отменена"
    exit 0
fi

# Проверяем наличие файла патча
if [ ! -f "migration_patch.py" ]; then
    echo "❌ Файл migration_patch.py не найден!"
    echo "💡 Убедитесь что файл патча находится в текущей директории"
    exit 1
fi

echo "🔄 Запуск патча миграции..."
echo ""

# Запускаем патч
python3 migration_patch.py

# Проверяем результат
if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО!"
    echo ""
    echo "🚀 СЛЕДУЮЩИЕ ШАГИ:"
    echo "  1. Проверьте настройки: python3 main.py --validate"
    echo "  2. Установите зависимости: pip3 install -r requirements.txt"
    echo "  3. Запустите бота: python3 main.py --mode hybrid"
    echo ""
    echo "📋 ДОСТУПНЫЕ РЕЖИМЫ:"
    echo "  🎭 hybrid  - новая архитектура + совместимость (рекомендуется)"
    echo "  📜 legacy  - старый бот без изменений"
    echo "  🆕 new     - полная новая архитектура (в разработке)"
    echo ""
    echo "📁 БЭКАПЫ:"
    echo "  📦 backup_before_migration/ - все старые файлы"
    echo "  📄 main_old.py - копия старого main.py"
    echo ""
    echo "📚 ДОКУМЕНТАЦИЯ:"
    echo "  📖 README_NEW.md - руководство по новой версии"
    echo "  📋 CHANGELOG.md - список изменений"
    
    # Предлагаем запустить тесты
    echo ""
    read -p "❓ Запустить тесты совместимости? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🧪 Запуск тестов..."
        
        # Проверяем наличие pytest
        if command -v pytest &> /dev/null; then
            pytest tests/ -v
        else
            echo "⚠️ pytest не найден, устанавливаем..."
            pip3 install pytest pytest-asyncio
            pytest tests/ -v
        fi
    fi
    
    echo ""
    echo "✅ Готово! Бот готов к запуску в новой архитектуре."
    
else
    echo ""
    echo "❌ ОШИБКА МИГРАЦИИ!"
    echo "🔄 Проверьте логи выше для деталей"
    echo "💡 При критических проблемах файлы можно восстановить из backup_before_migration/"
    exit 1
fi
