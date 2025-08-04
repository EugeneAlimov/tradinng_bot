#!/usr/bin/env python3
"""🎯 Адаптер стратегий"""

from typing import Any, Dict, List, Optional
from datetime import datetime

from .base_adapter import BaseAdapter


class StrategyAdapter(BaseAdapter):
    """🎯 Адаптер для интеграции старых и новых стратегий"""
    
    def __init__(self):
        super().__init__("StrategyAdapter")
        self.legacy_strategies: List[Any] = []
        self.strategy_instances: Dict[str, Any] = {}
        self.active_strategy: Optional[str] = None
    
    async def initialize(self) -> bool:
        """🚀 Инициализация адаптера стратегий"""
        try:
            self.logger.info("🎯 Инициализация адаптера стратегий...")
            
            # Загружаем старые стратегии
            await self._load_legacy_strategies()
            
            # Создаем экземпляры базовых стратегий
            await self._create_basic_strategies()
            
            self.is_initialized = True
            self.logger.info("✅ Адаптер стратегий инициализирован")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации адаптера стратегий: {e}")
            return False
    
    async def _load_legacy_strategies(self) -> None:
        """📥 Загрузка старых стратегий"""
        try:
            strategy_modules = [
                'adaptive_dca_strategy',
                'pyramid_strategy', 
                'trailing_stop'
            ]
            
            for module_name in strategy_modules:
                try:
                    module = __import__(module_name)
                    
                    # Ищем классы стратегий
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and 
                            'strategy' in attr_name.lower() and 
                            not attr_name.startswith('_')):
                            
                            self.legacy_strategies.append({
                                'name': attr_name,
                                'class': attr,
                                'module': module_name,
                                'type': 'legacy'
                            })
                            
                            self.logger.debug(f"🎯 Загружена legacy стратегия: {attr_name}")
                
                except ImportError:
                    self.logger.debug(f"⚠️ Модуль {module_name} не найден")
                    continue
            
            self.logger.info(f"✅ Загружено {len(self.legacy_strategies)} legacy стратегий")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки legacy стратегий: {e}")
    
    async def _create_basic_strategies(self) -> None:
        """🏗️ Создание базовых стратегий"""
        try:
            # Создаем простые стратегии для демонстрации
            basic_strategies = {
                'hold_strategy': self._create_hold_strategy(),
                'random_strategy': self._create_random_strategy(),
                'trend_strategy': self._create_trend_strategy()
            }
            
            self.strategy_instances.update(basic_strategies)
            self.logger.info(f"✅ Создано {len(basic_strategies)} базовых стратегий")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания базовых стратегий: {e}")
    
    def _create_hold_strategy(self) -> Dict[str, Any]:
        """📊 Создание HOLD стратегии"""
        return {
            'name': 'hold_strategy',
            'type': 'basic',
            'analyze': lambda data: {
                'action': 'hold',
                'confidence': 1.0,
                'reason': 'HOLD стратегия - всегда держим позицию'
            }
        }
    
    def _create_random_strategy(self) -> Dict[str, Any]:
        """🎲 Создание случайной стратегии"""
        def random_analyze(data):
            import random
            actions = ['hold', 'buy', 'sell']
            action = random.choices(actions, weights=[70, 15, 15])[0]
            
            return {
                'action': action,
                'confidence': random.uniform(0.3, 0.8),
                'reason': f'Случайная стратегия: {action}'
            }
        
        return {
            'name': 'random_strategy',
            'type': 'basic',
            'analyze': random_analyze
        }
    
    def _create_trend_strategy(self) -> Dict[str, Any]:
        """📈 Создание трендовой стратегии"""
        def trend_analyze(data):
            price = data.get('price', 0.18)
            
            # Простая логика на основе цены
            if price < 0.17:
                return {
                    'action': 'buy',
                    'confidence': 0.7,
                    'reason': 'Цена ниже 0.17 - сигнал покупки'
                }
            elif price > 0.19:
                return {
                    'action': 'sell',
                    'confidence': 0.7,
                    'reason': 'Цена выше 0.19 - сигнал продажи'
                }
            else:
                return {
                    'action': 'hold',
                    'confidence': 0.5,
                    'reason': 'Цена в нейтральной зоне'
                }
        
        return {
            'name': 'trend_strategy',
            'type': 'basic',
            'analyze': trend_analyze
        }
    
    async def execute_cycle(self) -> Dict[str, Any]:
        """🔄 Выполнение цикла анализа стратегий"""
        try:
            if not self.is_initialized:
                return {'success': False, 'error': 'Адаптер не инициализирован'}
            
            # Получаем мок данные для анализа
            market_data = await self._get_mock_market_data()
            
            # Выполняем анализ всеми доступными стратегиями
            results = {}
            
            # Анализ базовыми стратегиями
            for name, strategy in self.strategy_instances.items():
                try:
                    if 'analyze' in strategy:
                        analysis = strategy['analyze'](market_data)
                        results[name] = {
                            'type': strategy['type'],
                            'analysis': analysis,
                            'timestamp': datetime.now().isoformat()
                        }
                except Exception as e:
                    self.logger.warning(f"⚠️ Ошибка анализа стратегии {name}: {e}")
                    results[name] = {'error': str(e)}
            
            # Анализ legacy стратегиями (если доступны)
            for strategy_info in self.legacy_strategies:
                try:
                    strategy_name = strategy_info['name']
                    strategy_class = strategy_info['class']
                    
                    # Пытаемся создать экземпляр и выполнить анализ
                    instance = strategy_class()
                    if hasattr(instance, 'analyze'):
                        analysis = instance.analyze(market_data)
                        results[strategy_name] = {
                            'type': 'legacy',
                            'analysis': analysis,
                            'timestamp': datetime.now().isoformat()
                        }
                    
                except Exception as e:
                    self.logger.warning(f"⚠️ Ошибка legacy стратегии {strategy_name}: {e}")
                    results[strategy_name] = {'error': str(e)}
            
            return {
                'success': True,
                'timestamp': datetime.now().isoformat(),
                'market_data': market_data,
                'strategies_count': len(results),
                'results': results
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка выполнения цикла стратегий: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _get_mock_market_data(self) -> Dict[str, Any]:
        """📊 Получение мок рыночных данных"""
        import random
        
        return {
            'price': 0.18 + random.uniform(-0.02, 0.02),
            'volume': random.randint(1000000, 5000000),
            'change_24h': random.uniform(-5, 5),
            'timestamp': datetime.now().isoformat()
        }
    
    def set_active_strategy(self, strategy_name: str) -> bool:
        """🎯 Установка активной стратегии"""
        try:
            if strategy_name in self.strategy_instances:
                self.active_strategy = strategy_name
                self.logger.info(f"🎯 Активная стратегия: {strategy_name}")
                return True
            else:
                self.logger.warning(f"⚠️ Стратегия {strategy_name} не найдена")
                return False
        except Exception as e:
            self.logger.error(f"❌ Ошибка установки активной стратегии: {e}")
            return False
    
    def get_available_strategies(self) -> List[Dict[str, Any]]:
        """📋 Получение списка доступных стратегий"""
        strategies = []
        
        # Базовые стратегии
        for name, strategy in self.strategy_instances.items():
            strategies.append({
                'name': name,
                'type': strategy['type'],
                'active': name == self.active_strategy
            })
        
        # Legacy стратегии
        for strategy_info in self.legacy_strategies:
            strategies.append({
                'name': strategy_info['name'],
                'type': 'legacy',
                'module': strategy_info['module'],
                'active': False
            })
        
        return strategies
    
    async def cleanup(self) -> None:
        """🧹 Очистка ресурсов"""
        self.logger.info("🧹 Очистка адаптера стратегий...")
        
        self.legacy_strategies.clear()
        self.strategy_instances.clear()
        self.active_strategy = None
        self.is_initialized = False
        
        self.logger.info("✅ Адаптер стратегий очищен")
