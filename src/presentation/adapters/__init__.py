"""🔄 Адаптеры совместимости"""

from .base_adapter import BaseAdapter
from .safe_adapter import SafeAdapter
from .legacy_bot_adapter import LegacyBotAdapter

__all__ = [
    'BaseAdapter',
    'SafeAdapter', 
    'LegacyBotAdapter'
]
