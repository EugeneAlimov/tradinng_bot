import logging
from datetime import datetime
from advanced_trend_filter import AdvancedTrendFilter, TrendDirection
from config import TradingConfig
from api_client import ExmoAPIClient

def diagnose_trend_filter():
    """🔍 Диагностика работы trend filter"""
    print("🧠 ДИАГНОСТИКА TREND FILTER")
    print("=" * 50)

    try:
        config = TradingConfig()
        api = ExmoAPIClient(config)
        trend_filter = AdvancedTrendFilter(config)

        # Получаем текущую цену
        pair = f"{config.CURRENCY_1}_{config.CURRENCY_2}"
        trades = api.get_trades(pair)
        current_price = float(trades[pair][0]['price'])

        print(f"💰 Текущая цена DOGE: {current_price:.8f} EUR")

        # Симулируем некоторое количество цен для инициализации
        print("\n📊 Инициализация данных...")
        base_price = current_price
        for i in range(60):  # 1 час данных
            # Небольшие случайные изменения
            import random
            change = random.uniform(-0.002, 0.002)  # ±0.2%
            base_price *= (1 + change)
            trend_filter.update_price(base_price)

        # Анализируем текущий тренд
        print("\n🧠 АНАЛИЗ ТРЕНДА:")
        analysis = trend_filter.analyze_trend(current_price)

        print(f"📊 Направление: {analysis.direction.value}")
        print(f"💪 Сила тренда: {analysis.strength:.2f}")
        print(f"🎯 Уверенность: {analysis.confidence:.2f}")
        print(f"📈 Тренд 4ч: {analysis.trend_4h*100:+.2f}%")
        print(f"📈 Тренд 1ч: {analysis.trend_1h*100:+.2f}%")
        print(f"🌊 Волатильность: {analysis.volatility*100:.2f}%")
        print(f"⚡ Моментум: {analysis.momentum*100:+.2f}%")

        print("\n🎯 ТОРГОВЫЕ РЕШЕНИЯ:")
        print(f"🛒 DCA разрешена: {'✅ ДА' if analysis.should_allow_dca else '🚫 НЕТ'}")
        print(f"💰 Покупки разрешены: {'✅ ДА' if analysis.should_allow_buy else '🚫 НЕТ'}")
        print(f"💭 Причина: {analysis.reason}")

        # Проверяем пороги
        print("\n⚙️ НАСТРОЙКИ ФИЛЬТРА:")
        print(f"🐻 Медвежий порог (DCA): {config.TREND_DCA_DISABLE_THRESHOLD*100:.0f}%")
        print(f"🐻 Критический порог: {config.TREND_BUY_DISABLE_THRESHOLD*100:.0f}%")
        print(f"🌊 Высокая волатильность: {config.TREND_HIGH_VOLATILITY_THRESHOLD*100:.0f}%")

        # Рекомендации
        print("\n💡 РЕКОМЕНДАЦИИ:")
        if analysis.direction == TrendDirection.STRONG_BEARISH:
            print("🚨 СИЛЬНЫЙ МЕДВЕЖИЙ ТРЕНД - все покупки должны быть заблокированы!")
        elif analysis.direction == TrendDirection.BEARISH:
            print("⚠️ Медвежий тренд - DCA может быть заблокирована")
        elif analysis.direction == TrendDirection.STRONG_BULLISH:
            print("🚀 Сильный бычий тренд - все покупки разрешены!")
        elif analysis.direction == TrendDirection.SIDEWAYS:
            print("➡️ Боковой тренд - идеальные условия для торговли")

        # Проверяем конкретные условия
        print("\n🔍 ПРОВЕРКА УСЛОВИЙ:")
        if analysis.trend_4h <= config.TREND_DCA_DISABLE_THRESHOLD:
            print(f"🚫 DCA будет заблокирована: {analysis.trend_4h*100:.1f}% <= {config.TREND_DCA_DISABLE_THRESHOLD*100:.0f}%")
        else:
            print(f"✅ DCA разрешена по 4ч тренду: {analysis.trend_4h*100:.1f}% > {config.TREND_DCA_DISABLE_THRESHOLD*100:.0f}%")

        if analysis.volatility > config.TREND_HIGH_VOLATILITY_THRESHOLD:
            print(f"⚠️ Высокая волатильность: {analysis.volatility*100:.1f}% > {config.TREND_HIGH_VOLATILITY_THRESHOLD*100:.0f}%")
        else:
            print(f"✅ Нормальная волатильность: {analysis.volatility*100:.1f}% <= {config.TREND_HIGH_VOLATILITY_THRESHOLD*100:.0f}%")

        print("\n" + "=" * 50)
        print("✅ Диагностика завершена")

        return analysis

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        return None

if __name__ == "__main__":
    diagnose_trend_filter()
