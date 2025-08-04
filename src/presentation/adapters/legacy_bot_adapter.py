#!/usr/bin/env python3
"""🤖 Адаптер для старого бота"""

import sys
import asyncio
from typing import Any, Dict, Optional, List
from pathlib import Path
from datetime import datetime

from .base_adapter import BaseAdapter, AdapterInitializationError, AdapterExecutionError


class LegacyBotAdapter(BaseAdapter):
    """🤖 Адаптер для интеграции со старым ботом"""
    
    def __init__(self, use_hybrid: bool = True):
        super().__init__("LegacyBotAdapter")
        self.use_hybrid = use_hybrid
        self.legacy_bot: Optional[Any] = None
        self.legacy_modules: Dict[str, Any] = {}
        self.legacy_config: Dict[str, Any] = {}
        self.is_running = False
        
        self.logger.info(f"🤖 Legacy адаптер создан (hybrid={use_hybrid})")
    
    async def initialize(self) -> bool:
        """🚀 Инициализация адаптера старого бота"""
        try:
            self.logger.info("🤖 Инициализация Legacy адаптера...")
            
            # Загружаем старый бот
            self.legacy_bot = await self._load_legacy_bot()
            
            # Загружаем старую конфигурацию
            self.legacy_config = await self._load_legacy_config()
            
            # Загружаем старые стратегии
            await self._load_legacy_strategies()
            
            if self.legacy_bot or self.use_hybrid:
                self.is_initialized = True
                self.logger.info("✅ Legacy адаптер инициализирован")
                return True
            else:
                raise AdapterInitializationError("Не удалось загрузить legacy компоненты")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации Legacy адаптера: {e}")
            return False
    
    async def _load_legacy_bot(self) -> Optional[Any]:
        """📥 Загрузка старого бота"""
        try:
            self.logger.info("📥 Попытка загрузки старого бота...")
            
            # Список возможных модулей со старым ботом
            bot_modules = [
                ('improved_bot', 'ImprovedTradingBot'),
                ('bot', 'ImprovedTradingBot'),
                ('bot', 'TradingBot'),
                ('main', 'TradingBot'),
            ]
            
            for module_name, class_name in bot_modules:
                try:
                    self.logger.debug(f"🔍 Пытаемся загрузить {class_name} из {module_name}")
                    
                    # Пытаемся импортировать модуль
                    module = __import__(module_name)
                    
                    # Пытаемся получить класс
                    if hasattr(module, class_name):
                        bot_class = getattr(module, class_name)
                        
                        # Создаем экземпляр
                        bot_instance = bot_class()
                        
                        self.logger.info(f"✅ Загружен {class_name} из {module_name}")
                        return bot_instance
                    
                except ImportError as e:
                    self.logger.debug(f"⚠️ Модуль {module_name} не найден: {e}")
                    continue
                except Exception as e:
                    self.logger.warning(f"⚠️ Ошибка создания {class_name}: {e}")
                    continue
            
            # Если не удалось загрузить, создаем заглушку
            self.logger.warning("⚠️ Старый бот не найден, создаем заглушку")
            return self._create_bot_stub()
            
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка загрузки старого бота: {e}")
            return None
    
    def _create_bot_stub(self) -> Any:
        """🎭 Создание заглушки бота"""
        class BotStub:
            def __init__(self):
                self.name = "BotStub"
                self.is_running = False
            
            def run(self):
                print("🎭 Запуск заглушки бота")
                self.is_running = True
            
            def stop(self):
                print("🎭 Остановка заглушки бота")
                self.is_running = False
            
            def get_balance(self):
                return {'EUR': 1000.0, 'DOGE': 5000.0}
            
            def get_current_price(self):
                return 0.18
            
            def execute_strategy(self):
                return {'action': 'hold', 'reason': 'Заглушка бота'}
        
        return BotStub()
    
    async def _load_legacy_config(self) -> Dict[str, Any]:
        """⚙️ Загрузка старой конфигурации"""
        try:
            self.logger.info("⚙️ Загрузка старой конфигурации...")
            
            config_modules = ['config', 'settings', 'bot_config']
            legacy_config = {}
            
            for module_name in config_modules:
                try:
                    module = __import__(module_name)
                    
                    # Извлекаем все переменные, не начинающиеся с _
                    for attr_name in dir(module):
                        if not attr_name.startswith('_'):
                            attr_value = getattr(module, attr_name)
                            # Пропускаем функции и классы
                            if not callable(attr_value) and not isinstance(attr_value, type):
                                legacy_config[attr_name] = attr_value
                    
                    self.logger.info(f"✅ Загружена конфигурация из {module_name}")
                    break
                    
                except ImportError:
                    self.logger.debug(f"⚠️ Модуль {module_name} не найден")
                    continue
            
            # Добавляем значения по умолчанию
            default_config = {
                'api_key': 'test_key',
                'api_secret': 'test_secret',
                'trading_pair': 'DOGE_EUR',
                'position_size': 100,
                'dca_enabled': True,
                'stop_loss_percent': 15.0
            }
            
            for key, value in default_config.items():
                if key not in legacy_config:
                    legacy_config[key] = value
            
            self.logger.info(f"✅ Загружено {len(legacy_config)} параметров конфигурации")
            return legacy_config
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки конфигурации: {e}")
            return {}
    
    async def _load_legacy_strategies(self) -> List[Any]:
        """🎯 Загрузка старых стратегий"""
        try:
            self.logger.info("🎯 Загрузка старых стратегий...")
            
            strategies = []
            strategy_modules = [
                'adaptive_dca_strategy',
                'pyramid_strategy',
                'trailing_stop',
                'strategies'
            ]
            
            for module_name in strategy_modules:
                try:
                    module = __import__(module_name)
                    self.legacy_modules[module_name] = module
                    
                    # Ищем классы стратегий
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and 
                            'strategy' in attr_name.lower() and
                            not attr_name.startswith('_')):
                            strategies.append({
                                'name': attr_name,
                                'class': attr,
                                'module': module_name
                            })
                            self.logger.debug(f"🎯 Найдена стратегия: {attr_name}")
                
                except ImportError:
                    self.logger.debug(f"⚠️ Модуль стратегий {module_name} не найден")
                    continue
                except Exception as e:
                    self.logger.warning(f"⚠️ Ошибка загрузки стратегий из {module_name}: {e}")
                    continue
            
            self.logger.info(f"✅ Найдено {len(strategies)} старых стратегий")
            return strategies
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки стратегий: {e}")
            return []
    
    async def execute_cycle(self) -> Dict[str, Any]:
        """🔄 Выполнение цикла старого бота"""
        try:
            if not self.is_initialized:
                raise AdapterExecutionError("Legacy адаптер не инициализирован")
            
            self.logger.info("🔄 Выполнение цикла Legacy бота...")
            
            cycle_result = {
                'success': False,
                'timestamp': datetime.now().isoformat(),
                'legacy_bot_available': self.legacy_bot is not None,
                'hybrid_mode': self.use_hybrid
            }
            
            if self.legacy_bot:
                # Выполняем цикл старого бота
                legacy_result = await self._execute_legacy_cycle()
                cycle_result.update(legacy_result)
            else:
                # Гибридный режим или заглушка
                hybrid_result = await self._execute_hybrid_cycle()
                cycle_result.update(hybrid_result)
            
            cycle_result['success'] = True
            return cycle_result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка выполнения цикла: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    async def _execute_legacy_cycle(self) -> Dict[str, Any]:
        """🤖 Выполнение цикла старого бота"""
        try:
            result = {'legacy_execution': True}
            
            # Получаем баланс
            if hasattr(self.legacy_bot, 'get_balance'):
                balance = await self.safe_execute(self.legacy_bot.get_balance)
                result['balance'] = balance
            
            # Получаем текущую цену
            if hasattr(self.legacy_bot, 'get_current_price'):
                price = await self.safe_execute(self.legacy_bot.get_current_price)
                result['current_price'] = price
            
            # Выполняем стратегию
            if hasattr(self.legacy_bot, 'execute_strategy'):
                strategy_result = await self.safe_execute(self.legacy_bot.execute_strategy)
                result['strategy_result'] = strategy_result
            
            # Проверяем DCA
            if hasattr(self.legacy_bot, 'check_dca'):
                dca_result = await self.safe_execute(self.legacy_bot.check_dca)
                result['dca_result'] = dca_result
            
            self.logger.info("✅ Legacy цикл выполнен")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка legacy цикла: {e}")
            return {'legacy_execution': False, 'error': str(e)}
    
    async def _execute_hybrid_cycle(self) -> Dict[str, Any]:
        """🔀 Выполнение гибридного цикла"""
        try:
            self.logger.info("🔀 Выполнение гибридного цикла...")
            
            # Используем новую архитектуру с адаптацией старых данных
            result = {
                'hybrid_execution': True,
                'config_loaded': len(self.legacy_config) > 0,
                'strategies_loaded': len(self.legacy_modules) > 0
            }
            
            # Адаптируем старую конфигурацию
            adapted_config = self._adapt_legacy_config()
            result['adapted_config'] = adapted_config
            
            # Симулируем выполнение с адаптированной конфигурацией
            execution_result = await self._simulate_execution(adapted_config)
            result.update(execution_result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка гибридного цикла: {e}")
            return {'hybrid_execution': False, 'error': str(e)}
    
    def _adapt_legacy_config(self) -> Dict[str, Any]:
        """🔄 Адаптация старой конфигурации"""
        try:
            adapted = {}
            
            # Мапинг старых параметров на новые
            config_mapping = {
                'api_key': 'exmo_api_key',
                'api_secret': 'exmo_api_secret',
                'trading_pair': 'trading_pair',
                'position_size': 'position_size_percent',
                'dca_enabled': 'dca_enabled',
                'stop_loss_percent': 'stop_loss_percent'
            }
            
            for old_key, new_key in config_mapping.items():
                if old_key in self.legacy_config:
                    adapted[new_key] = self.legacy_config[old_key]
            
            # Добавляем значения по умолчанию для новых параметров
            defaults = {
                'trading_profile': 'balanced',
                'trading_mode': 'paper',
                'max_position_size_percent': 50.0,
                'take_profit_percent': 25.0
            }
            
            for key, value in defaults.items():
                if key not in adapted:
                    adapted[key] = value
            
            self.logger.debug(f"🔄 Адаптировано {len(adapted)} параметров конфигурации")
            return adapted
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка адаптации конфигурации: {e}")
            return {}
    
    async def _simulate_execution(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """🎭 Симуляция выполнения с адаптированной конфигурацией"""
        try:
            # Симулируем торговый цикл
            import random
            
            result = {
                'market_data': {
                    'price': 0.18 + random.uniform(-0.01, 0.01),
                    'volume': random.randint(1000000, 5000000),
                    'timestamp': datetime.now().isoformat()
                },
                'analysis': {
                    'action': random.choice(['hold', 'buy', 'sell']),
                    'confidence': random.uniform(0.3, 0.9),
                    'reason': 'Адаптированный анализ'
                },
                'config_used': config
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка симуляции: {e}")
            return {'simulation_error': str(e)}
    
    async def cleanup(self) -> None:
        """🧹 Очистка ресурсов"""
        try:
            self.logger.info("🧹 Очистка Legacy адаптера...")
            
            # Останавливаем старый бот если запущен
            if self.legacy_bot and hasattr(self.legacy_bot, 'stop'):
                await self.safe_execute(self.legacy_bot.stop)
            
            # Очищаем ссылки
            self.legacy_bot = None
            self.legacy_modules.clear()
            self.legacy_config.clear()
            
            self.is_initialized = False
            self.is_running = False
            
            self.logger.info("✅ Legacy адаптер очищен")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка очистки Legacy адаптера: {e}")
    
    def get_legacy_bot(self) -> Optional[Any]:
        """🤖 Получение экземпляра старого бота"""
        return self.legacy_bot
    
    def get_legacy_config(self) -> Dict[str, Any]:
        """⚙️ Получение старой конфигурации"""
        return self.legacy_config.copy()
    
    def get_legacy_modules(self) -> Dict[str, Any]:
        """📦 Получение загруженных модулей"""
        return self.legacy_modules.copy()
    
    async def run_legacy_bot(self) -> None:
        """🚀 Запуск старого бота"""
        try:
            if not self.legacy_bot:
                raise AdapterExecutionError("Legacy бот не доступен")
            
            self.logger.info("🚀 Запуск старого бота...")
            self.is_running = True
            
            # Пытаемся запустить старый бот
            if hasattr(self.legacy_bot, 'run'):
                await self.safe_execute(self.legacy_bot.run)
            elif hasattr(self.legacy_bot, 'start'):
                await self.safe_execute(self.legacy_bot.start)
            elif hasattr(self.legacy_bot, 'main_loop'):
                await self.safe_execute(self.legacy_bot.main_loop)
            else:
                self.logger.warning("⚠️ Не найден метод запуска в старом боте")
                
        except KeyboardInterrupt:
            self.logger.info("⌨️ Остановка старого бота по запросу пользователя")
        except Exception as e:
            self.logger.error(f"❌ Ошибка запуска старого бота: {e}")
            raise
        finally:
            self.is_running = False
