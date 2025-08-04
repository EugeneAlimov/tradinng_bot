#!/usr/bin/env python3
"""🔄 Миграция Part 8C - Главный адаптер и утилиты"""
import logging
from pathlib import Path

class Migration:
    """🔄 Создание главного адаптера и утилит"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.adapters_dir = project_root / "src" / "presentation" / "adapters"
        self.logger = logging.getLogger(__name__)
    
    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("🔄 Создание главного адаптера и утилит...")
            
            # Создаем главный адаптер
            self._create_main_adapter()
            
            # Создаем адаптер режимов
            self._create_mode_adapter()
            
            # Создаем утилиты адаптеров
            self._create_adapter_utils()
            
            self.logger.info("✅ Главный адаптер и утилиты созданы")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания адаптера: {e}")
            return False
    
    def _create_main_adapter(self):
        """🎯 Создание главного адаптера"""
        main_adapter_content = '''#!/usr/bin/env python3
"""🎯 Главный адаптер системы"""

import asyncio
from typing import Any, Dict, Optional, List
from datetime import datetime
from enum import Enum

from .base_adapter import BaseAdapter, AdapterError
from .safe_adapter import SafeAdapter
from .legacy_bot_adapter import LegacyBotAdapter
from .strategy_adapter import StrategyAdapter


class AdapterMode(Enum):
    """🔧 Режимы работы адаптера"""
    SAFE = "safe"
    LEGACY = "legacy"
    HYBRID = "hybrid"
    NEW = "new"


class MainAdapter(BaseAdapter):
    """🎯 Главный адаптер системы"""
    
    def __init__(self, mode: AdapterMode = AdapterMode.HYBRID):
        super().__init__("MainAdapter")
        self.mode = mode
        self.sub_adapters: Dict[str, BaseAdapter] = {}
        self.active_adapter: Optional[BaseAdapter] = None
        self.cycle_count = 0
        
        self.logger.info(f"🎯 Главный адаптер создан в режиме: {mode.value}")
    
    async def initialize(self) -> bool:
        """🚀 Инициализация главного адаптера"""
        try:
            self.logger.info(f"🚀 Инициализация в режиме {self.mode.value}...")
            
            # Создаем и инициализируем подадаптеры в зависимости от режима
            if self.mode == AdapterMode.SAFE:
                await self._initialize_safe_mode()
            elif self.mode == AdapterMode.LEGACY:
                await self._initialize_legacy_mode()
            elif self.mode == AdapterMode.HYBRID:
                await self._initialize_hybrid_mode()
            elif self.mode == AdapterMode.NEW:
                await self._initialize_new_mode()
            
            self.is_initialized = True
            self.logger.info("✅ Главный адаптер инициализирован")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации главного адаптера: {e}")
            return False
    
    async def _initialize_safe_mode(self) -> None:
        """🛡️ Инициализация безопасного режима"""
        self.logger.info("🛡️ Инициализация безопасного режима...")
        
        safe_adapter = SafeAdapter()
        await safe_adapter.initialize()
        
        self.sub_adapters['safe'] = safe_adapter
        self.active_adapter = safe_adapter
        
        self.logger.info("✅ Безопасный режим инициализирован")
    
    async def _initialize_legacy_mode(self) -> None:
        """🤖 Инициализация legacy режима"""
        self.logger.info("🤖 Инициализация legacy режима...")
        
        legacy_adapter = LegacyBotAdapter(use_hybrid=False)
        await legacy_adapter.initialize()
        
        self.sub_adapters['legacy'] = legacy_adapter
        self.active_adapter = legacy_adapter
        
        self.logger.info("✅ Legacy режим инициализирован")
    
    async def _initialize_hybrid_mode(self) -> None:
        """🔀 Инициализация гибридного режима"""
        self.logger.info("🔀 Инициализация гибридного режима...")
        
        # Инициализируем несколько адаптеров
        safe_adapter = SafeAdapter()
        legacy_adapter = LegacyBotAdapter(use_hybrid=True)
        strategy_adapter = StrategyAdapter()
        
        # Инициализируем все адаптеры
        adapters_to_init = [
            ('safe', safe_adapter),
            ('legacy', legacy_adapter),
            ('strategy', strategy_adapter)
        ]
        
        initialized_count = 0
        for name, adapter in adapters_to_init:
            try:
                if await adapter.initialize():
                    self.sub_adapters[name] = adapter
                    initialized_count += 1
                    self.logger.info(f"✅ {name} адаптер инициализирован")
                else:
                    self.logger.warning(f"⚠️ {name} адаптер не инициализирован")
            except Exception as e:
                self.logger.warning(f"⚠️ Ошибка инициализации {name} адаптера: {e}")
        
        # Выбираем основной адаптер
        if 'legacy' in self.sub_adapters:
            self.active_adapter = self.sub_adapters['legacy']
        elif 'safe' in self.sub_adapters:
            self.active_adapter = self.sub_adapters['safe']
        
        self.logger.info(f"✅ Гибридный режим инициализирован ({initialized_count} адаптеров)")
    
    async def _initialize_new_mode(self) -> None:
        """🆕 Инициализация нового режима"""
        self.logger.info("🆕 Инициализация нового режима...")
        
        # В новом режиме используем только новую архитектуру
        strategy_adapter = StrategyAdapter()
        await strategy_adapter.initialize()
        
        self.sub_adapters['strategy'] = strategy_adapter
        self.active_adapter = strategy_adapter
        
        self.logger.info("✅ Новый режим инициализирован")
    
    async def execute_cycle(self) -> Dict[str, Any]:
        """🔄 Выполнение главного цикла"""
        try:
            if not self.is_initialized:
                raise AdapterError("Главный адаптер не инициализирован")
            
            self.cycle_count += 1
            self.logger.info(f"🔄 Выполнение главного цикла #{self.cycle_count}")
            
            cycle_result = {
                'success': False,
                'cycle': self.cycle_count,
                'mode': self.mode.value,
                'timestamp': datetime.now().isoformat(),
                'active_adapter': self.active_adapter.name if self.active_adapter else None,
                'sub_adapters_count': len(self.sub_adapters)
            }
            
            # Выполняем цикл активного адаптера
            if self.active_adapter:
                adapter_result = await self.active_adapter.execute_cycle()
                cycle_result['adapter_result'] = adapter_result
                cycle_result['success'] = adapter_result.get('success', False)
            
            # В гибридном режиме собираем данные со всех адаптеров
            if self.mode == AdapterMode.HYBRID:
                hybrid_results = await self._execute_hybrid_cycle()
                cycle_result['hybrid_results'] = hybrid_results
            
            return cycle_result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка выполнения главного цикла: {e}")
            return {
                'success': False,
                'error': str(e),
                'cycle': self.cycle_count,
                'timestamp': datetime.now().isoformat()
            }
    
    async def _execute_hybrid_cycle(self) -> Dict[str, Any]:
        """🔀 Выполнение гибридного цикла"""
        try:
            results = {}
            
            # Выполняем циклы всех доступных адаптеров
            for name, adapter in self.sub_adapters.items():
                try:
                    if adapter != self.active_adapter:  # Не дублируем активный адаптер
                        adapter_result = await adapter.execute_cycle()
                        results[name] = adapter_result
                except Exception as e:
                    self.logger.warning(f"⚠️ Ошибка {name} адаптера: {e}")
                    results[name] = {'success': False, 'error': str(e)}
            
            return results
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка гибридного цикла: {e}")
            return {'error': str(e)}
    
    async def switch_mode(self, new_mode: AdapterMode) -> bool:
        """🔄 Переключение режима работы"""
        try:
            if new_mode == self.mode:
                self.logger.info(f"ℹ️ Already in {new_mode.value} mode")
                return True
            
            self.logger.info(f"🔄 Переключение режима: {self.mode.value} -> {new_mode.value}")
            
            # Очищаем текущие адаптеры
            await self._cleanup_adapters()
            
            # Устанавливаем новый режим
            self.mode = new_mode
            self.is_initialized = False
            
            # Инициализируем в новом режиме
            return await self.initialize()
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка переключения режима: {e}")
            return False
    
    async def _cleanup_adapters(self) -> None:
        """🧹 Очистка всех адаптеров"""
        for name, adapter in self.sub_adapters.items():
            try:
                await adapter.cleanup()
                self.logger.debug(f"🧹 {name} адаптер очищен")
            except Exception as e:
                self.logger.warning(f"⚠️ Ошибка очистки {name} адаптера: {e}")
        
        self.sub_adapters.clear()
        self.active_adapter = None
    
    async def cleanup(self) -> None:
        """🧹 Очистка главного адаптера"""
        self.logger.info("🧹 Очистка главного адаптера...")
        
        await self._cleanup_adapters()
        
        self.cycle_count = 0
        self.is_initialized = False
        
        self.logger.info("✅ Главный адаптер очищен")
    
    def get_status(self) -> Dict[str, Any]:
        """📊 Получение статуса главного адаптера"""
        status = super().get_status()
        
        status.update({
            'mode': self.mode.value,
            'cycle_count': self.cycle_count,
            'active_adapter': self.active_adapter.name if self.active_adapter else None,
            'sub_adapters': {
                name: adapter.get_status() 
                for name, adapter in self.sub_adapters.items()
            }
        })
        
        return status
    
    def get_adapter(self, name: str) -> Optional[BaseAdapter]:
        """🔍 Получение адаптера по имени"""
        return self.sub_adapters.get(name)
    
    def list_adapters(self) -> List[str]:
        """📋 Список доступных адаптеров"""
        return list(self.sub_adapters.keys())
'''
        
        main_adapter_file = self.adapters_dir / "main_adapter.py"
        main_adapter_file.write_text(main_adapter_content)
    
    def _create_mode_adapter(self):
        """🎛️ Создание адаптера режимов"""
        mode_adapter_content = '''#!/usr/bin/env python3
"""🎛️ Адаптер режимов работы"""

import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from .main_adapter import MainAdapter, AdapterMode


class ModeAdapter:
    """🎛️ Адаптер для управления режимами работы"""
    
    def __init__(self):
        self.main_adapter: Optional[MainAdapter] = None
        self.current_mode: Optional[AdapterMode] = None
        self.mode_history: list = []
        self.logger = __import__('logging').getLogger(f"{__name__}.ModeAdapter")
    
    async def initialize_mode(self, mode_name: str) -> bool:
        """🚀 Инициализация режима по имени"""
        try:
            # Преобразуем строку в режим
            mode = self._parse_mode(mode_name)
            if not mode:
                self.logger.error(f"❌ Неизвестный режим: {mode_name}")
                return False
            
            self.logger.info(f"🚀 Инициализация режима: {mode.value}")
            
            # Создаем главный адаптер
            self.main_adapter = MainAdapter(mode)
            
            # Инициализируем
            if await self.main_adapter.initialize():
                self.current_mode = mode
                self._add_to_history(mode, "initialized")
                self.logger.info(f"✅ Режим {mode.value} инициализирован")
                return True
            else:
                self.logger.error(f"❌ Не удалось инициализировать режим {mode.value}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации режима {mode_name}: {e}")
            return False
    
    def _parse_mode(self, mode_name: str) -> Optional[AdapterMode]:
        """🔍 Парсинг названия режима"""
        mode_mapping = {
            'safe': AdapterMode.SAFE,
            'paper': AdapterMode.SAFE,  # Алиас
            'legacy': AdapterMode.LEGACY,
            'old': AdapterMode.LEGACY,  # Алиас
            'hybrid': AdapterMode.HYBRID,
            'mixed': AdapterMode.HYBRID,  # Алиас
            'new': AdapterMode.NEW,
            'modern': AdapterMode.NEW  # Алиас
        }
        
        return mode_mapping.get(mode_name.lower())
    
    async def switch_mode(self, new_mode_name: str) -> bool:
        """🔄 Переключение режима"""
        try:
            new_mode = self._parse_mode(new_mode_name)
            if not new_mode:
                self.logger.error(f"❌ Неизвестный режим: {new_mode_name}")
                return False
            
            if not self.main_adapter:
                self.logger.warning("⚠️ Главный адаптер не инициализирован, создаем новый")
                return await self.initialize_mode(new_mode_name)
            
            # Переключаем режим
            if await self.main_adapter.switch_mode(new_mode):
                old_mode = self.current_mode
                self.current_mode = new_mode
                self._add_to_history(new_mode, f"switched_from_{old_mode.value if old_mode else 'none'}")
                self.logger.info(f"✅ Режим переключен на {new_mode.value}")
                return True
            else:
                self.logger.error(f"❌ Не удалось переключить режим на {new_mode.value}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка переключения режима: {e}")
            return False
    
    async def execute_cycle(self) -> Dict[str, Any]:
        """🔄 Выполнение цикла текущего режима"""
        try:
            if not self.main_adapter:
                return {
                    'success': False,
                    'error': 'Главный адаптер не инициализирован',
                    'timestamp': datetime.now().isoformat()
                }
            
            result = await self.main_adapter.execute_cycle()
            result['mode_adapter'] = {
                'current_mode': self.current_mode.value if self.current_mode else None,
                'history_count': len(self.mode_history)
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка выполнения цикла: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def _add_to_history(self, mode: AdapterMode, action: str) -> None:
        """📝 Добавление записи в историю режимов"""
        self.mode_history.append({
            'mode': mode.value,
            'action': action,
            'timestamp': datetime.now().isoformat()
        })
        
        # Ограничиваем историю 100 записями
        if len(self.mode_history) > 100:
            self.mode_history = self.mode_history[-100:]
    
    def get_status(self) -> Dict[str, Any]:
        """📊 Получение статуса адаптера режимов"""
        status = {
            'current_mode': self.current_mode.value if self.current_mode else None,
            'main_adapter_initialized': self.main_adapter is not None,
            'history_count': len(self.mode_history),
            'available_modes': [mode.value for mode in AdapterMode]
        }
        
        if self.main_adapter:
            status['main_adapter_status'] = self.main_adapter.get_status()
        
        return status
    
    def get_mode_history(self) -> list:
        """📈 Получение истории режимов"""
        return self.mode_history.copy()
    
    async def cleanup(self) -> None:
        """🧹 Очистка адаптера режимов"""
        self.logger.info("🧹 Очистка адаптера режимов...")
        
        if self.main_adapter:
            await self.main_adapter.cleanup()
            self.main_adapter = None
        
        self.current_mode = None
        self.mode_history.clear()
        
        self.logger.info("✅ Адаптер режимов очищен")
    
    def validate_mode(self, mode_name: str) -> bool:
        """✅ Валидация названия режима"""
        return self._parse_mode(mode_name) is not None
    
    def get_available_modes(self) -> list:
        """📋 Получение списка доступных режимов"""
        return [
            {
                'name': mode.value,
                'aliases': self._get_mode_aliases(mode),
                'description': self._get_mode_description(mode),
                'current': mode == self.current_mode
            }
            for mode in AdapterMode
        ]
    
    def _get_mode_aliases(self, mode: AdapterMode) -> list:
        """🏷️ Получение алиасов режима"""
        aliases_map = {
            AdapterMode.SAFE: ['paper'],
            AdapterMode.LEGACY: ['old'],
            AdapterMode.HYBRID: ['mixed'],
            AdapterMode.NEW: ['modern']
        }
        return aliases_map.get(mode, [])
    
    def _get_mode_description(self, mode: AdapterMode) -> str:
        """📝 Получение описания режима"""
        descriptions = {
            AdapterMode.SAFE: "Безопасный режим с симуляцией торговли",
            AdapterMode.LEGACY: "Режим совместимости со старым ботом",
            AdapterMode.HYBRID: "Гибридный режим с новой и старой архитектурой",
            AdapterMode.NEW: "Новый режим с современной архитектурой"
        }
        return descriptions.get(mode, "Неизвестный режим")
'''
        
        mode_adapter_file = self.adapters_dir / "mode_adapter.py"
        mode_adapter_file.write_text(mode_adapter_content)
    
    def _create_adapter_utils(self):
        """🛠️ Создание утилит адаптеров"""
        utils_content = '''#!/usr/bin/env python3
"""🛠️ Утилиты для адаптеров"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime, timedelta
from pathlib import Path


class AdapterRegistry:
    """📋 Реестр адаптеров"""
    
    def __init__(self):
        self._adapters: Dict[str, Any] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self.logger = logging.getLogger(f"{__name__}.AdapterRegistry")
    
    def register(self, name: str, adapter: Any, metadata: Optional[Dict[str, Any]] = None) -> None:
        """📝 Регистрация адаптера"""
        self._adapters[name] = adapter
        self._metadata[name] = metadata or {}
        self._metadata[name]['registered_at'] = datetime.now().isoformat()
        
        self.logger.info(f"📝 Адаптер зарегистрирован: {name}")
    
    def unregister(self, name: str) -> bool:
        """🗑️ Удаление адаптера из реестра"""
        if name in self._adapters:
            del self._adapters[name]
            del self._metadata[name]
            self.logger.info(f"🗑️ Адаптер удален: {name}")
            return True
        return False
    
    def get(self, name: str) -> Optional[Any]:
        """🔍 Получение адаптера по имени"""
        return self._adapters.get(name)
    
    def list_adapters(self) -> List[str]:
        """📋 Список зарегистрированных адаптеров"""
        return list(self._adapters.keys())
    
    def get_metadata(self, name: str) -> Dict[str, Any]:
        """📊 Получение метаданных адаптера"""
        return self._metadata.get(name, {})


class AdapterHealthChecker:
    """🏥 Проверка здоровья адаптеров"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.AdapterHealthChecker")
        self._health_checks: Dict[str, Callable] = {}
        self._last_check: Dict[str, datetime] = {}
        self._check_results: Dict[str, Dict[str, Any]] = {}
    
    def register_health_check(self, adapter_name: str, check_func: Callable) -> None:
        """📝 Регистрация проверки здоровья"""
        self._health_checks[adapter_name] = check_func
        self.logger.info(f"📝 Проверка здоровья зарегистрирована для: {adapter_name}")
    
    async def check_adapter_health(self, adapter_name: str) -> Dict[str, Any]:
        """🏥 Проверка здоровья конкретного адаптера"""
        if adapter_name not in self._health_checks:
            return {'status': 'unknown', 'reason': 'No health check registered'}
        
        try:
            check_func = self._health_checks[adapter_name]
            
            # Выполняем проверку с таймаутом
            result = await asyncio.wait_for(
                self._safe_execute_check(check_func),
                timeout=10.0
            )
            
            health_result = {
                'status': 'healthy' if result.get('success', False) else 'unhealthy',
                'timestamp': datetime.now().isoformat(),
                'details': result,
                'adapter': adapter_name
            }
            
            self._last_check[adapter_name] = datetime.now()
            self._check_results[adapter_name] = health_result
            
            return health_result
            
        except asyncio.TimeoutError:
            health_result = {
                'status': 'timeout',
                'timestamp': datetime.now().isoformat(),
                'reason': 'Health check timed out',
                'adapter': adapter_name
            }
            
            self._check_results[adapter_name] = health_result
            return health_result
            
        except Exception as e:
            health_result = {
                'status': 'error',
                'timestamp': datetime.now().isoformat(),
                'error': str(e),
                'adapter': adapter_name
            }
            
            self._check_results[adapter_name] = health_result
            return health_result
    
    async def _safe_execute_check(self, check_func: Callable) -> Dict[str, Any]:
        """🛡️ Безопасное выполнение проверки"""
        try:
            if asyncio.iscoroutinefunction(check_func):
                return await check_func()
            else:
                return check_func()
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def check_all_adapters(self) -> Dict[str, Dict[str, Any]]:
        """🏥 Проверка здоровья всех адаптеров"""
        results = {}
        
        for adapter_name in self._health_checks.keys():
            results[adapter_name] = await self.check_adapter_health(adapter_name)
        
        return results
    
    def get_last_check_time(self, adapter_name: str) -> Optional[datetime]:
        """⏰ Время последней проверки"""
        return self._last_check.get(adapter_name)
    
    def get_check_result(self, adapter_name: str) -> Dict[str, Any]:
        """📊 Результат последней проверки"""
        return self._check_results.get(adapter_name, {})


class AdapterMetrics:
    """📊 Метрики адаптеров"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.AdapterMetrics")
        self._metrics: Dict[str, List[Dict[str, Any]]] = {}
        self._start_times: Dict[str, datetime] = {}
    
    def start_cycle(self, adapter_name: str) -> None:
        """🚀 Начало цикла адаптера"""
        self._start_times[adapter_name] = datetime.now()
    
    def end_cycle(self, adapter_name: str, success: bool = True, **kwargs) -> None:
        """🏁 Конец цикла адаптера"""
        if adapter_name not in self._start_times:
            self.logger.warning(f"⚠️ Не найдено время начала для {adapter_name}")
            return
        
        start_time = self._start_times[adapter_name]
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        metric = {
            'timestamp': end_time.isoformat(),
            'duration_seconds': duration,
            'success': success,
            **kwargs
        }
        
        if adapter_name not in self._metrics:
            self._metrics[adapter_name] = []
        
        self._metrics[adapter_name].append(metric)
        
        # Ограничиваем количество метрик
        if len(self._metrics[adapter_name]) > 1000:
            self._metrics[adapter_name] = self._metrics[adapter_name][-1000:]
        
        del self._start_times[adapter_name]
    
    def get_metrics(self, adapter_name: str, hours: int = 24) -> List[Dict[str, Any]]:
        """📊 Получение метрик адаптера"""
        if adapter_name not in self._metrics:
            return []
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        return [
            metric for metric in self._metrics[adapter_name]
            if datetime.fromisoformat(metric['timestamp']) >= cutoff_time
        ]
    
    def get_summary(self, adapter_name: str, hours: int = 24) -> Dict[str, Any]:
        """📈 Сводка по метрикам"""
        metrics = self.get_metrics(adapter_name, hours)
        
        if not metrics:
            return {'total_cycles': 0, 'no_data': True}
        
        durations = [m['duration_seconds'] for m in metrics]
        successful_cycles = sum(1 for m in metrics if m['success'])
        
        return {
            'total_cycles': len(metrics),
            'successful_cycles': successful_cycles,
            'success_rate': successful_cycles / len(metrics),
            'avg_duration': sum(durations) / len(durations),
            'min_duration': min(durations),
            'max_duration': max(durations),
            'period_hours': hours
        }


# Глобальные экземпляры утилит
adapter_registry = AdapterRegistry()
adapter_health_checker = AdapterHealthChecker()
adapter_metrics = AdapterMetrics()


def get_adapter_registry() -> AdapterRegistry:
    """📋 Получение глобального реестра адаптеров"""
    return adapter_registry


def get_health_checker() -> AdapterHealthChecker:
    """🏥 Получение глобального чекера здоровья"""
    return adapter_health_checker


def get_metrics_collector() -> AdapterMetrics:
    """📊 Получение глобального сборщика метрик"""
    return adapter_metrics
'''
        
        utils_file = self.adapters_dir / "adapter_utils.py"
        utils_file.write_text(utils_content)

if __name__ == "__main__":
    import sys
    migration = Migration(Path("."))
    success = migration.execute()
    sys.exit(0 if success else 1)