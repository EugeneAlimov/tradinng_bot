#!/usr/bin/env python3
"""⚙️ Новая система конфигурации"""

import os
from dataclasses import dataclass
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

@dataclass
class TradingSettings:
    # API
    exmo_api_key: str = ""
    exmo_api_secret: str = ""

    # Торговля
    position_size_percent: float = 6.0
    min_profit_percent: float = 0.8
    stop_loss_percent: float = 8.0

    # DCA
    dca_enabled: bool = True
    dca_drop_threshold: float = 1.5
    dca_purchase_size: float = 3.0

    def __post_init__(self):
        if not self.exmo_api_key:
            self.exmo_api_key = os.getenv('EXMO_API_KEY', '')
        if not self.exmo_api_secret:
            self.exmo_api_secret = os.getenv('EXMO_API_SECRET', '')

    def validate(self):
        if not self.exmo_api_key or not self.exmo_api_secret:
            raise ValueError("API ключи не настроены")

def get_settings() -> TradingSettings:
    """Получение настроек"""
    return TradingSettings()
