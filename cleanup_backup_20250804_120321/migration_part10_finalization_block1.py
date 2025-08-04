#!/usr/bin/env python3
"""🎯 Миграция Part 10A - Базовая документация"""
import logging
from pathlib import Path
from datetime import datetime

class Migration:
    """🎯 Создание базовой документации проекта"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.logger = logging.getLogger(__name__)
    
    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("🎯 Создание базовой документации...")
            
            # Создаем основную документацию
            self._create_main_documentation()
            
            # Создаем руководство по конфигурации
            self._create_configuration_guide()
            
            self.logger.info("✅ Базовая документация создана")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания документации: {e}")
            return False
    
    def _create_main_documentation(self):
        """📚 Создание главной документации"""
        docs_dir = self.project_root / "docs"
        docs_dir.mkdir(exist_ok=True)
        
        # Главный README
        readme_content = '''# 🤖 DOGE Trading Bot v4.1-refactored

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
'''
        
        readme_file = self.project_root / "README.md"
        readme_file.write_text(readme_content)
        
        # API документация
        api_docs_content = '''# 📡 API Документация

## Обзор архитектуры

Bot использует Clean Architecture с четким разделением слоев:

- **Core**: Базовые интерфейсы и модели
- **Infrastructure**: Внешние сервисы (API, БД, уведомления)
- **Domain**: Бизнес-логика (стратегии, риск-менеджмент)
- **Application**: Сервисы приложения
- **Presentation**: Интерфейсы пользователя

## Core Interfaces

### ExchangeAPI
```python
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional

class ExchangeAPI(ABC):
    @abstractmethod
    async def get_ticker(self, pair: str) -> Dict:
        """Получение тикера для пары"""
        pass
    
    @abstractmethod
    async def get_balance(self) -> Dict[str, Dict[str, Decimal]]:
        """Получение баланса"""
        pass
    
    @abstractmethod
    async def create_order(self, pair: str, type: str, amount: Decimal, price: Decimal) -> Dict:
        """Создание ордера"""
        pass
```

### TradingStrategy
```python
class TradingStrategy(ABC):
    @abstractmethod
    def analyze(self, market_data: Dict) -> Dict:
        """Анализ рынка и генерация сигнала"""
        pass
    
    @abstractmethod
    def should_buy(self, market_data: Dict) -> bool:
        """Проверка условий для покупки"""
        pass
    
    @abstractmethod
    def should_sell(self, market_data: Dict) -> bool:
        """Проверка условий для продажи"""
        pass
```

## Создание собственной стратегии

```python
from src.core.interfaces import TradingStrategy
from decimal import Decimal
from typing import Dict

class MyCustomStrategy(TradingStrategy):
    def __init__(self, threshold: Decimal = Decimal('0.02')):
        self.threshold = threshold
        self.name = "MyCustomStrategy"
    
    def analyze(self, market_data: Dict) -> Dict:
        current_price = market_data.get('last', 0)
        # Ваша логика анализа здесь
        
        return {
            'action': 'hold',  # 'buy', 'sell', 'hold'
            'confidence': 0.5,  # 0.0 - 1.0
            'reason': 'Описание решения'
        }
    
    def should_buy(self, market_data: Dict) -> bool:
        return self.analyze(market_data)['action'] == 'buy'
    
    def should_sell(self, market_data: Dict) -> bool:
        return self.analyze(market_data)['action'] == 'sell'
```

## Events и Hooks

```python
from src.core.events import EventBus

# Подписка на события
@event_bus.subscribe('order_created')
def on_order_created(event_data):
    print(f"Создан ордер: {event_data['order_id']}")

# Генерация событий
event_bus.emit('custom_event', {'data': 'value'})
```

## Мониторинг и метрики

```python
from src.infrastructure.monitoring import MetricsCollector

metrics = MetricsCollector()
metrics.increment('custom_strategy_signals')
metrics.gauge('current_position_size', position_size)
```
'''
        
        api_docs_file = docs_dir / "API.md"
        api_docs_file.write_text(api_docs_content)
    
    def _create_configuration_guide(self):
        """⚙️ Создание руководства по конфигурации"""
        docs_dir = self.project_root / "docs"
        
        config_guide_content = '''# ⚙️ Руководство по конфигурации

## Основные настройки

### Файл .env

```env
# 🔐 API настройки EXMO
EXMO_API_KEY=your_api_key_here
EXMO_API_SECRET=your_api_secret_here

# 📊 Торговые настройки
TRADING_PROFILE=balanced        # conservative, balanced, aggressive
TRADING_MODE=paper             # paper, live
TRADING_PAIR=DOGE_EUR          # Торговая пара

# 💰 Размеры позиций (%)
POSITION_SIZE_PERCENT=6.0      # Размер позиции от баланса
MAX_POSITION_SIZE_PERCENT=50.0 # Максимальный размер позиции
STOP_LOSS_PERCENT=15.0         # Стоп-лосс
TAKE_PROFIT_PERCENT=25.0       # Тейк-профит

# 🎯 DCA настройки
DCA_ENABLED=true               # Включить DCA
DCA_STEP_PERCENT=5.0          # Шаг усреднения
DCA_MAX_STEPS=5               # Максимум шагов
DCA_STEP_MULTIPLIER=1.5       # Мультипликатор шага

# ⚠️ Риск-менеджмент
MAX_DAILY_LOSS_PERCENT=10.0    # Максимальная дневная просадка
MAX_DRAWDOWN_PERCENT=20.0      # Максимальная просадка
EMERGENCY_STOP_PERCENT=30.0    # Аварийная остановка

# 📱 Уведомления
TELEGRAM_ENABLED=false         # Включить Telegram
TELEGRAM_BOT_TOKEN=           # Токен бота
TELEGRAM_CHAT_ID=             # ID чата

# 🔧 Технические настройки
LOG_LEVEL=INFO                # DEBUG, INFO, WARNING, ERROR
UPDATE_INTERVAL=15            # Интервал обновления (секунды)
API_TIMEOUT=30               # Таймаут API (секунды)
```

## Профили торговли

### Conservative (Консервативный)
```python
CONSERVATIVE_PROFILE = {
    'position_size_percent': Decimal('4.0'),
    'max_position_size_percent': Decimal('30.0'),
    'stop_loss_percent': Decimal('10.0'),
    'take_profit_percent': Decimal('15.0'),
    'dca': {
        'enabled': True,
        'step_percent': Decimal('3.0'),
        'max_steps': 3,
        'step_multiplier': Decimal('1.2')
    }
}
```

### Balanced (Сбалансированный)
```python
BALANCED_PROFILE = {
    'position_size_percent': Decimal('6.0'),
    'max_position_size_percent': Decimal('50.0'),
    'stop_loss_percent': Decimal('15.0'),
    'take_profit_percent': Decimal('25.0'),
    'dca': {
        'enabled': True,
        'step_percent': Decimal('5.0'),
        'max_steps': 5,
        'step_multiplier': Decimal('1.5')
    }
}
```

### Aggressive (Агрессивный)
```python
AGGRESSIVE_PROFILE = {
    'position_size_percent': Decimal('10.0'),
    'max_position_size_percent': Decimal('70.0'),
    'stop_loss_percent': Decimal('20.0'),
    'take_profit_percent': Decimal('35.0'),
    'dca': {
        'enabled': True,
        'step_percent': Decimal('7.0'),
        'max_steps': 7,
        'step_multiplier': Decimal('2.0')
    }
}
```

## Кастомный профиль

Создайте файл `config/custom_profile.py`:

```python
from decimal import Decimal

CUSTOM_PROFILE = {
    'name': 'my_custom_profile',
    'description': 'Мой собственный профиль торговли',
    
    # Основные настройки
    'position_size_percent': Decimal('8.0'),
    'max_position_size_percent': Decimal('60.0'),
    'stop_loss_percent': Decimal('18.0'),
    'take_profit_percent': Decimal('30.0'),
    
    # DCA настройки
    'dca': {
        'enabled': True,
        'step_percent': Decimal('6.0'),
        'max_steps': 6,
        'step_multiplier': Decimal('1.8')
    },
    
    # Риск-менеджмент
    'risk': {
        'max_daily_loss_percent': Decimal('12.0'),
        'max_drawdown_percent': Decimal('25.0'),
        'emergency_stop_percent': Decimal('35.0')
    }
}
```

## Валидация конфигурации

Запустите валидацию:
```bash
python main.py --validate
```

Пример валидации:
```python
def validate_config(config):
    errors = []
    
    # API ключи
    if not config.exmo_api_key or len(config.exmo_api_key) < 10:
        errors.append("EXMO API key слишком короткий")
    
    # Размеры позиций
    if config.position_size_percent <= 0 or config.position_size_percent > 100:
        errors.append("Размер позиции должен быть между 0 и 100%")
    
    return errors
```

## Переменные окружения

Для продакшена используйте переменные окружения:

```bash
export EXMO_API_KEY="your_api_key"
export EXMO_API_SECRET="your_api_secret"
export TRADING_PROFILE="balanced"
export TRADING_MODE="live"
```

## Мониторинг конфигурации

```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ConfigWatcher(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('.env'):
            print("Конфигурация изменена, перезагружаем...")
            reload_config()
```
'''
        
        config_guide_file = docs_dir / "CONFIGURATION.md"
        config_guide_file.write_text(config_guide_content)

if __name__ == "__main__":
    import sys
    migration = Migration(Path("."))
    success = migration.execute()
    sys.exit(0 if success else 1)