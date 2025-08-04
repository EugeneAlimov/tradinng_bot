# ⚙️ Руководство по конфигурации

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
