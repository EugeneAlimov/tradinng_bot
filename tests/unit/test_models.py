#!/usr/bin/env python3
"""🧪 Unit тесты моделей данных"""
import pytest
from decimal import Decimal
from datetime import datetime

@pytest.mark.unit
def test_market_data_structure(mock_market_data):
    """Тест структуры рыночных данных"""
    doge_data = mock_market_data['DOGE_EUR']
    
    required_fields = ['bid', 'ask', 'last', 'volume', 'timestamp']
    for field in required_fields:
        assert field in doge_data
    
    # Проверяем типы
    assert isinstance(doge_data['bid'], Decimal)
    assert isinstance(doge_data['ask'], Decimal)
    assert isinstance(doge_data['last'], Decimal)
    assert isinstance(doge_data['volume'], Decimal)
    assert isinstance(doge_data['timestamp'], int)
    
    # Логические проверки
    assert doge_data['ask'] >= doge_data['bid']
    assert doge_data['volume'] > 0

@pytest.mark.unit
def test_balance_structure(mock_balance):
    """Тест структуры баланса"""
    assert 'EUR' in mock_balance
    assert 'DOGE' in mock_balance
    
    for currency, balance in mock_balance.items():
        assert 'available' in balance
        assert 'reserved' in balance
        assert isinstance(balance['available'], Decimal)
        assert isinstance(balance['reserved'], Decimal)
        assert balance['available'] >= 0
        assert balance['reserved'] >= 0

@pytest.mark.unit
def test_order_structure(mock_order):
    """Тест структуры ордера"""
    required_fields = ['order_id', 'pair', 'type', 'amount', 'price', 'status']
    
    for field in required_fields:
        assert field in mock_order
    
    assert mock_order['type'] in ['buy', 'sell']
    assert mock_order['status'] in ['open', 'filled', 'cancelled', 'partial']
    assert isinstance(mock_order['amount'], Decimal)
    assert isinstance(mock_order['price'], Decimal)
    assert mock_order['amount'] > 0
    assert mock_order['price'] > 0

@pytest.mark.unit
def test_trade_history_structure(mock_trade_history):
    """Тест структуры истории торгов"""
    assert len(mock_trade_history) == 10
    
    for trade in mock_trade_history:
        required_fields = ['trade_id', 'pair', 'type', 'amount', 'price', 'fee', 'timestamp']
        for field in required_fields:
            assert field in trade
        
        assert trade['type'] in ['buy', 'sell']
        assert isinstance(trade['amount'], Decimal)
        assert isinstance(trade['price'], Decimal)
        assert isinstance(trade['fee'], Decimal)
