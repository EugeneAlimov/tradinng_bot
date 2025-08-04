#!/usr/bin/env python3
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
