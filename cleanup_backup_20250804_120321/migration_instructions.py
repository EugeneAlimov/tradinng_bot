#!/usr/bin/env python3
"""📚 Инструкция по запуску автоматической миграции"""

migration_guide = """
🚀 АВТОМАТИЧЕСКАЯ МИГРАЦИЯ ТОРГОВОГО БОТА v4.1-refactored
================================================================

📋 ОБЗОР МИГРАЦИИ:
Миграция разбита на 10 частей для управляемого процесса:

Part 1: Core интерфейсы      - Базовые интерфейсы системы
Part 2: Core модели          - Модели данных и исключения  
Part 3: Конфигурация         - Настройки и константы
Part 4: DI контейнер         - Dependency Injection
Part 5: Инфраструктура       - API, персистентность, мониторинг
Part 6: Доменная логика      - Стратегии, риск-менеджмент
Part 7: Слой приложения      - Сервисы и оркестраторы
Part 8: Адаптеры             - Совместимость со старым кодом
Part 9: Тестирование         - Unit и integration тесты
Part 10: Финализация         - Документация и настройки

🔧 СПОСОБЫ ЗАПУСКА:

1️⃣ АВТОМАТИЧЕСКИЙ (РЕКОМЕНДУЕТСЯ):
   python migration_executor.py
   
   ✅ Автоматически выполняет все части
   ✅ Создает бэкапы
   ✅ Проверяет результат
   ✅ Откатывает при ошибках

2️⃣ РУЧНОЙ (для разработчиков):
   # Создайте каждый файл migration_partX.py из артефактов
   # Затем запустите по очереди:
   
   python -c "
   from migration_part1_core_interfaces import Migration
   m = Migration('.')
   m.execute()
   "
   
   # И так далее для всех частей...

3️⃣ ПОШАГОВЫЙ (для отладки):
   python migration_executor.py --status     # Проверка текущего состояния
   # Редактирование migration_executor.py при необходимости
   python migration_executor.py              # Запуск

⚠️ ПОДГОТОВКА К МИГРАЦИИ:

1. ОСТАНОВИТЕ БОТ:
   - Убедитесь что все процессы торговли завершены
   - Закройте все активные ордера
   - Сохраните текущие позиции

2. СОЗДАЙТЕ БЭКАП:
   # Ручной бэкап (дополнительно)
   cp -r . ../trading_bot_backup_$(date +%Y%m%d_%H%M%S)

3. ПРОВЕРЬТЕ ОКРУЖЕНИЕ:
   python --version          # Должно быть >= 3.8
   pip install -r requirements.txt
   
4. ПРОВЕРЬТЕ ФАЙЛЫ:
   # Основные файлы должны присутствовать:
   ls config.py api_client.py position_manager.py

📊 ПОСЛЕ МИГРАЦИИ:

✅ ПРОВЕРКА РЕЗУЛЬТАТА:
   python main.py --validate                 # Проверка конфигурации
   python main.py --mode legacy              # Тест старого бота
   ls src/                                    # Проверка новой структуры

✅ НОВАЯ СТРУКТУРА:
   src/
   ├── core/                 # Интерфейсы, модели, исключения
   ├── config/               # Настройки и константы
   ├── infrastructure/       # API, БД, мониторинг
   ├── domain/               # Бизнес-логика, стратегии
   └── application/          # Сервисы и оркестраторы

✅ РЕЖИМЫ РАБОТЫ:
   python main.py --mode legacy              # Старый бот (100% работает)
   python main.py --mode hybrid              # Новый + адаптеры (в разработке)
   python main.py --mode new                 # Полная новая архитектура (в разработке)

🆘 ОТКАТ И ВОССТАНОВЛЕНИЕ:

❌ ЕСЛИ ЧТО-ТО ПОШЛО НЕ ТАК:
   python migration_executor.py --rollback   # Автоматический откат
   
   # Или вручную:
   cp main_old.py main.py
   rm -rf src/
   # Восстановите из backup_before_migration/

❌ ПОЛНОЕ ВОССТАНОВЛЕНИЕ:
   # Если автоматический откат не работает
   rm -rf src/ tests/ *.py
   cp backup_before_migration/* .
   cp backup_before_migration/data/ ./data/
   cp backup_before_migration/logs/ ./logs/

🔍 ДИАГНОСТИКА ПРОБЛЕМ:

🐛 ПРОБЛЕМЫ ИМПОРТА:
   # Проверьте структуру src/
   find src/ -name "*.py" -exec python -m py_compile {} \;

🐛 ПРОБЛЕМЫ КОНФИГУРАЦИИ:
   python -c "
   import sys
   sys.path.insert(0, 'src')
   from config.settings import get_settings
   print(get_settings())
   "

🐛 ПРОБЛЕМЫ ЗАВИСИМОСТЕЙ:
   # Убедитесь в совместимости интерфейсов
   python -c "
   import sys
   sys.path.insert(0, 'src')
   from infrastructure.di_container import DependencyContainer
   container = DependencyContainer()
   print('DI контейнер работает')
   "

📝 ЛОГИ И ОТЛАДКА:
   tail -f logs/migration.log                # Логи миграции
   tail -f logs/trading_bot.log              # Логи бота
   
   # Включение отладки:
   export LOG_LEVEL=DEBUG
   python main.py --mode legacy

🔗 ДОПОЛНИТЕЛЬНЫЕ РЕСУРСЫ:

📚 ДОКУМЕНТАЦИЯ:
   README_NEW.md             # Новая документация
   CHANGELOG.md              # История изменений
   
📊 СТРУКТУРА ПРОЕКТА:
   # См. диаграмму архитектуры в README_NEW.md

🧪 ТЕСТИРОВАНИЕ:
   pytest tests/             # Запуск тестов
   pytest -m unit            # Только unit тесты
   pytest -m integration     # Только integration тесты

💡 СОВЕТЫ ПО ИСПОЛЬЗОВАНИЮ:

✨ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ:
   - Используйте --mode legacy для стабильной работы
   - Следите за логами при переходе на новые режимы
   - Делайте регулярные бэкапы данных

✨ ДЛЯ РАЗРАБОТЧИКОВ:
   - Изучите src/core/interfaces.py для понимания архитектуры
   - Используйте DI контейнер для новых компонентов
   - Добавляйте тесты в tests/ для новой функциональности

✨ ДЛЯ ОТЛАДКИ:
   - Включайте DEBUG логирование
   - Используйте migration_executor.py --status для проверки
   - Проверяйте каждый шаг миграции отдельно

🎯 ЦЕЛИ МИГРАЦИИ:

✅ ДОСТИГНУТО:
   - Clean Architecture внедрена
   - Dependency Injection настроен
   - Обратная совместимость обеспечена
   - Модульная структура создана
   - Тестирование подготовлено

🚧 В РАЗРАБОТКЕ:
   - Полная интеграция новых компонентов
   - Веб-интерфейс для мониторинга
   - Расширенная аналитика
   - Мульти-биржевая поддержка

🎉 ПОЗДРАВЛЯЕМ С УСПЕШНОЙ МИГРАЦИЕЙ!

Вы обновили торговый бот до современной архитектуры с сохранением
всей функциональности. Теперь система готова к дальнейшему развитию
и добавлению новых возможностей.

📧 Поддержка: проверьте логи или восстановите из бэкапа при проблемах
🔄 Обновления: следите за новыми версиями в репозитории
"""

def print_migration_guide():
    """📚 Вывод полного руководства"""
    print(migration_guide)

def print_quick_start():
    """🚀 Быстрое начало"""
    print("""
🚀 БЫСТРЫЙ СТАРТ МИГРАЦИИ:

1. python migration_executor.py      # Запуск миграции
2. python main.py --validate         # Проверка
3. python main.py --mode legacy      # Тест старого бота

❌ Если проблемы:
   python migration_executor.py --rollback
""")

def print_troubleshooting():
    """🔧 Решение проблем"""
    print("""
🔧 ЧАСТЫЕ ПРОБЛЕМЫ И РЕШЕНИЯ:

❌ "ModuleNotFoundError":
   → Проверьте структуру src/
   → Убедитесь что все __init__.py созданы

❌ "ConfigurationError":
   → Скопируйте .env.example в .env
   → Заполните API ключи

❌ "DependencyError":
   → Проверьте src/infrastructure/di_container.py
   → Убедитесь в правильности интерфейсов

❌ Бот не запускается:
   → Используйте --mode legacy
   → Проверьте логи в logs/

❌ Откат не работает:
   → Восстановите вручную из backup_before_migration/
   → Копируйте main_old.py в main.py
""")

if __name__ == "__main__":
    import sys
    
    if "--quick" in sys.argv:
        print_quick_start()
    elif "--troubleshooting" in sys.argv:
        print_troubleshooting()
    else:
        print_migration_guide()
