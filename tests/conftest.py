#!/usr/bin/env python3
"""🧪 Конфигурация pytest"""

import pytest
import sys
from pathlib import Path

# Добавляем src в путь для всех тестов
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

@pytest.fixture
def mock_config():
    """Мок конфигурации для тестов"""
    from decimal import Decimal

    class MockConfig:
        exmo_api_key = "test_key"
        exmo_api_secret = "test_secret"
        position_size_percent = 6.0
        min_profit_percent = 0.8

        def validate(self):
            pass

    return MockConfig()

@pytest.fixture
def sample_market_data():
    """Тестовые рыночные данные"""
    return {
        'current_price': 0.18,
        'balance': 1000.0,
        'timestamp': 1234567890
    }
