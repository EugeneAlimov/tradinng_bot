#!/usr/bin/env python3
# mock_exmo_data.py - Генератор моковых данных для EXMO

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def generate_mock_ohlc(pair: str, tf: str, n: int) -> pd.DataFrame:
    """Генерирует реалистичные OHLC данные для тестирования"""
    
    # Маппинг таймфреймов в минуты
    periods = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
    minutes = periods.get(tf, 5)
    
    # Создаем временные метки
    end_time = datetime.now()
    timestamps = []
    for i in range(n):
        ts = end_time - timedelta(minutes=minutes * (n - i - 1))
        timestamps.append(ts)
    
    # Базовые цены для разных пар
    base_prices = {
        'DOGE_USD': 0.07,
        'DOGE_EUR': 0.065,
        'XRP_USD': 0.50,
        'XRP_EUR': 0.46,
        'BTC_USD': 43000.0,
        'ETH_USD': 2300.0
    }
    
    base_price = base_prices.get(pair, 0.1)
    
    # Генерируем цены с трендом и волатильностью
    np.random.seed(hash(pair) % 2**32)  # Детерминированные данные для каждой пары
    
    prices = []
    current_price = base_price
    
    for i in range(n):
        # Добавляем слабый восходящий тренд + случайные движения
        trend = 0.0001  # 0.01% роста за бар
        volatility = np.random.normal(0, 0.01)  # 1% волатильность
        
        # Иногда добавляем сильные движения для генерации сигналов
        if i % 50 == 0:  # Каждые 50 баров
            volatility += np.random.choice([-0.05, 0.05])  # 5% движение
        
        current_price *= (1 + trend + volatility)
        
        # Генерируем OHLC для этого бара
        open_price = current_price
        close_change = np.random.normal(0, 0.005)  # 0.5% изменение внутри бара
        close_price = open_price * (1 + close_change)
        
        high_price = max(open_price, close_price) * (1 + abs(np.random.normal(0, 0.003)))
        low_price = min(open_price, close_price) * (1 - abs(np.random.normal(0, 0.003)))
        volume = np.random.uniform(1000, 50000)
        
        prices.append({
            'open': round(open_price, 6),
            'high': round(high_price, 6),
            'low': round(low_price, 6),
            'close': round(close_price, 6),
            'volume': round(volume, 2)
        })
        
        current_price = close_price
    
    # Создаем DataFrame
    df = pd.DataFrame(prices)
    df['dt'] = timestamps
    df['timestamp'] = [int(ts.timestamp()) for ts in timestamps]
    
    return df[["dt", "timestamp", "open", "high", "low", "close", "volume"]]

if __name__ == "__main__":
    # Тестируем генерацию данных
    import sys
    pair = sys.argv[1] if len(sys.argv) > 1 else "DOGE_USD"
    tf = sys.argv[2] if len(sys.argv) > 2 else "5m"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 720
    
    df = generate_mock_ohlc(pair, tf, n)
    print(f"Generated {len(df)} bars for {pair} on {tf} timeframe")
    print(f"Price range: {df['low'].min():.6f} - {df['high'].max():.6f}")
    print(f"First bar: {df.iloc[0].to_dict()}")
    print(f"Last bar: {df.iloc[-1].to_dict()}")
