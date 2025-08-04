# 🤖 DOGE Trading Bot v4.1-refactored

Профессиональный автоматизированный торговый бот для криптовалюты DOGE с современной архитектурой.

## 🌟 Особенности

- ✅ **Clean Architecture** - четкое разделение ответственности
- ✅ **Dependency Injection** - слабая связанность компонентов
- ✅ **Полная типизация** - type hints для всех компонентов
- ✅ **Профили торговли** - консервативный, сбалансированный, агрессивный
- ✅ **DCA стратегия** - усреднение позиции при просадках
- ✅ **Риск-менеджмент** - комплексная система управления рисками
- ✅ **Обратная совместимость** - адаптеры для старого кода
- ✅ **Полное тестирование** - unit, integration, performance тесты

## 🚀 Быстрый старт

### 1. Установка

```bash
# Клонирование репозитория
git clone <repository_url>
cd doge-trading-bot

# Установка зависимостей
pip install -r requirements.txt
```

### 2. Настройка

```bash
# Создание конфигурации
cp .env.example .env

# Редактирование настроек
nano .env
```

**Обязательные настройки в .env:**
```env
# API ключи EXMO
EXMO_API_KEY=your_api_key_here
EXMO_API_SECRET=your_api_secret_here

# Профиль торговли
TRADING_PROFILE=balanced  # conservative, balanced, aggressive

# Режим работы
TRADING_MODE=paper        # paper, live
```

### 3. Запуск

```bash
# Проверка конфигурации
python main.py --validate

# Запуск в paper trading режиме
python main.py --mode paper

# Запуск в гибридном режиме
python main.py --mode hybrid

# Запуск в legacy режиме
python main.py --mode legacy
```

## 📊 Профили торговли

| Профиль | Размер позиции | Стоп-лосс | Take-profit | DCA шаги | Риск |
|---------|---------------|-----------|-------------|----------|------|
| **Conservative** | 4% | 10% | 15% | 3 | Низкий |
| **Balanced** | 6% | 15% | 25% | 5 | Средний |
| **Aggressive** | 10% | 20% | 35% | 7 | Высокий |

## 🧪 Тестирование

```bash
# Запуск всех тестов
pytest

# Unit тесты
pytest -m unit

# Integration тесты
pytest -m integration

# Performance тесты
pytest -m performance

# Тесты с покрытием кода
pytest --cov=src --cov-report=html
```

## 📁 Структура проекта

```
├── src/                    # 🏗️ Новая архитектура
│   ├── core/              # 🔧 Основные абстракции
│   ├── config/            # ⚙️ Конфигурация
│   ├── infrastructure/    # 🏭 Инфраструктура
│   ├── domain/           # 🧠 Доменная логика
│   ├── application/      # 🎭 Слой приложения
│   └── presentation/     # 🎨 Интерфейсы
├── tests/                # 🧪 Тесты
├── docs/                 # 📚 Документация
├── scripts/              # 🔧 Утилиты
├── main.py              # 🚀 Точка входа
└── requirements.txt     # 📦 Зависимости
```

## ⚠️ Важные замечания

1. **Тестирование**: Всегда тестируйте на paper trading перед реальной торговлей
2. **Безопасность**: Никогда не делитесь API ключами
3. **Риски**: Торговля криптовалютой связана с высокими рисками
4. **Мониторинг**: Регулярно проверяйте работу бота и логи

## 🆘 Поддержка

При проблемах:
1. **Проверьте конфигурацию**: `python main.py --validate`
2. **Запустите диагностику**: `python scripts/diagnostic.py`
3. **Проверьте логи**: `tail -f logs/trading_bot.log`

---

**⚠️ Disclaimer**: Этот бот предназначен для образовательных целей. Торговля криптовалютой связана с высокими рисками.
