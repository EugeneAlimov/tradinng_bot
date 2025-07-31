"""
📊 Система анализа трендов с внешними данными
Использует CoinGecko + Binance для исторических данных
"""

import json
import requests
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

@dataclass
class TrendPoint:
    """📍 Точка данных тренда"""
    timestamp: datetime
    price: float
    volume: float
    source: str

    def to_dict(self):
        return {
            'timestamp': self.timestamp.isoformat(),
            'price': self.price,
            'volume': self.volume,
            'source': self.source
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            timestamp=datetime.fromisoformat(data['timestamp']),
            price=data['price'],
            volume=data['volume'],
            source=data['source']
        )

class TrendDataStorage:
    """💾 Хранилище данных трендов"""

    def __init__(self):
        self.data_dir = Path('data/trends')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.current_file = self.data_dir / 'current_trends.json'
        self.logger = logging.getLogger(__name__)

    def save_trend_data(self, points: List[TrendPoint]):
        """💾 Сохранение данных"""
        try:
            # Сохраняем последние 48 часов
            data = {
                'last_update': datetime.now().isoformat(),
                'points': [point.to_dict() for point in points[-288:]]
            }

            with open(self.current_file, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения: {e}")

    def load_trend_data(self) -> List[TrendPoint]:
        """📂 Загрузка данных"""
        try:
            if not self.current_file.exists():
                return []

            with open(self.current_file, 'r') as f:
                data = json.load(f)

            return [TrendPoint.from_dict(point) for point in data.get('points', [])]

        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки: {e}")
            return []

class ExternalMarketData:
    """🌐 Внешние источники данных"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def get_coingecko_data(self, days=1) -> List[TrendPoint]:
        """🦎 Данные CoinGecko"""
        try:
            url = "https://api.coingecko.com/api/v3/coins/dogecoin/market_chart"
            params = {
                'vs_currency': 'eur',
                'days': str(days),
                'interval': 'hourly'
            }

            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            points = []
            for timestamp_ms, price in data['prices'][-48:]:
                points.append(TrendPoint(
                    timestamp=datetime.fromtimestamp(timestamp_ms / 1000),
                    price=price,
                    volume=0,
                    source='coingecko'
                ))

            self.logger.info(f"📊 CoinGecko: {len(points)} точек")
            return points

        except Exception as e:
            self.logger.error(f"❌ CoinGecko: {e}")
            return []

    def get_binance_data(self) -> List[TrendPoint]:
        """🟡 Данные Binance"""
        try:
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': 'DOGEEUR',
                'interval': '1h',
                'limit': 48
            }

            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            points = []
            for kline in data:
                points.append(TrendPoint(
                    timestamp=datetime.fromtimestamp(int(kline[0]) / 1000),
                    price=float(kline[4]),  # Close price
                    volume=float(kline[5]),
                    source='binance'
                ))

            self.logger.info(f"📊 Binance: {len(points)} точек")
            return points

        except Exception as e:
            self.logger.error(f"❌ Binance: {e}")
            return []

class TrendAnalyzer:
    """📈 Анализатор трендов"""

    def __init__(self):
        self.storage = TrendDataStorage()
        self.market_data = ExternalMarketData()
        self.logger = logging.getLogger(__name__)
        self.last_update = None
        self.cached_analysis = {}

    def update_market_data(self):
        """🔄 Обновление данных"""
        try:
            all_points = []

            # Собираем из разных источников
            all_points.extend(self.market_data.get_coingecko_data())
            all_points.extend(self.market_data.get_binance_data())

            if all_points:
                # Удаляем дубликаты по времени
                unique_points = {}
                for point in all_points:
                    # Округляем до часа для группировки
                    hour_key = point.timestamp.replace(minute=0, second=0, microsecond=0)
                    if hour_key not in unique_points or point.source == 'coingecko':
                        unique_points[hour_key] = point

                sorted_points = sorted(unique_points.values(), key=lambda x: x.timestamp)

                self.storage.save_trend_data(sorted_points)
                self.last_update = datetime.now()

                self.logger.info(f"📊 Данные обновлены: {len(sorted_points)} точек")

        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления: {e}")

    def analyze_trend(self, hours_back=4) -> Dict:
        """📈 Анализ тренда"""
        try:
            points = self.storage.load_trend_data()
            if len(points) < 3:
                return {'trend': 'insufficient_data', 'confidence': 0}

            # Фильтруем по времени
            cutoff = datetime.now() - timedelta(hours=hours_back)
            recent_points = [p for p in points if p.timestamp >= cutoff]

            if len(recent_points) < 2:
                return {'trend': 'insufficient_data', 'confidence': 0}

            # Рассчитываем изменение
            start_price = recent_points[0].price
            end_price = recent_points[-1].price
            price_change = (end_price - start_price) / start_price

            # Определяем тренд
            if price_change > 0.03:      # +3%
                trend = 'strong_bullish'
            elif price_change > 0.01:    # +1%
                trend = 'bullish'
            elif price_change < -0.03:   # -3%
                trend = 'strong_bearish'
            elif price_change < -0.01:   # -1%
                trend = 'bearish'
            else:
                trend = 'sideways'

            # Рассчитываем волатильность
            if len(recent_points) > 2:
                prices = [p.price for p in recent_points]
                volatility = (max(prices) - min(prices)) / min(prices)
            else:
                volatility = 0

            analysis = {
                'trend': trend,
                'price_change_percent': price_change * 100,
                'volatility_percent': volatility * 100,
                'confidence': min(len(recent_points) / 10, 1.0),
                'data_points': len(recent_points),
                'start_price': start_price,
                'end_price': end_price,
                'hours_analyzed': hours_back,
                'timestamp': datetime.now().isoformat()
            }

            return analysis

        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа: {e}")
            return {'trend': 'error', 'confidence': 0}

    def should_allow_trading(self) -> Tuple[bool, str]:
        """🎯 Решение о торговле"""
        analysis = self.analyze_trend(hours_back=4)

        if analysis['confidence'] < 0.3:
            return False, "Недостаточно данных"

        trend = analysis['trend']
        change = analysis.get('price_change_percent', 0)

        if trend == 'strong_bearish' and change < -4:
            return False, f"Сильный медвежий тренд: {change:.1f}%"

        if analysis.get('volatility_percent', 0) > 8:
            return False, f"Высокая волатильность: {analysis['volatility_percent']:.1f}%"

        return True, f"Торговля разрешена ({trend}: {change:+.1f}%)"

    def get_cached_analysis(self, force_update=False) -> Dict:
        """⚡ Кэшированный анализ"""
        now = datetime.now()

        # Обновляем данные каждые 10 минут
        if (force_update or not self.last_update or 
            (now - self.last_update).seconds > 600):
            self.update_market_data()

        # Обновляем анализ каждые 5 минут
        cache_key = f"analysis_{now.hour}_{now.minute//5}"
        if cache_key not in self.cached_analysis:
            self.cached_analysis.clear()  # Очищаем старый кэш

            analysis = {}
            for period in [1, 4, 24]:
                analysis[f'{period}h'] = self.analyze_trend(period)

            analysis['trading_allowed'], analysis['trading_reason'] = self.should_allow_trading()
            self.cached_analysis[cache_key] = analysis

        return self.cached_analysis[cache_key]

    def get_trend_summary(self) -> str:
        """📋 Краткая сводка"""
        try:
            analysis = self.get_cached_analysis()
            trend_4h = analysis.get('4h', {})

            trend = trend_4h.get('trend', 'unknown')
            change = trend_4h.get('price_change_percent', 0)
            confidence = trend_4h.get('confidence', 0)

            if confidence < 0.3:
                return "📊 Недостаточно данных для анализа"

            emoji_map = {
                'strong_bullish': '🚀',
                'bullish': '📈', 
                'sideways': '➡️',
                'bearish': '📉',
                'strong_bearish': '💥'
            }

            emoji = emoji_map.get(trend, '❓')

            return f"{emoji} Тренд 4ч: {trend} ({change:+.1f}%, уверенность: {confidence:.0%})"

        except Exception as e:
            return f"❌ Ошибка анализа: {e}"

# Интеграция с ботом
def integrate_trend_analysis(bot_instance):
    """🔗 Интеграция в основной бот"""

    if not hasattr(bot_instance, 'trend_analyzer'):
        bot_instance.trend_analyzer = TrendAnalyzer()

    def enhanced_buy_decision(original_decision):
        """🧠 Улучшенное решение о покупке"""
        if not original_decision:
            return False, "Оригинальная стратегия против"

        try:
            allowed, reason = bot_instance.trend_analyzer.should_allow_trading()
            if not allowed:
                return False, f"Тренд-анализ: {reason}"

            return True, f"Разрешено трендом: {reason}"

        except Exception as e:
            bot_instance.logger.error(f"❌ Ошибка тренд-анализа: {e}")
            return original_decision, "Анализ недоступен"

    return enhanced_buy_decision

if __name__ == "__main__":
    # Тестирование
    analyzer = TrendAnalyzer()

    print("📊 ТЕСТ АНАЛИЗАТОРА ТРЕНДОВ")
    print("=" * 40)

    # Обновляем данные
    print("🔄 Обновление данных...")
    analyzer.update_market_data()

    # Получаем анализ
    analysis = analyzer.get_cached_analysis()

    for period in ['1h', '4h', '24h']:
        if period in analysis:
            trend_data = analysis[period]
            print(f"{period}: {trend_data.get('trend', 'N/A')} "
                  f"({trend_data.get('price_change_percent', 0):+.1f}%)")

    # Решение о торговле
    can_trade = analysis.get('trading_allowed', False)
    reason = analysis.get('trading_reason', 'N/A')
    print(f"\nТорговля: {'✅ РАЗРЕШЕНА' if can_trade else '❌ ЗАПРЕЩЕНА'}")
    print(f"Причина: {reason}")

    # Краткая сводка
    print(f"\n{analyzer.get_trend_summary()}")
