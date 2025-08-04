#!/usr/bin/env python3
"""🧪 Базовая конфигурация для pytest"""

import pytest
import sys
from pathlib import Path

# Добавляем src в путь
src_path = Path(__file__).parent.parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

@pytest.fixture
def sample_config():
    """Базовая конфигурация для тестов"""
    return {
        "api_key": "test_key",
        "api_secret": "test_secret",
        "pair": "DOGE_EUR",
        "test_mode": True
    }

@pytest.fixture
def sample_market_data():
    """Тестовые рыночные данные"""
    return {
        "current_price": 0.18,
        "balance": 1000.0,
        "timestamp": 1234567890
    }
