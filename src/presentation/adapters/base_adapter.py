#!/usr/bin/env python3
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
