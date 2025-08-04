# 🤖 DOGE Trading Bot v4.1-refactored

Автоматизированный торговый бот с новой архитектурой.

## 🚀 Быстрый старт

```bash
# Установка зависимостей
pip install -r requirements.txt

# Настройка
cp .env.example .env
# Отредактируйте .env файл

# Запуск
python main.py --mode hybrid
```

## ⚙️ Режимы работы

- `--mode legacy` - Старый бот (работает)
- `--mode hybrid` - Гибридный режим (в разработке)
- `--mode new` - Новая архитектура (в разработке)

## 📁 Структура

```
├── src/                # Новая архитектура
├── backup_before_migration/  # Бэкап старых файлов
├── main.py            # Новая точка входа
└── main_old.py        # Старый main.py
```

## 🔄 Откат

```bash
# Восстановление старого бота
cp main_old.py main.py
python main.py
```
