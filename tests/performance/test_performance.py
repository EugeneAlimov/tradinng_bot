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
    
    print(f"\n📊 Performance: {iterations} анализов за {total_time:.3f}s (avg: {avg_time:.4f}s)")

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
    
    print(f"\n📊 API Performance: {calls} вызовов за {total_time:.3f}s (avg: {avg_time:.4f}s)")

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
    
    print(f"\n📊 Decimal Performance: {iterations} расчетов за {total_time:.3f}s")

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
    
    print(f"\n📊 Concurrent Performance: {cycles_count} циклов за {total_time:.3f}s, завершено: {completed_cycles}")

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
        
        print(f"\n📊 Memory Usage: Initial: {initial_memory:.1f}MB, Peak: {peak_memory:.1f}MB, Final: {final_memory:.1f}MB")
        
    except ImportError:
        pytest.skip("psutil не установлен, пропускаем тест памяти")
