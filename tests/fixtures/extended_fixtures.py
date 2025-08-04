#!/usr/bin/env python3
"""🧪 Расширенные фикстуры для DCA и стратегий"""
import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import Mock

@pytest.fixture
def mock_dca_config():
    """🎯 DCA конфигурация"""
    dca_config = Mock()
    dca_config.enabled = True
    dca_config.step_percent = Decimal("5.0")
    dca_config.max_steps = 5
    dca_config.step_multiplier = Decimal("1.5")
    dca_config.recovery_threshold_percent = Decimal("2.0")
    return dca_config

@pytest.fixture
def mock_dca_state():
    """🎯 Состояние DCA"""
    return {
        'pair': 'DOGE_EUR',
        'base_price': Decimal('0.20000'),
        'current_step': 2,
        'total_invested': Decimal('300.00'),
        'total_amount': Decimal('1600.00'),
        'average_price': Decimal('0.1875'),
        'unrealized_pnl': Decimal('-36.00'),
        'steps': [
            {'step': 1, 'price': Decimal('0.20000'), 'amount': Decimal('500.00'), 'invested': Decimal('100.00')},
            {'step': 2, 'price': Decimal('0.19000'), 'amount': Decimal('526.32'), 'invested': Decimal('100.00')},
            {'step': 3, 'price': Decimal('0.18050'), 'amount': Decimal('553.05'), 'invested': Decimal('100.00')}
        ],
        'last_update': datetime.now()
    }

@pytest.fixture
def mock_risk_config():
    """⚠️ Риск-менеджмент конфигурация"""
    risk_config = Mock()
    risk_config.max_daily_loss_percent = Decimal("10.0")
    risk_config.max_drawdown_percent = Decimal("20.0")
    risk_config.emergency_stop_percent = Decimal("30.0")
    risk_config.position_size_scaling = True
    return risk_config

@pytest.fixture
def mock_trade_history():
    """📈 История торгов"""
    base_time = datetime.now() - timedelta(days=1)
    return [
        {
            'trade_id': f'trade_{i}',
            'pair': 'DOGE_EUR',
            'type': 'buy' if i % 2 == 0 else 'sell',
            'amount': Decimal(f'{100 + i * 10}.00'),
            'price': Decimal(f'0.{18000 + i * 100:05d}'),
            'fee': Decimal(f'{0.1 + i * 0.01:.3f}'),
            'timestamp': base_time + timedelta(hours=i)
        }
        for i in range(10)
    ]

@pytest.fixture
def mock_strategy():
    """📈 Базовая торговая стратегия"""
    strategy = Mock()
    strategy.name = "TestStrategy"
    strategy.analyze = Mock(return_value={'action': 'hold', 'confidence': 0.5, 'reason': 'Тестовый сигнал'})
    strategy.should_buy = Mock(return_value=False)
    strategy.should_sell = Mock(return_value=False)
    return strategy

@pytest.fixture
def mock_risk_manager():
    """⚠️ Риск-менеджер"""
    risk_manager = Mock()
    risk_manager.check_position_size = Mock(return_value=True)
    risk_manager.check_daily_limits = Mock(return_value=True)
    risk_manager.calculate_stop_loss = Mock(return_value=Decimal('0.15300'))
    risk_manager.calculate_take_profit = Mock(return_value=Decimal('0.22500'))
    return risk_manager

@pytest.fixture
def sample_candles():
    """🕯️ Тестовые свечи"""
    base_time = datetime.now() - timedelta(hours=24)
    candles = []
    
    for i in range(24):
        timestamp = base_time + timedelta(hours=i)
        base_price = 0.18 + (i % 3 - 1) * 0.001
        candles.append({
            'timestamp': timestamp,
            'open': Decimal(f'{base_price:.5f}'),
            'high': Decimal(f'{base_price + 0.002:.5f}'),
            'low': Decimal(f'{base_price - 0.002:.5f}'),
            'close': Decimal(f'{base_price + 0.001:.5f}'),
            'volume': Decimal(f'{10000 + i * 1000}')
        })
    
    return candles

@pytest.fixture
def mock_notification_service():
    """📱 Сервис уведомлений"""
    notification = Mock()
    notification.send_telegram = Mock(return_value=True)
    notification.send_email = Mock(return_value=True)
    notification.log_event = Mock()
    return notification
