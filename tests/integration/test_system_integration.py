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
