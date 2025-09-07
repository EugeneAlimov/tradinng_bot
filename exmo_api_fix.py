#!/usr/bin/env python3
# exmo_api_fix.py - Диагностика и исправление EXMO API

import requests
import time
import json


def test_exmo_candles_api():
    """Тестируем различные варианты параметров для EXMO candles_history"""

    symbol = "DOGE_USD"
    base_url = "https://api.exmo.com/v1.1/candles_history"

    print(f"Тестирование EXMO candles API для {symbol}...")
    print("=" * 50)

    # Текущее время
    current_time = int(time.time())

    # Различные варианты параметров
    test_cases = [
        {
            "name": "Только symbol и resolution",
            "params": {
                "symbol": symbol,
                "resolution": 1
            }
        },
        {
            "name": "Symbol, resolution и limit",
            "params": {
                "symbol": symbol,
                "resolution": 1,
                "limit": 100
            }
        },
        {
            "name": "Symbol, resolution, from и to",
            "params": {
                "symbol": symbol,
                "resolution": 1,
                "from": current_time - 3600,  # час назад
                "to": current_time
            }
        },
        {
            "name": "Symbol, resolution и to",
            "params": {
                "symbol": symbol,
                "resolution": 1,
                "to": current_time
            }
        },
        {
            "name": "Альтернативный формат с period",
            "params": {
                "symbol": symbol,
                "period": "1m",
                "limit": 100
            }
        }
    ]

    for i, test_case in enumerate(test_cases, 1):
        print(f"\nТест {i}: {test_case['name']}")
        print(f"Параметры: {test_case['params']}")

        try:
            response = requests.get(base_url, params=test_case['params'], timeout=10)
            print(f"Статус: {response.status_code}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        if data.get('result') == False and 'error' in data:
                            print(f"❌ API Error: {data['error']}")
                        elif 's' in data and data['s'] == 'error':
                            print(f"❌ API Error: {data.get('errmsg', 'Unknown error')}")
                        elif 'candles' in data:
                            candles = data['candles']
                            print(f"✅ Успех! Получено {len(candles)} свечей")
                            if candles:
                                print(f"   Первая свеча: {candles[0]}")
                        else:
                            print(f"❓ Неожиданный формат ответа: {list(data.keys())}")
                    else:
                        print(f"❓ Ответ не является словарем: {type(data)}")
                except json.JSONDecodeError:
                    print(f"❌ Некорректный JSON: {response.text[:100]}")
            else:
                print(f"❌ HTTP Error {response.status_code}: {response.text[:100]}")

        except Exception as e:
            print(f"❌ Исключение: {e}")

        time.sleep(0.5)  # Небольшая пауза между запросами


def check_exmo_api_docs():
    """Проверяем официальную документацию через другие endpoints"""
    print("\n" + "=" * 50)
    print("Проверка других EXMO endpoints...")

    # Тестируем другие endpoints для понимания формата
    endpoints = [
        ("ticker", {}),
        ("trades", {"pair": "DOGE_USD"}),
        ("order_book", {"pair": "DOGE_USD"})
    ]

    for endpoint, params in endpoints:
        print(f"\nТестируем {endpoint}...")
        try:
            url = f"https://api.exmo.com/v1.1/{endpoint}"
            response = requests.get(url, params=params, timeout=10)
            print(f"Статус: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and len(data) > 0:
                    print(f"✅ Успех! Ключи: {list(data.keys())[:5]}")
                else:
                    print(f"❓ Пустой ответ или неожиданный формат")
            else:
                print(f"❌ HTTP Error: {response.status_code}")

        except Exception as e:
            print(f"❌ Ошибка: {e}")


if __name__ == "__main__":
    test_exmo_candles_api()
    check_exmo_api_docs()

    print("\n" + "=" * 50)
    print("РЕКОМЕНДАЦИИ:")
    print("1. Проверьте какой тест успешен и используйте те параметры")
    print("2. Возможно, EXMO изменил API - проверьте актуальную документацию")
    print("3. Попробуйте альтернативный endpoint или формат запроса")
    print("4. Проверьте rate limits - возможно нужны задержки между запросами")