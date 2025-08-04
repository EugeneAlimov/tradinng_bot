#!/usr/bin/env python3
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
