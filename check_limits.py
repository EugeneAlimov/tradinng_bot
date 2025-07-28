import json
from api_client import ExmoAPIClient
from config import TradingConfig


def analyze_all_pairs():
    """Анализ всех доступных пар и их лимитов"""
    config = TradingConfig()
    api = ExmoAPIClient(config)

    try:
        print("🔍 Получаем настройки всех пар...")
        pair_settings = api.get_pair_settings()

        print(f"📊 Найдено пар: {len(pair_settings)}")
        print("=" * 80)

        # Группируем пары по валютам
        eur_pairs = []
        usd_pairs = []
        btc_pairs = []
        eth_pairs = []
        usdt_pairs = []
        other_pairs = []

        for pair_name, settings in pair_settings.items():
            if '_EUR' in pair_name:
                eur_pairs.append((pair_name, settings))
            elif '_USD' in pair_name:
                usd_pairs.append((pair_name, settings))
            elif '_BTC' in pair_name:
                btc_pairs.append((pair_name, settings))
            elif '_ETH' in pair_name:
                eth_pairs.append((pair_name, settings))
            elif '_USDT' in pair_name or 'USDT_' in pair_name:
                usdt_pairs.append((pair_name, settings))
            else:
                other_pairs.append((pair_name, settings))

        # Анализируем каждую группу
        print("🇪🇺 EUR ПАРЫ:")
        analyze_currency_pairs(eur_pairs, "EUR")

        print("\n🇺🇸 USD ПАРЫ:")
        analyze_currency_pairs(usd_pairs, "USD")

        print("\n₿ BTC ПАРЫ:")
        analyze_currency_pairs(btc_pairs, "BTC")

        print("\n⟠ ETH ПАРЫ:")
        analyze_currency_pairs(eth_pairs, "ETH")

        print("\n💰 USDT ПАРЫ:")
        analyze_currency_pairs(usdt_pairs, "USDT")

        print("\n🔄 ВОЗМОЖНЫЕ АРБИТРАЖНЫЕ ЦЕПОЧКИ:")
        find_arbitrage_chains(pair_settings)

        print("\n💡 РЕКОМЕНДАЦИИ ДЛЯ 20 EUR:")
        recommendations_for_small_amount(pair_settings)

    except Exception as e:
        print(f"❌ Ошибка: {e}")


def analyze_currency_pairs(pairs, currency):
    """Анализ пар для конкретной валюты"""
    if not pairs:
        print(f"   Нет доступных пар с {currency}")
        return

    # Сортируем по min_amount для удобства
    pairs.sort(key=lambda x: float(x[1].get('min_amount', '999999')))

    for pair_name, settings in pairs:
        min_qty = settings.get('min_quantity', 'N/A')
        min_amount = settings.get('min_amount', 'N/A')
        max_amount = settings.get('max_amount', 'N/A')
        commission = settings.get('commission_taker_percent', 'N/A')

        # Определяем доступность для 20 EUR
        affordable = "✅" if is_affordable(settings, 20.0) else "❌"

        print(f"   {affordable} {pair_name:12} | "
              f"Мин.сумма: {min_amount:>8} | "
              f"Мин.кол-во: {min_qty:>12} | "
              f"Комиссия: {commission}%")


def is_affordable(settings, amount_eur):
    """Проверяем доступность пары для заданной суммы"""
    try:
        min_amount = float(settings.get('min_amount', '999999'))
        return amount_eur >= min_amount
    except:
        return False


def find_arbitrage_chains(pair_settings):
    """Поиск возможных арбитражных цепочек"""

    # Ищем пары для построения цепочек
    available_pairs = set(pair_settings.keys())

    print("   🔄 Проверяем возможные арбитражные циклы...")

    # Базовые валюты для анализа
    base_currencies = ['EUR', 'USD', 'BTC', 'ETH', 'USDT']

    # Проверяем треугольные арбитражи
    triangular_chains = []

    for base1 in base_currencies:
        for base2 in base_currencies:
            for base3 in base_currencies:
                if base1 != base2 != base3 != base1:
                    # Ищем цепочку A->B->C->A
                    pair1 = f"{base1}_{base2}"
                    pair2 = f"{base2}_{base3}"
                    pair3 = f"{base3}_{base1}"

                    # Проверяем обратные пары тоже
                    pair1_rev = f"{base2}_{base1}"
                    pair2_rev = f"{base3}_{base2}"
                    pair3_rev = f"{base1}_{base3}"

                    # Различные комбинации направлений
                    if (pair1 in available_pairs and
                            pair2 in available_pairs and
                            pair3 in available_pairs):

                        chain = f"{base1} → {base2} → {base3} → {base1}"
                        chain_pairs = [pair1, pair2, pair3]

                        if is_chain_affordable(chain_pairs, pair_settings, 20.0):
                            affordable = "✅"
                        else:
                            affordable = "❌"

                        triangular_chains.append((affordable, chain, chain_pairs))

    # Показываем найденные цепочки
    if triangular_chains:
        print("   📊 Найденные треугольные арбитражи:")
        for affordable, chain, pairs in triangular_chains[:10]:  # Первые 10
            print(f"      {affordable} {chain}")
            for pair in pairs:
                settings = pair_settings.get(pair, {})
                min_amount = settings.get('min_amount', 'N/A')
                print(f"         └─ {pair}: мин.сумма {min_amount}")
    else:
        print("   ❌ Треугольные арбитражи не найдены")

    # Ищем цепочки через промежуточные валюты для DOGE
    print("\n   🐕 Цепочки для DOGE EUR ↔ USD:")
    doge_chains = find_doge_conversion_chains(pair_settings)

    for chain_info in doge_chains[:5]:  # Первые 5
        affordable, description, pairs, total_commission = chain_info
        print(f"      {affordable} {description}")
        print(f"         Общая комиссия: ~{total_commission:.2f}%")
        for pair in pairs:
            settings = pair_settings.get(pair, {})
            min_amount = settings.get('min_amount', 'N/A')
            commission = settings.get('commission_taker_percent', 'N/A')
            print(f"         └─ {pair}: мин.сумма {min_amount}, комиссия {commission}%")


def find_doge_conversion_chains(pair_settings):
    """Поиск цепочек для конверсии DOGE EUR ↔ USD"""
    chains = []
    available_pairs = set(pair_settings.keys())

    # Возможные промежуточные валюты
    intermediate = ['BTC', 'ETH', 'USDT', 'LTC']

    for bridge in intermediate:
        # Цепочка: DOGE_EUR → BRIDGE_EUR → BRIDGE_USD → DOGE_USD
        chain_pairs = [
            f"DOGE_EUR",
            f"{bridge}_EUR",
            f"{bridge}_USD",
            f"DOGE_USD"
        ]

        # Проверяем что все пары существуют
        if all(pair in available_pairs for pair in chain_pairs):
            total_commission = calculate_chain_commission(chain_pairs, pair_settings)
            affordable = "✅" if is_chain_affordable(chain_pairs, pair_settings, 20.0) else "❌"

            description = f"DOGE_EUR → {bridge}_EUR → {bridge}_USD → DOGE_USD"
            chains.append((affordable, description, chain_pairs, total_commission))

    return sorted(chains, key=lambda x: x[3])  # Сортируем по комиссии


def is_chain_affordable(chain_pairs, pair_settings, amount_eur):
    """Проверяем доступность всей цепочки для заданной суммы"""
    for pair in chain_pairs:
        settings = pair_settings.get(pair, {})
        if not is_affordable(settings, amount_eur * 0.25):  # 25% от суммы на каждый шаг
            return False
    return True


def calculate_chain_commission(chain_pairs, pair_settings):
    """Рассчитываем общую комиссию для цепочки"""
    total_commission = 0
    for pair in chain_pairs:
        settings = pair_settings.get(pair, {})
        commission = float(settings.get('commission_taker_percent', '0.3'))
        total_commission += commission
    return total_commission


def recommendations_for_small_amount(pair_settings):
    """Рекомендации для торговли с небольшой суммой"""

    print("   💡 Для суммы ~20 EUR:")

    # Ищем самые доступные пары
    affordable_pairs = []

    for pair_name, settings in pair_settings.items():
        if is_affordable(settings, 20.0):
            min_amount = float(settings.get('min_amount', '999999'))
            commission = float(settings.get('commission_taker_percent', '0.3'))

            # Приоритет для популярных валют
            priority = 0
            if 'DOGE' in pair_name:
                priority += 10
            if 'EUR' in pair_name:
                priority += 5
            if 'BTC' in pair_name or 'ETH' in pair_name:
                priority += 3
            if 'USDT' in pair_name:
                priority += 2

            affordable_pairs.append((priority, pair_name, min_amount, commission))

    # Сортируем по приоритету и минимальной сумме
    affordable_pairs.sort(key=lambda x: (-x[0], x[2]))

    print("   📊 Топ доступных пар:")
    for priority, pair, min_amount, commission in affordable_pairs[:15]:
        print(f"      ✅ {pair:12} | Мин: {min_amount:>6.2f} | Комиссия: {commission}% | Приоритет: {priority}")

    print("\n   🎯 КОНКРЕТНЫЕ РЕКОМЕНДАЦИИ:")
    print("      1. Начать с текущей стратегии DOGE_EUR")
    print("      2. Добавить мониторинг других доступных DOGE пар")
    print("      3. Рассмотреть ETH или BTC пары для диверсификации")
    print("      4. Избегать цепочек с комиссией >2%")
    print("      5. Тестировать арбитраж только при разнице >1%")


if __name__ == "__main__":
    print("🚀 АНАЛИЗ ЛИМИТОВ EXMO")
    print("=" * 50)
    analyze_all_pairs()
    print("=" * 50)
    print("✅ Анализ завершен!")