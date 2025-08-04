#!/usr/bin/env python3
"""🔄 Миграция Part 8 - Адаптеры совместимости"""

import logging
from pathlib import Path


class Migration:
    """🔄 Миграция адаптеров"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.src_dir = project_root / "src"
        self.adapters_dir = self.src_dir / "adapters"
        self.logger = logging.getLogger(__name__)

    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("🔄 Создание адаптеров...")
            
            # Создаем структуру директорий
            self._create_directory_structure()
            
            # Создаем адаптер старого бота
            self._create_legacy_bot_adapter()
            
            # Создаем адаптер стратегий
            self._create_strategy_adapter()
            
            # Создаем главный адаптер
            self._create_main_adapter()
            
            self.logger.info("✅ Адаптеры созданы")
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
                init_file.write_text('"""🔄 Адаптеры совместимости"""\n')

    def _create_legacy_bot_adapter(self):
        """🤖 Создание адаптера старого бота"""
        legacy_adapter_content = '''#!/usr/bin/env python3
"""🤖 Адаптер для старого бота"""

import sys
import logging
from pathlib import Path
from typing import Any, Dict, Optional, List

from ..core.interfaces import ILegacyBotAdapter
from ..infrastructure.di_container import injectable


@injectable
class LegacyBotAdapter(ILegacyBotAdapter):
    """🤖 Адаптер для интеграции со старым ботом"""
    
    def __init__(self, use_hybrid: bool = True):
        self.use_hybrid = use_hybrid
        self.logger = logging.getLogger(f"{__name__}.LegacyBotAdapter")
        self.legacy_bot: Optional[Any] = None
        self.legacy_modules: Dict[str, Any] = {}
        
        # Добавляем корневую директорию в путь для импорта старых модулей
        self.project_root = Path(__file__).parent.parent.parent
        if str(self.project_root) not in sys.path:
            sys.path.insert(0, str(self.project_root))
        
        self.logger.info(f"🤖 Legacy адаптер инициализирован (hybrid={use_hybrid})")
    
    def get_legacy_bot(self) -> Any:
        """🤖 Получение экземпляра старого бота"""
        if self.legacy_bot is None:
            self.legacy_bot = self._load_legacy_bot()
        
        return self.legacy_bot
    
    def _load_legacy_bot(self) -> Optional[Any]:
        """📥 Загрузка старого бота"""
        try:
            # Пытаемся загрузить улучшенный бот
            try:
                from bot import ImprovedTradingBot as TradingBot
                self.logger.info("✅ Загружен улучшенный бот (ImprovedTradingBot)")
            except ImportError:
                # Фоллбэк на обычный бот
                try:
                    from bot import TradingBot
                    self.logger.info("✅ Загружен базовый бот (TradingBot)")
                except ImportError:
                    # Последняя попытка - ищем в старых файлах
                    try:
                        from improved_bot import ImprovedTradingBot as TradingBot
                        self.logger.info("✅ Загружен бот из improved_bot.py")
                    except ImportError:
                        self.logger.error("❌ Не удалось найти старый бот")
                        return None
            
            # Создаем экземпляр
            bot = TradingBot()
            self.logger.info("🤖 Экземпляр старого бота создан")
            return bot
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки старого бота: {e}")
            return None
    
    def adapt_strategy_call(self, method_name: str, *args, **kwargs) -> Any:
        """🔄 Адаптация вызова стратегии"""
        try:
            bot = self.get_legacy_bot()
            if not bot:
                raise RuntimeError("Legacy бот не доступен")
            
            if hasattr(bot, method_name):
                method = getattr(bot, method_name)
                result = method(*args, **kwargs)
                
                self.logger.debug(f"🔄 Вызван метод {method_name} старого бота")
                return result
            else:
                self.logger.warning(f"⚠️ Метод {method_name} не найден в старом боте")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка вызова {method_name}: {e}")
            raise
    
    def get_legacy_config(self) -> Dict[str, Any]:
        """⚙️ Получение конфигурации старого бота"""
        try:
            # Пытаемся загрузить старую конфигурацию
            try:
                import config
                legacy_config = {}
                
                # Извлекаем основные параметры
                for attr_name in dir(config):
                    if not attr_name.startswith('_'):
                        legacy_config[attr_name] = getattr(config, attr_name)
                
                self.logger.info("✅ Старая конфигурация загружена")
                return legacy_config
                
            except ImportError:
                self.logger.warning("⚠️ Старая конфигурация не найдена")
                return {}
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки конфигурации: {e}")
            return {}
    
    def get_legacy_strategies(self) -> List[Any]:
        """🎯 Получение стратегий старого бота"""
        try:
            strategies = []
            
            # Пытаемся загрузить старые стратегии
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
                    
                    # Ищем классы стратегий в модуле
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and 
                            'strategy' in attr_name.lower() and
                            not attr_name.startswith('_')):
                            strategies.append(attr)
                            
                except ImportError:
                    self.logger.warning(f"⚠️ Модуль {module_name} не найден")
                    continue
            
            self.logger.info(f"✅ Найдено {len(strategies)} старых стратегий")
            return strategies
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки стратегий: {e}")
            return []
    
    def adapt_position_data(self, legacy_position: Dict[str, Any]) -> Dict[str, Any]:
        """📊 Адаптация данных позиции"""
        try:
            # Преобразуем старый формат позиции в новый
            adapted_position = {
                'currency': legacy_position.get('currency', 'UNKNOWN'),
                'quantity': float(legacy_position.get('quantity', 0)),
                'avg_price': float(legacy_position.get('avg_price', 0)),
                'total_cost': float(legacy_position.get('total_cost', 0)),
                'timestamp': legacy_position.get('timestamp', None),
                'trades': legacy_position.get('trades', [])
            }
            
            return adapted_position
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка адаптации позиции: {e}")
            return {}
    
    def adapt_market_data(self, legacy_data: Dict[str, Any]) -> Dict[str, Any]:
        """📊 Адаптация рыночных данных"""
        try:
            adapted_data = {
                'current_price': float(legacy_data.get('current_price', 0)),
                'balance': float(legacy_data.get('balance', 0)),
                'timestamp': legacy_data.get('timestamp', None)
            }
            
            # Добавляем дополнительные данные если есть
            for key in ['volume_24h', 'high_24h', 'low_24h', 'change_24h']:
                if key in legacy_data:
                    adapted_data[key] = float(legacy_data[key])
            
            return adapted_data
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка адаптации рыночных данных: {e}")
            return {}
    
    def run_legacy_bot(self) -> None:
        """🚀 Запуск старого бота"""
        try:
            bot = self.get_legacy_bot()
            if not bot:
                raise RuntimeError("Legacy бот не доступен")
            
            self.logger.info("🚀 Запуск старого бота...")
            
            # Пытаемся запустить старый бот
            if hasattr(bot, 'run'):
                bot.run()
            elif hasattr(bot, 'start'):
                bot.start()
            elif hasattr(bot, 'main_loop'):
                bot.main_loop()
            else:
                self.logger.error("❌ Не найден метод запуска в старом боте")
                
        except KeyboardInterrupt:
            self.logger.info("⌨️ Остановка старого бота по запросу пользователя")
        except Exception as e:
            self.logger.error(f"❌ Ошибка запуска старого бота: {e}")
            raise
    
    def get_legacy_status(self) -> Dict[str, Any]:
        """📊 Получение статуса старого бота"""
        try:
            bot = self.get_legacy_bot()
            if not bot:
                return {'status': 'unavailable', 'reason': 'Legacy бот не загружен'}
            
            # Пыт