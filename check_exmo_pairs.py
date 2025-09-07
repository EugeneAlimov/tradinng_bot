#!/usr/bin/env python3
"""
Скрипт для диагностики и тестирования EXMO API
Поможет понять, какие пары доступны и какой формат ответа использует API
"""

import requests
import time
import json
from typing import Dict, Any


def test_exmo_ticker():
    """Проверяем доступные пары через ticker"""
    print("=== Тестирование EXMO ticker ===")

    try:
        response = requests.get("https://api.exmo.com/v1.1/ticker", timeout=10)

        if response.status_code != 200:
            print(f"❌ HTTP error: {response.status_code}")
            return None

        data = response.json()

        print(f"✅ Получено {len(data)} торговых пар")

        # Ищем пары с DOGE и EUR
        doge_pairs = [pair for pair in data.keys() if "DOGE" in pair]
        eur_pairs = [pair for pair in data.keys() if "EUR" in pair]

        print(f"Пары с DOGE: {doge_pairs}")
        print(f"Пары с EUR: {eur_pairs}")

        # Проверяем конкретные пары
        target_pairs = ["DOGE_EUR", "DOGE_USD", "DOGE_USDT", "BTC_EUR", "ETH_EUR"]
        available_pairs = []

        for pair in target_pairs:
            if pair in data:
                available_pairs.append(pair)
                print(f"✅ {pair} - доступна")
            else:
                print(f"❌ {pair} - недоступна")

        return available_pairs

    except Exception as e:
        print(f"❌ Ошибка при получении ticker: {e}")
        return None


def test_candles_request(symbol: str, test_name: str = ""):
    """Тестируем запрос свечей для конкретной пары"""
    print(f"\n=== Тестирование candles для {symbol} {test_name} ===")

    current_time = int(time.time())

    # Различные варианты параметров
    test_cases = [
        {
            "name": "Минимальные параметры",
            "params": {
                "symbol": symbol,
                "resolution": 1
            }
        },
        {
            "name": "С limit",
            "params": {
                "symbol": symbol,
                "resolution": 1,
                "limit": 100
            }
        },
        {
            "name": "С from/to (последний час)",
            "params": {
                "symbol": symbol,
                "resolution": 1,
                "from": current_time - 3600,
                "to": current_time
            }
        },
        {
            "name": "5-минутки",
            "params": {
                "symbol": symbol,
                "resolution": 5,
                "limit": 50
            }
        }
    ]

    for case in test_cases:
        print(f"\n--- {case['name']} ---")
        print(f"Параметры: {case['params']}")

        try:
            response = requests.get(
                "https://api.exmo.com/v1.1/candles_history",
                params=case['params'],
                timeout=10
            )

            print(f"HTTP статус: {response.status_code}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    analyze_candles_response(data, case['name'])
                except json.JSONDecodeError:
                    print(f"❌ Некорректный JSON: {response.text[:100]}")
            else:
                print(f"❌ HTTP ошибка: {response.text[:100]}")

        except Exception as e:
            print(f"❌ Ошибка запроса: {e}")


def analyze_candles_response(data: Any, test_name: str):
    """Анализируем ответ API для candles"""

    if not isinstance(data, dict):
        print(f"❌ Ответ не dict: {type(data)}")
        return

    # Проверяем на ошибки
    if data.get('result') == False and 'error' in data:
        print(f"❌ API error: {data['error']}")
        return

    if data.get('s') == 'error':
        print(f"❌ API error: {data.get('errmsg', 'unknown')}")
        return

    # Проверяем структуру данных
    if 'candles' in data:
        candles = data['candles']
        if isinstance(candles, list) and candles:
            print(f"✅ Успех! Получено {len(candles)} свечей")
            print(f"Первая свеча: {candles[0]}")
            if len(candles) > 1:
                print(f"Последняя свеча: {candles[-1]}")

            # Проверяем структуру свечи
            if candles[0]:
                keys = list(candles[0].keys())
                print(f"Поля свечи: {keys}")
        else:
            print(f"❌ Пустой массив свечей")
    elif 't' in data and 'o' in data:
        # Альтернативный формат с массивами
        print("✅ Формат с отдельными массивами")
        arrays = {k: len(v) if isinstance(v, list) else 'not list'
                  for k, v in data.items() if k in ['t', 'o', 'h', 'l', 'c', 'v']}
        print(f"Размеры массивов: {arrays}")
    else:
        print(f"❓ Неизвестная структура: {list(data.keys())}")
        print(f"Пример данных: {str(data)[:200]}")


def test_different_symbols():
    """Тестируем разные символы для поиска рабочих"""
    print("\n=== Тестирование различных символов ===")

    # Получаем список доступных пар
    available_pairs = test_exmo_ticker()

    if not available_pairs:
        print("Не удалось получить список пар, тестируем стандартные")
        test_symbols = ["DOGE_USD", "BTC_USD", "ETH_USD"]
    else:
        test_symbols = available_pairs[:3]  # Берем первые 3 доступные

    for symbol in test_symbols:
        test_candles_request(symbol, f"({symbol})")


def main():
    """Основная функция для диагностики EXMO API"""
    print("EXMO API Диагностика")
    print("=" * 50)

    # 1. Проверяем доступные пары
    available_pairs = test_exmo_ticker()

    # 2. Тестируем запрос свечей для разных пар
    if available_pairs:
        # Тестируем первую доступную пару
        test_candles_request(available_pairs[0], "(первая доступная)")

    # 3. Специально тестируем DOGE_EUR если она есть
    if available_pairs and "DOGE_EUR" in available_pairs:
        test_candles_request("DOGE_EUR", "(целевая пара)")
    else:
        print("\n❌ DOGE_EUR недоступна, попробуем альтернативы")
        alternatives = ["DOGE_USD", "DOGE_USDT", "BTC_EUR", "ETH_EUR"]
        for alt in alternatives:
            if available_pairs and alt in available_pairs:
                test_candles_request(alt, f"(альтернатива {alt})")
                break

    print("\n" + "=" * 50)
    print("Диагностика завершена")

    # Рекомендации
    if available_pairs:
        print(f"\n✅ Рекомендуемые пары для использования: {available_pairs[:5]}")
    else:
        print("\n❌ Не удалось получить список доступных пар")
        print("Проверьте подключение к интернету и доступность EXMO API")


if __name__ == "__main__":
    main()
