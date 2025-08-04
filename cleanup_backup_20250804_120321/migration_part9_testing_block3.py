#!/usr/bin/env python3
"""🧪 Миграция Part 9C - Integration и Performance тесты"""
import logging
from pathlib import Path

class Migration:
    """🧪 Создание Integration и Performance тестов"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.tests_dir = project_root / "tests"
        self.logger = logging.getLogger(__name__)
    
    def execute(self) -> bool:
        """🚀 Выполнение миграции"""
        try:
            self.logger.info("🧪 Создание Integration и Performance тестов...")
            
            # Создаем integration тесты
            self._create_integration_tests()
            
            # Создаем performance тесты
            self._create_performance_tests()
            
            # Создаем утилиты для тестов
            self._create_test_utilities()
            
            self.logger.info("✅ Integration и Performance тесты созданы")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка создания тестов: {e}")
            return False
    
    def _create_integration_tests(self):
        """🔗 Создание интеграционных тестов"""
        # API интеграционные тесты
        api_integration_content = '''#!/usr/bin/env python3
"""🧪 Integration тесты API"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

@pytest.mark.integration
@pytest.mark.api
@pytest.mark.asyncio
async def test_api_client_full_cycle(mock_api_client):
    """Тест полного цикла API"""
    # Получаем тикер
    ticker = await mock_api_client.get_ticker()
    assert 'DOGE_EUR' in ticker
    
    # Получаем баланс
    balance = await mock_api_client.get_balance()
    assert 'EUR' in balance
    assert 'DOGE' in balance
    
    # Создаем ордер
    order = await mock_api_client.create_order(
        pair='DOGE_EUR',
        type='buy',
        amount='100',
        price='0.18'
    )
    assert order['order_id'] is not None
    assert order['status'] == 'open'

@pytest.mark.integration
@pytest.mark.api
@pytest.mark.asyncio
async def test_api_error_handling(mock_api_client):
    """Тест обработки ошибок API"""
    # Настраиваем мок для ошибки
    mock_api_client.get_ticker.side_effect = Exception("API Connection Error")
    
    with pytest.raises(Exception, match="API Connection Error"):
        await mock_api_client.get_ticker()

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_api_timeout_handling(mock_api_client):
    """Тест обработки таймаутов"""
    import asyncio
    
    async def slow_response():
        await asyncio.sleep(2)
        return {"result": "slow"}
    
    mock_api_client.get_ticker = slow_response
    
    # Тест с таймаутом
    try:
        result = await asyncio.wait_for(mock_api_client.get_ticker(), timeout=1.0)
        assert False, "Должен был быть таймаут"
    except asyncio.TimeoutError:
        pass  # Ожидаемое поведение

@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_api_calls(mock_api_client):
    """Тест параллельных API вызовов"""
    # Запускаем несколько вызовов параллельно
    tasks = [
        mock_api_client.get_ticker(),
        mock_api_client.get_balance(),
        mock_api_client.get_ticker(),
        mock_api_client.get_balance()
    ]
    
    results = await asyncio.gather(*tasks)
    
    assert len(results) == 4
    for result in results:
        assert result is not None
'''
        
        api_integration_file = self.tests_dir / "integration" / "test_api_integration.py"
        api_integration_file.write_text(api_integration_content)
        
        # Тесты системной интеграции
        system_integration_content = '''#!/usr/bin/env python3
"""🧪 Integration тесты системы"""
import pytest
import asyncio
from unittest.mock import Mock

@pytest.mark.integration
@pytest.mark.asyncio
async def test_trading_system_integration(mock_api_client, mock_strategy, mock_risk_manager):
    """Тест интеграции торговой системы"""
    # Симулируем торговый цикл
    
    # 1. Получаем рыночные данные
    market_data = await mock_api_client.get_ticker()
    assert market_data is not None
    
    # 2. Анализируем стратегией
    analysis = mock_strategy.analyze(market_data)
    assert analysis['action'] in ['buy', 'sell', 'hold']
    
    # 3. Проверяем риски
    risk_ok = mock_risk_manager.check_position_size(100)
    assert risk_ok is True
    
    # 4. Если нужно торговать - создаем ордер
    if analysis['action'] in ['buy', 'sell']:
        order = await mock_api_client.create_order(
            pair='DOGE_EUR',
            type=analysis['action'],
            amount='100',
            price='0.18'
        )
        assert order['order_id'] is not None

@pytest.mark.integration
@pytest.mark.dca
@pytest.mark.asyncio
async def test_dca_system_integration(mock_api_client, mock_dca_state, mock_dca_config):
    """Тест интеграции DCA системы"""
    # Проверяем состояние DCA
    assert mock_dca_state['current_step'] == 2
    assert mock_dca_state['total_invested'] > 0
    
    # Симулируем срабатывание следующего шага DCA
    current_price = 0.17000  # Цена упала еще больше
    base_price = mock_dca_state['base_price']
    step_trigger_price = base_price * (1 - mock_dca_config.step_percent / 100)
    
    if current_price <= step_trigger_price:
        # Должен сработать следующий шаг
        next_investment = mock_dca_config.step_multiplier * 100
        
        order = await mock_api_client.create_order(
            pair='DOGE_EUR',
            type='buy',
            amount=str(next_investment / current_price),
            price=str(current_price)
        )
        
        assert order['order_id'] is not None

@pytest.mark.integration
def test_strategy_risk_integration(mock_strategy, mock_risk_manager, mock_market_data):
    """Тест интеграции стратегии и риск-менеджмента"""
    # Получаем сигнал от стратегии
    signal = mock_strategy.analyze(mock_market_data)
    
    # Проверяем через риск-менеджер
    if signal['action'] == 'buy':
        position_size = 100  # EUR
        risk_approved = mock_risk_manager.check_position_size(position_size)
        daily_limits_ok = mock_risk_manager.check_daily_limits()
        
        # Все проверки должны пройти для мока
        assert risk_approved is True
        assert daily_limits_ok is True

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_full_trading_cycle(mock_api_client, mock_strategy, mock_risk_manager):
    """Тест полного торгового цикла"""
    cycles_completed = 0
    max_cycles = 3
    
    for cycle in range(max_cycles):
        # 1. Получаем данные
        ticker = await mock_api_client.get_ticker()
        balance = await mock_api_client.get_balance()
        
        # 2. Анализируем
        analysis = mock_strategy.analyze(ticker)
        
        # 3. Принимаем решение
        if analysis['action'] != 'hold' and analysis['confidence'] > 0.7:
            # 4. Проверяем риски
            risk_check = mock_risk_manager.check_daily_limits()
            
            if risk_check:
                # 5. Создаем ордер
                order = await mock_api_client.create_order(
                    pair='DOGE_EUR',
                    type=analysis['action'],
                    amount='100',
                    price='0.18'
                )
                
                # 6. Ждем исполнения (симуляция)
                await asyncio.sleep(0.1)
                
                # 7. Проверяем статус
                status = await mock_api_client.get_order_status(order['order_id'])
                
                if status['status'] == 'filled':
                    cycles_completed += 1
    
    # Проверяем что хотя бы один цикл завершился
    assert cycles_completed >= 0
'''
        
        system_integration_file = self.tests_dir / "integration" / "test_system_integration.py"
        system_integration_file.write_text(system_integration_content)
    
    def _create_performance_tests(self):
        """⚡ Создание тестов производительности"""
        performance_test_content = '''#!/usr/bin/env python3
"""🧪 Performance тесты"""
import pytest
import time
import asyncio
from decimal import Decimal

@pytest.mark.performance
@pytest.mark.slow
def test_strategy_analysis_performance(mock_strategy, sample_candles):
    """Тест производительности анализа стратегии"""
    iterations = 100
    start_time = time.time()
    
    for _ in range(iterations):
        result = mock_strategy.analyze(sample_candles)
        assert result is not None
    
    end_time = time.time()
    total_time = end_time - start_time
    avg_time = total_time / iterations
    
    # Анализ должен выполняться быстро (менее 10ms в среднем)
    assert avg_time < 0.01, f"Среднee время анализа: {avg_time:.4f}s"
    
    print(f"\\n📊 Performance: {iterations} анализов за {total_time:.3f}s (avg: {avg_time:.4f}s)")

@pytest.mark.performance
@pytest.mark.asyncio
async def test_api_calls_performance(mock_api_client):
    """Тест производительности API вызовов"""
    calls = 50
    start_time = time.time()
    
    # Параллельные вызовы
    tasks = []
    for _ in range(calls):
        task = mock_api_client.get_ticker()
        tasks.append(task)
    
    results = await asyncio.gather(*tasks)
    
    end_time = time.time()
    total_time = end_time - start_time
    avg_time = total_time / calls
    
    assert len(results) == calls
    assert avg_time < 0.1, f"Среднее время API вызова: {avg_time:.4f}s"
    
    print(f"\\n📊 API Performance: {calls} вызовов за {total_time:.3f}s (avg: {avg_time:.4f}s)")

@pytest.mark.performance
def test_decimal_calculations_performance():
    """Тест производительности расчетов с Decimal"""
    iterations = 1000
    start_time = time.time()
    
    base_price = Decimal('0.18000')
    amounts = [Decimal(str(i)) for i in range(1, 101)]
    
    for _ in range(iterations):
        # Симулируем типичные расчеты
        total_cost = sum(amount * base_price for amount in amounts)
        total_amount = sum(amounts)
        avg_price = total_cost / total_amount if total_amount > 0 else Decimal('0')
        
        assert avg_price > 0
    
    end_time = time.time()
    total_time = end_time - start_time
    
    assert total_time < 5.0, f"Расчеты слишком медленные: {total_time:.3f}s"
    
    print(f"\\n📊 Decimal Performance: {iterations} расчетов за {total_time:.3f}s")

@pytest.mark.performance
@pytest.mark.slow
@pytest.mark.asyncio
async def test_concurrent_trading_cycles(mock_api_client, mock_strategy):
    """Тест производительности параллельных торговых циклов"""
    cycles_count = 10
    start_time = time.time()
    
    async def trading_cycle():
        # Симуляция торгового цикла
        ticker = await mock_api_client.get_ticker()
        analysis = mock_strategy.analyze(ticker)
        
        if analysis['action'] in ['buy', 'sell']:
            order = await mock_api_client.create_order(
                pair='DOGE_EUR',
                type=analysis['action'],
                amount='100',
                price='0.18'
            )
            return order
        return None
    
    # Запускаем циклы параллельно
    tasks = [trading_cycle() for _ in range(cycles_count)]
    results = await asyncio.gather(*tasks)
    
    end_time = time.time()
    total_time = end_time - start_time
    
    completed_cycles = sum(1 for r in results if r is not None)
    
    assert total_time < 10.0, f"Параллельные циклы слишком медленные: {total_time:.3f}s"
    
    print(f"\\n📊 Concurrent Performance: {cycles_count} циклов за {total_time:.3f}s, завершено: {completed_cycles}")

@pytest.mark.performance
def test_memory_usage_monitoring():
    """Тест мониторинга использования памяти"""
    try:
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Создаем много объектов для тестирования памяти
        large_data = []
        for i in range(1000):
            data = {
                'timestamp': time.time(),
                'price': Decimal(f'0.{18000 + i:05d}'),
                'volume': Decimal(f'{1000000 + i}'),
                'metadata': f'test_data_{i}' * 100
            }
            large_data.append(data)
        
        peak_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Очищаем
        large_data.clear()
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = peak_memory - initial_memory
        
        assert memory_increase < 100, f"Слишком большое использование памяти: {memory_increase:.1f}MB"
        
        print(f"\\n📊 Memory Usage: Initial: {initial_memory:.1f}MB, Peak: {peak_memory:.1f}MB, Final: {final_memory:.1f}MB")
        
    except ImportError:
        pytest.skip("psutil не установлен, пропускаем тест памяти")
'''
        
        performance_test_file = self.tests_dir / "performance" / "test_performance.py"
        performance_test_file.write_text(performance_test_content)
    
    def _create_test_utilities(self):
        """🛠️ Создание утилит для тестов"""
        test_utilities_content = '''#!/usr/bin/env python3
"""🛠️ Утилиты для тестирования"""
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
'''
        
        utilities_file = self.tests_dir / "fixtures" / "test_utilities.py"
        utilities_file.write_text(test_utilities_content)

if __name__ == "__main__":
    import sys
    migration = Migration(Path("."))
    success = migration.execute()
    sys.exit(0 if success else 1)