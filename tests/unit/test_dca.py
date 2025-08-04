#!/usr/bin/env python3
"""🧪 Unit тесты DCA стратегии"""
import pytest
from decimal import Decimal
from datetime import datetime

@pytest.mark.unit
@pytest.mark.dca
def test_dca_config(mock_dca_config):
    """Тест DCA конфигурации"""
    assert mock_dca_config.enabled is True
    assert mock_dca_config.step_percent == Decimal("5.0")
    assert mock_dca_config.max_steps == 5
    assert mock_dca_config.step_multiplier == Decimal("1.5")

@pytest.mark.unit
@pytest.mark.dca
def test_dca_state_structure(mock_dca_state):
    """Тест структуры состояния DCA"""
    required_fields = ['pair', 'base_price', 'current_step', 'total_invested', 
                      'total_amount', 'average_price', 'unrealized_pnl', 'steps']
    
    for field in required_fields:
        assert field in mock_dca_state
    
    assert isinstance(mock_dca_state['base_price'], Decimal)
    assert isinstance(mock_dca_state['current_step'], int)
    assert isinstance(mock_dca_state['steps'], list)

@pytest.mark.unit
@pytest.mark.dca
def test_dca_calculations(mock_dca_state, test_utils):
    """Тест расчетов DCA"""
    # Проверяем логику расчетов
    total_cost = sum(step['amount'] * step['price'] for step in mock_dca_state['steps'])
    total_amount = sum(step['amount'] for step in mock_dca_state['steps'])
    
    if total_amount > 0:
        expected_avg_price = total_cost / total_amount
        test_utils.assert_decimal_equal(
            mock_dca_state['average_price'], 
            expected_avg_price,
            places=4
        )

@pytest.mark.unit
@pytest.mark.dca
def test_dca_step_validation(mock_dca_config):
    """Тест валидации шагов DCA"""
    assert mock_dca_config.step_percent > 0
    assert mock_dca_config.max_steps > 0
    assert mock_dca_config.step_multiplier >= 1
    assert mock_dca_config.recovery_threshold_percent > 0
