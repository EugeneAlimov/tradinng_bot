#!/usr/bin/env python3
"""🔄 Миграция Part 8A - Базовые адаптеры"""
import logging
from pathlib import Path

class Migration:
    """🔄 Создание базовых адаптеров совместимости"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.src_dir = project_root / "src"
        self.adapters_dir = self.src_dir / "presentation" / "adapters"
        self.logger = logging.getLogger(__name__)
    
    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("🔄 Создание базовых адаптеров...")
            
            # Создаем структуру директорий
            self._create_directory_structure()
            
            # Создаем базовый адаптер
            self._create_base_adapter()
            
            # Создаем безопасный адаптер
            self._create_safe_adapter()
            
            self.logger.info("✅ Базовые адаптеры созданы")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания адаптеров: {e}")
            return False
    
    def _create_directory_structure(self):
        """📁 Создание структуры директорий"""
        dirs_to_create = [
            self.adapters_dir,
        ]
        
        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
            
            # Создаем __init__.py
            init_file = dir_path / "__init__.py"
            if not init_file.exists():
                init_content = '''"""🔄 Адаптеры совместимости"""

from .base_adapter import BaseAdapter
from .safe_adapter import SafeAdapter
from .legacy_bot_adapter import LegacyBotAdapter

__all__ = [
    'BaseAdapter',
    'SafeAdapter', 
    'LegacyBotAdapter'
]
'''
                init_file.write_text(init_content)
    
    def _create_base_adapter(self):
        """🔧 Создание базового адаптера"""
        base_adapter_content = '''#!/usr/bin/env python3
"""🔧 Базовый адаптер для совместимости"""

import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from pathlib import Path
import sys

class BaseAdapter(ABC):
    """🔧 Базовый класс для всех адаптеров"""
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.is_initialized = False
        self._setup_paths()
        
        self.logger.info(f"🔧 Создан адаптер: {name}")
    
    def _setup_paths(self):
        """📁 Настройка путей для импорта"""
        # Добавляем корневую директорию в путь
        project_root = Path(__file__).parent.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        # Добавляем директорию src
        src_path = project_root / "src"
        if str(src_path) not in sys.path:
            sys.path.insert(0, str(src_path))
    
    @abstractmethod
    async def initialize(self) -> bool:
        """🚀 Инициализация адаптера"""
        pass
    
    @abstractmethod
    async def execute_cycle(self) -> Dict[str, Any]:
        """🔄 Выполнение одного цикла"""
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """🧹 Очистка ресурсов"""
        pass
    
    def get_status(self) -> Dict[str, Any]:
        """📊 Получение статуса адаптера"""
        return {
            'name': self.name,
            'initialized': self.is_initialized,
            'class': self.__class__.__name__
        }
    
    async def safe_execute(self, func, *args, **kwargs) -> Optional[Any]:
        """🛡️ Безопасное выполнение функции"""
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            self.logger.error(f"❌ Ошибка выполнения {func.__name__}: {e}")
            return None
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """✅ Валидация конфигурации"""
        try:
            # Базовая валидация
            if not isinstance(config, dict):
                self.logger.error("❌ Конфигурация должна быть словарем")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка валидации конфигурации: {e}")
            return False
    
    def adapt_data(self, data: Any, source_format: str, target_format: str) -> Any:
        """🔄 Адаптация данных между форматами"""
        try:
            self.logger.debug(f"🔄 Адаптация данных: {source_format} -> {target_format}")
            
            # Базовая адаптация - просто возвращаем данные
            return data
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка адаптации данных: {e}")
            return data
    
    def handle_error(self, error: Exception, context: str = "") -> None:
        """⚠️ Обработка ошибок"""
        error_msg = f"❌ Ошибка в {self.name}"
        if context:
            error_msg += f" ({context})"
        error_msg += f": {error}"
        
        self.logger.error(error_msg)
        
        # Можно добавить уведомления, метрики и т.д.


class AdapterError(Exception):
    """⚠️ Базовая ошибка адаптера"""
    pass


class AdapterInitializationError(AdapterError):
    """⚠️ Ошибка инициализации адаптера"""
    pass


class AdapterExecutionError(AdapterError):
    """⚠️ Ошибка выполнения адаптера"""
    pass
'''
        
        base_adapter_file = self.adapters_dir / "base_adapter.py"
        base_adapter_file.write_text(base_adapter_content)
    
    def _create_safe_adapter(self):
        """🛡️ Создание безопасного адаптера"""
        safe_adapter_content = '''#!/usr/bin/env python3
"""🛡️ Безопасный адаптер для тестирования"""

import asyncio
from typing import Any, Dict, Optional
from decimal import Decimal
from datetime import datetime

from .base_adapter import BaseAdapter, AdapterInitializationError


class SafeAdapter(BaseAdapter):
    """🛡️ Безопасный адаптер для paper trading и тестирования"""
    
    def __init__(self):
        super().__init__("SafeAdapter")
        self.mock_balance = {
            'EUR': Decimal('1000.00'),
            'DOGE': Decimal('5000.00')
        }
        self.mock_price = Decimal('0.18000')
        self.orders_history = []
        self.cycle_count = 0
    
    async def initialize(self) -> bool:
        """🚀 Инициализация безопасного адаптера"""
        try:
            self.logger.info("🛡️ Инициализация безопасного адаптера...")
            
            # Проверяем, что мы в безопасном режиме
            self.logger.info("📊 Режим paper trading активен")
            self.logger.info(f"💰 Начальный баланс: EUR={self.mock_balance['EUR']}, DOGE={self.mock_balance['DOGE']}")
            
            self.is_initialized = True
            self.logger.info("✅ Безопасный адаптер инициализирован")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации: {e}")
            raise AdapterInitializationError(f"Не удалось инициализировать SafeAdapter: {e}")
    
    async def execute_cycle(self) -> Dict[str, Any]:
        """🔄 Выполнение безопасного торгового цикла"""
        try:
            if not self.is_initialized:
                raise AdapterInitializationError("Адаптер не инициализирован")
            
            self.cycle_count += 1
            self.logger.info(f"🔄 Выполнение цикла #{self.cycle_count}")
            
            # Симулируем получение рыночных данных
            market_data = await self._get_mock_market_data()
            
            # Симулируем анализ
            analysis_result = await self._mock_analysis(market_data)
            
            # Симулируем принятие торгового решения
            trading_decision = await self._make_mock_decision(analysis_result)
            
            # Симулируем выполнение ордера (если есть)
            execution_result = await self._execute_mock_order(trading_decision)
            
            result = {
                'success': True,
                'cycle': self.cycle_count,
                'timestamp': datetime.now().isoformat(),
                'market_data': market_data,
                'analysis': analysis_result,
                'decision': trading_decision,
                'execution': execution_result,
                'balance': {k: float(v) for k, v in self.mock_balance.items()},
                'orders_count': len(self.orders_history)
            }
            
            self.logger.info(f"✅ Цикл #{self.cycle_count} выполнен успешно")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка выполнения цикла: {e}")
            return {
                'success': False,
                'error': str(e),
                'cycle': self.cycle_count,
                'timestamp': datetime.now().isoformat()
            }
    
    async def _get_mock_market_data(self) -> Dict[str, Any]:
        """📊 Получение мок данных рынка"""
        # Симулируем небольшие колебания цены
        import random
        price_change = Decimal(str(random.uniform(-0.001, 0.001)))
        self.mock_price += self.mock_price * price_change
        
        # Не даем цене стать отрицательной
        if self.mock_price <= 0:
            self.mock_price = Decimal('0.01')
        
        return {
            'pair': 'DOGE_EUR',
            'price': float(self.mock_price),
            'volume_24h': random.randint(1000000, 5000000),
            'change_24h': float(price_change * 100),  # в процентах
            'timestamp': datetime.now().isoformat()
        }
    
    async def _mock_analysis(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """🧠 Мок анализ рынка"""
        # Простая логика для демонстрации
        current_price = market_data['price']
        
        # Генерируем случайный сигнал
        import random
        actions = ['hold', 'buy', 'sell']
        action = random.choices(actions, weights=[70, 15, 15])[0]  # 70% hold
        confidence = random.uniform(0.3, 0.9)
        
        reasons = {
            'hold': 'Нет четкого сигнала',
            'buy': 'Потенциал роста',
            'sell': 'Фиксация прибыли'
        }
        
        return {
            'action': action,
            'confidence': confidence,
            'reason': reasons[action],
            'analysis_time': datetime.now().isoformat(),
            'indicators': {
                'rsi': random.uniform(20, 80),
                'ma_signal': random.choice(['bullish', 'bearish', 'neutral'])
            }
        }
    
    async def _make_mock_decision(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """🎯 Принятие мок торгового решения"""
        action = analysis['action']
        confidence = analysis['confidence']
        
        # Принимаем решение только при высокой уверенности
        if action != 'hold' and confidence > 0.7:
            amount = 100  # EUR для покупки или количество DOGE для продажи
            
            return {
                'should_trade': True,
                'action': action,
                'amount': amount,
                'price': float(self.mock_price),
                'confidence': confidence,
                'timestamp': datetime.now().isoformat()
            }
        
        return {
            'should_trade': False,
            'reason': f"Низкая уверенность ({confidence:.2f}) или hold сигнал",
            'timestamp': datetime.now().isoformat()
        }
    
    async def _execute_mock_order(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """💼 Выполнение мок ордера"""
        if not decision.get('should_trade', False):
            return {'executed': False, 'reason': 'Нет торгового решения'}
        
        try:
            action = decision['action']
            amount = decision['amount']
            price = Decimal(str(decision['price']))
            
            order_id = f"mock_order_{len(self.orders_history) + 1}"
            
            if action == 'buy':
                # Покупаем DOGE за EUR
                cost = Decimal(str(amount))
                if self.mock_balance['EUR'] >= cost:
                    doge_amount = cost / price
                    self.mock_balance['EUR'] -= cost
                    self.mock_balance['DOGE'] += doge_amount
                    
                    order = {
                        'id': order_id,
                        'action': 'buy',
                        'amount_eur': float(cost),
                        'amount_doge': float(doge_amount),
                        'price': float(price),
                        'timestamp': datetime.now().isoformat(),
                        'status': 'filled'
                    }
                    
                    self.orders_history.append(order)
                    self.logger.info(f"💰 Покупка: {doge_amount:.2f} DOGE за {cost} EUR по цене {price}")
                    
                    return {'executed': True, 'order': order}
                else:
                    return {'executed': False, 'reason': 'Недостаточно EUR для покупки'}
            
            elif action == 'sell':
                # Продаем DOGE за EUR
                doge_amount = Decimal(str(amount))
                if self.mock_balance['DOGE'] >= doge_amount:
                    eur_amount = doge_amount * price
                    self.mock_balance['DOGE'] -= doge_amount
                    self.mock_balance['EUR'] += eur_amount
                    
                    order = {
                        'id': order_id,
                        'action': 'sell',
                        'amount_doge': float(doge_amount),
                        'amount_eur': float(eur_amount),
                        'price': float(price),
                        'timestamp': datetime.now().isoformat(),
                        'status': 'filled'
                    }
                    
                    self.orders_history.append(order)
                    self.logger.info(f"💰 Продажа: {doge_amount} DOGE за {eur_amount:.2f} EUR по цене {price}")
                    
                    return {'executed': True, 'order': order}
                else:
                    return {'executed': False, 'reason': 'Недостаточно DOGE для продажи'}
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка выполнения мок ордера: {e}")
            return {'executed': False, 'error': str(e)}
    
    async def cleanup(self) -> None:
        """🧹 Очистка ресурсов"""
        self.logger.info("🧹 Очистка ресурсов SafeAdapter...")
        
        # Выводим финальную статистику
        total_orders = len(self.orders_history)
        buy_orders = len([o for o in self.orders_history if o['action'] == 'buy'])
        sell_orders = len([o for o in self.orders_history if o['action'] == 'sell'])
        
        self.logger.info(f"📊 Статистика: {total_orders} ордеров ({buy_orders} покупок, {sell_orders} продаж)")
        self.logger.info(f"💰 Финальный баланс: EUR={self.mock_balance['EUR']}, DOGE={self.mock_balance['DOGE']}")
        
        self.is_initialized = False
    
    def get_trading_history(self) -> List[Dict[str, Any]]:
        """📈 Получение истории торгов"""
        return self.orders_history.copy()
    
    def get_balance(self) -> Dict[str, float]:
        """💰 Получение текущего баланса"""
        return {k: float(v) for k, v in self.mock_balance.items()}
'''
        
        safe_adapter_file = self.adapters_dir / "safe_adapter.py"
        safe_adapter_file.write_text(safe_adapter_content)

if __name__ == "__main__":
    import sys
    migration = Migration(Path("."))
    success = migration.execute()
    sys.exit(0 if success else 1)