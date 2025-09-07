#!/usr/bin/env python3
# check_exmo_pairs.py - Проверка доступных пар на EXMO

import requests
import json


def check_exmo_pairs():
    """Получить список всех доступных пар на EXMO"""

    print("Получение списка доступных пар на EXMO...")

    try:
        # Получаем тикеры всех пар
        response = requests.get("https://api.exmo.com/v1.1/ticker", timeout=10)

        if response.status_code != 200:
            print(f"Ошибка HTTP: {response.status_code}")
            return

        data = response.json()

        print(f"\nВсего пар доступно: {len(data)}")
        print("\nДоступные пары:")

        # Ищем пары с DOGE и XRP
        doge_pairs = []
        xrp_pairs = []
        eur_pairs = []

        for pair in sorted(data.keys()):
            print(f"  {pair}")

            if "DOGE" in pair:
                doge_pairs.append(pair)
            if "XRP" in pair:
                xrp_pairs.append(pair)
            if "EUR" in pair:
                eur_pairs.append(pair)

        print(f"\nПары с DOGE: {doge_pairs}")
        print(f"Пары с XRP: {xrp_pairs}")
        print(f"Пары с EUR: {eur_pairs}")

        # Проверяем конкретные пары
        target_pairs = ["DOGE_EUR", "XRP_EUR", "DOGE_USD", "XRP_USD", "DOGE_USDT", "XRP_USDT"]
        print(f"\nПроверка целевых пар:")
        for pair in target_pairs:
            exists = pair in data
            print(f"  {pair}: {'✅ Существует' if exists else '❌ Не найдено'}")

    except Exception as e:
        print(f"Ошибка при получении пар: {e}")


def test_candles_request(symbol):
    """Тестируем запрос свечей для конкретной пары"""

    print(f"\nТестирование запроса свечей для {symbol}...")

    params = {
        "symbol": symbol,
        "resolution": 1,  # 1 минута
        "limit": 10
    }

    try:
        response = requests.get(
            "https://api.exmo.com/v1.1/candles_history",
            params=params,
            timeout=10
        )

        print(f"Статус ответа: {response.status_code}")
        print(f"Ответ: {response.text[:200]}...")

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and data.get('s') == 'error':
                print(f"❌ Ошибка API: {data.get('errmsg', 'Unknown error')}")
            else:
                print(f"✅ Успешный запрос")

    except Exception as e:
        print(f"❌ Ошибка запроса: {e}")


if __name__ == "__main__":
    check_exmo_pairs()

    # Тестируем проблемные пары
    print("\n" + "=" * 50)
    test_candles_request("DOGE_EUR")
    test_candles_request("XRP_EUR")

    # Попробуем альтернативные форматы
    test_candles_request("DOGE_USD")
    test_candles_request("XRP_USD")