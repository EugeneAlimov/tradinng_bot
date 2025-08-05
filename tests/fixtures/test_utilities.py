from decimal import Decimal
from datetime import datetime, timedelta
import json
from pathlib import Path
import random

class TestDataGenerator:
    """🏭 Генератор тестовых данных"""
    
    @staticmethod
    def generate_price_history(days=30, base_price=0.18, volatility=0.02):
        """Генерация истории цен"""
        history = []
        current_price = Decimal(str(base_price))
        current_time = datetime.now() - timedelta(days=days)
        
        for i in range(days * 24):  # Почасовые данные
            # Добавляем волатильность
            change = Decimal(str(random.uniform(-volatility, volatility)))
            current_price += current_price * change
            
            # Не даем цене стать отрицательной
            if current_price <= 0:
                current_price = Decimal('0.01')
            
            history.append({
                'timestamp': current_time + timedelta(hours=i),
                'price': current_price,
                'volume': Decimal(str(random.randint(100000, 1000000)))
            })
        
        return history
    
    @staticmethod
    def generate_trade_sequence(count=10):
        """Генерация последовательности сделок"""
        trades = []
        base_price = Decimal('0.18')
        
        for i in range(count):
            trade_type = 'buy' if i % 2 == 0 else 'sell'
            price_modifier = Decimal('0.001') if trade_type == 'buy' else Decimal('-0.001')
            
            trades.append({
                'id': f'trade_{i+1}',
                'type': trade_type,
                'amount': Decimal(str(100 + i * 10)),
                'price': base_price + price_modifier * i,
                'timestamp': datetime.now() - timedelta(hours=count-i),
                'fee': Decimal('0.1')
            })
        
        return trades

# Предустановленные наборы данных
SAMPLE_SCENARIOS = {
    'bull_market': {
        'price_trend': 'up',
        'volatility': 0.05,
        'volume_trend': 'increasing'
    },
    'bear_market': {
        'price_trend': 'down', 
        'volatility': 0.08,
        'volume_trend': 'decreasing'
    },
    'sideways': {
        'price_trend': 'flat',
        'volatility': 0.02,
        'volume_trend': 'stable'
    }
}

def create_test_environment(scenario='balanced'):
    """Создание тестового окружения"""
    return {
        'api_client': 'mock',
        'strategy': 'test_strategy',
        'risk_manager': 'conservative',
        'scenario': scenario,
        'start_balance': {'EUR': 1000, 'DOGE': 5000}
    }
