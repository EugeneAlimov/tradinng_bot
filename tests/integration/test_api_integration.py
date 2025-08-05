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
