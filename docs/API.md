# 📡 API Документация

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
