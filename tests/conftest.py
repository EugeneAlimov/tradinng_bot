import pytest
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock
import asyncio

# Добавляем src в путь для всех тестов
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

@pytest.fixture
def event_loop():
    """Фикстура event loop for async tests"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_config():
    """⚙️ Базовая мок конфигурация"""
    class MockConfig:
        def __init__(self):
            # Exchange API
            self.exchange = Mock()
            self.exchange.api_key = "test_api_key_12345"
            self.exchange.api_secret = "test_api_secret_67890"
            self.exchange.base_url = "https://api.exmo.com/v1"
            
            # Trading basic settings
            self.trading = Mock()
            self.trading.position_size_percent = Decimal("6.0")
            self.trading.max_position_size_percent = Decimal("50.0")
            self.trading.stop_loss_percent = Decimal("15.0")
            self.trading.take_profit_percent = Decimal("25.0")
            self.trading.min_profit_percent = Decimal("0.8")
            
        def validate(self):
            """Базовая валидация"""
            if not self.exchange.api_key or len(self.exchange.api_key) < 10:
                raise ValueError("API key слишком короткий")
            if not self.exchange.api_secret or len(self.exchange.api_secret) < 10:
                raise ValueError("API secret слишком короткий")
            return True
    
    return MockConfig()

@pytest.fixture
def mock_market_data():
    """📊 Базовые рыночные данные"""
    return {
        'DOGE_EUR': {
            'bid': Decimal('0.18000'),
            'ask': Decimal('0.18010'),
            'last': Decimal('0.18005'),
            'volume': Decimal('1234567.89'),
            'timestamp': int(datetime.now().timestamp())
        }
    }

@pytest.fixture
def mock_balance():
    """💰 Базовый баланс"""
    return {
        'EUR': {
            'available': Decimal('1000.00'),
            'reserved': Decimal('0.00')
        },
        'DOGE': {
            'available': Decimal('5000.00'),
            'reserved': Decimal('0.00')
        }
    }

@pytest.fixture
def mock_order():
    """📋 Базовый ордер"""
    return {
        'order_id': '12345',
        'pair': 'DOGE_EUR',
        'type': 'buy',
        'amount': Decimal('100.00'),
        'price': Decimal('0.18000'),
        'status': 'open',
        'created': datetime.now(),
        'updated': datetime.now()
    }

@pytest.fixture
def mock_api_client():
    """🔌 Базовый API клиент"""
    client = AsyncMock()
    
    # Базовые методы
    client.get_ticker = AsyncMock(return_value={'DOGE_EUR': {'last': '0.18005', 'volume': '1000000'}})
    client.get_balance = AsyncMock(return_value={'EUR': {'available': '1000'}, 'DOGE': {'available': '5000'}})
    client.create_order = AsyncMock(return_value={'order_id': '12345', 'status': 'open'})
    client.cancel_order = AsyncMock(return_value={'success': True})
    client.get_order_status = AsyncMock(return_value={'status': 'filled', 'filled_amount': '100'})
    
    return client

# Утилиты для тестов
class TestUtils:
    """🛠️ Базовые утилиты для тестирования"""
    
    @staticmethod
    def create_test_order(order_type='buy', amount='100', price='0.18'):
        """Создание тестового ордера"""
        return {
            'order_id': f'test_{datetime.now().timestamp()}',
            'pair': 'DOGE_EUR',
            'type': order_type,
            'amount': Decimal(amount),
            'price': Decimal(price),
            'status': 'open',
            'created': datetime.now()
        }
    
    @staticmethod
    def assert_decimal_equal(actual, expected, places=5):
        """Сравнение Decimal с точностью"""
        assert abs(actual - expected) < Decimal(10) ** -places, f"Expected {expected}, got {actual}"
    
    @staticmethod
    async def wait_for_condition(condition_func, timeout=5, interval=0.1):
        """Ожидание выполнения условия"""
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            if await condition_func() if asyncio.iscoroutinefunction(condition_func) else condition_func():
                return True
            await asyncio.sleep(interval)
        return False

@pytest.fixture
def test_utils():
    """🛠️ Фикстура утилит"""
    return TestUtils()
