# advanced_trend_filter.py - Продвинутый фильтр трендов для крипто-бота
import logging
import time
import statistics
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
from collections import deque
from dataclasses import dataclass
from enum import Enum


class TrendDirection(Enum):
    """📈 Направления тренда"""
    STRONG_BULLISH = "strong_bullish"    # Сильный рост
    BULLISH = "bullish"                  # Рост
    SIDEWAYS = "sideways"                # Боковик
    BEARISH = "bearish"                  # Падение
    STRONG_BEARISH = "strong_bearish"    # Сильное падение


@dataclass
class TrendAnalysis:
    """📊 Результат анализа тренда"""
    direction: TrendDirection
    strength: float                      # Сила тренда 0-1
    trend_4h: float                     # Тренд за 4 часа (%)
    trend_1h: float                     # Тренд за 1 час (%)
    trend_15m: float                    # Тренд за 15 минут (%)
    volatility: float                   # Волатильность
    momentum: float                     # Моментум
    confidence: float                   # Уверенность в анализе 0-1
    should_allow_dca: bool              # Разрешить DCA
    should_allow_buy: bool              # Разрешить покупки
    reason: str                         # Причина решения


class AdvancedTrendFilter:
    """🧠 Продвинутый анализатор трендов для криптовалют"""

    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # 📊 История цен для разных таймфреймов
        self.prices_1m = deque(maxlen=240)   # 4 часа минутных данных
        self.prices_5m = deque(maxlen=48)    # 4 часа 5-минутных данных
        self.prices_15m = deque(maxlen=16)   # 4 часа 15-минутных данных
        self.prices_1h = deque(maxlen=24)    # 24 часа часовых данных

        # ⏰ Временные метки для агрегации
        self.last_5m_update = 0
        self.last_15m_update = 0
        self.last_1h_update = 0

        # 🎯 Настройки фильтра
        self.bearish_threshold_4h = -0.08    # -8% за 4 часа = сильный медведь
        self.bearish_threshold_1h = -0.04    # -4% за 1 час = медведь
        self.bullish_threshold_4h = 0.06     # +6% за 4 часа = сильный бык
        self.bullish_threshold_1h = 0.03     # +3% за 1 час = бык

        # 🛡️ Настройки защиты DCA
        self.dca_disable_threshold = -0.05   # Отключать DCA при -5% за 4ч
        self.buy_disable_threshold = -0.10   # Отключать покупки при -10% за 4ч
        self.high_volatility_threshold = 0.05 # 5% волатильность = высокая

        # 📈 Momentum настройки
        self.momentum_periods = [5, 10, 15]  # Периоды для расчета моментума

        self.logger.info("🧠 Продвинутый TrendFilter инициализирован")
        self.logger.info(f"   🐻 Медвежий порог: {self.bearish_threshold_4h*100:.0f}% за 4ч")
        self.logger.info(f"   🐂 Бычий порог: {self.bullish_threshold_4h*100:.0f}% за 4ч")
        self.logger.info(f"   🚫 DCA блокировка: {self.dca_disable_threshold*100:.0f}% за 4ч")

    def update_price(self, current_price: float, timestamp: float = None):
        """📊 Обновление ценовых данных"""
        if timestamp is None:
            timestamp = time.time()

        # Добавляем в минутную историю
        self.prices_1m.append((timestamp, current_price))

        # Агрегируем в более крупные таймфреймы
        self._aggregate_timeframes(timestamp, current_price)

    def _aggregate_timeframes(self, timestamp: float, price: float):
        """🔄 Агрегация данных по таймфреймам"""

        # 5-минутная агрегация
        if timestamp - self.last_5m_update >= 300:  # 5 минут
            if len(self.prices_1m) >= 5:
                # Берем среднюю цену за последние 5 минут
                recent_5m = [p[1] for p in list(self.prices_1m)[-5:]]
                avg_5m = statistics.mean(recent_5m)
                self.prices_5m.append((timestamp, avg_5m))
                self.last_5m_update = timestamp

        # 15-минутная агрегация
        if timestamp - self.last_15m_update >= 900:  # 15 минут
            if len(self.prices_1m) >= 15:
                recent_15m = [p[1] for p in list(self.prices_1m)[-15:]]
                avg_15m = statistics.mean(recent_15m)
                self.prices_15m.append((timestamp, avg_15m))
                self.last_15m_update = timestamp

        # Часовая агрегация
        if timestamp - self.last_1h_update >= 3600:  # 1 час
            if len(self.prices_1m) >= 60:
                recent_1h = [p[1] for p in list(self.prices_1m)[-60:]]
                avg_1h = statistics.mean(recent_1h)
                self.prices_1h.append((timestamp, avg_1h))
                self.last_1h_update = timestamp

    def analyze_trend(self, current_price: float) -> TrendAnalysis:
        """🧠 Комплексный анализ тренда"""

        try:
            self.update_price(current_price)

            # Базовые расчеты трендов
            trend_4h = self._calculate_trend(self.prices_15m, 4*4)  # 4 часа
            trend_1h = self._calculate_trend(self.prices_5m, 12)    # 1 час
            trend_15m = self._calculate_trend(self.prices_1m, 15)   # 15 минут

            # Волатильность
            volatility = self._calculate_volatility(self.prices_1m, 60)  # 1 час

            # Моментум
            momentum = self._calculate_momentum(self.prices_1m)

            # Определяем направление тренда
            direction = self._determine_trend_direction(trend_4h, trend_1h, volatility)

            # Сила тренда
            strength = self._calculate_trend_strength(trend_4h, trend_1h, momentum)

            # Уверенность в анализе
            confidence = self._calculate_confidence()

            # Решения по торговле
            should_allow_dca, should_allow_buy, reason = self._make_trading_decisions(
                direction, trend_4h, trend_1h, volatility, strength
            )

            analysis = TrendAnalysis(
                direction=direction,
                strength=strength,
                trend_4h=trend_4h,
                trend_1h=trend_1h,
                trend_15m=trend_15m,
                volatility=volatility,
                momentum=momentum,
                confidence=confidence,
                should_allow_dca=should_allow_dca,
                should_allow_buy=should_allow_buy,
                reason=reason
            )

            # Логируем анализ
            self._log_analysis(analysis, current_price)

            return analysis

        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа тренда: {e}")
            return self._create_default_analysis("Ошибка анализа")

    def _calculate_trend(self, price_data: deque, periods: int) -> float:
        """📈 Расчет тренда за период"""
        if len(price_data) < periods:
            return 0.0

        prices = list(price_data)
        if len(prices) < 2:
            return 0.0

        start_price = prices[-periods][1] if len(prices) >= periods else prices[0][1]
        end_price = prices[-1][1]

        return (end_price - start_price) / start_price if start_price > 0 else 0.0

    def _calculate_volatility(self, price_data: deque, periods: int) -> float:
        """🌊 Расчет волатильности"""
        if len(price_data) < periods:
            periods = len(price_data)

        if periods < 2:
            return 0.0

        prices = [p[1] for p in list(price_data)[-periods:]]
        returns = []

        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                returns.append((prices[i] - prices[i-1]) / prices[i-1])

        return statistics.stdev(returns) if len(returns) > 1 else 0.0

    def _calculate_momentum(self, price_data: deque) -> float:
        """⚡ Расчет моментума"""
        if len(price_data) < max(self.momentum_periods):
            return 0.0

        prices = list(price_data)
        momentum_scores = []

        for period in self.momentum_periods:
            if len(prices) >= period:
                start_price = prices[-period][1]
                end_price = prices[-1][1]
                momentum = (end_price - start_price) / start_price if start_price > 0 else 0
                momentum_scores.append(momentum)

        return statistics.mean(momentum_scores) if momentum_scores else 0.0

    def _determine_trend_direction(self, trend_4h: float, trend_1h: float,
                                 volatility: float) -> TrendDirection:
        """🎯 Определение направления тренда"""

        # Сильные тренды (приоритет долгосрочному)
        if trend_4h >= self.bullish_threshold_4h:
            return TrendDirection.STRONG_BULLISH
        elif trend_4h <= self.bearish_threshold_4h:
            return TrendDirection.STRONG_BEARISH

        # Средние тренды с учетом краткосрочного
        elif trend_4h >= self.bullish_threshold_4h * 0.5:  # +3% за 4ч
            if trend_1h >= self.bullish_threshold_1h * 0.5:  # +1.5% за 1ч
                return TrendDirection.BULLISH

        elif trend_4h <= self.bearish_threshold_4h * 0.5:  # -4% за 4ч
            if trend_1h <= self.bearish_threshold_1h * 0.5:  # -2% за 1ч
                return TrendDirection.BEARISH

        # Высокая волатильность = неопределенность
        if volatility > self.high_volatility_threshold:
            # Смотрим краткосрочный тренд при высокой волатильности
            if trend_1h > 0.02:  # +2% за час
                return TrendDirection.BULLISH
            elif trend_1h < -0.02:  # -2% за час
                return TrendDirection.BEARISH

        return TrendDirection.SIDEWAYS

    def _calculate_trend_strength(self, trend_4h: float, trend_1h: float,
                                momentum: float) -> float:
        """💪 Расчет силы тренда"""

        # Базовая сила от 4-часового тренда
        base_strength = min(1.0, abs(trend_4h) / 0.1)  # Нормируем к 10%

        # Корректировка по краткосрочному тренду
        if (trend_4h > 0 and trend_1h > 0) or (trend_4h < 0 and trend_1h < 0):
            # Тренды в одном направлении - усиливаем
            trend_alignment = 0.2
        else:
            # Тренды в разных направлениях - ослабляем
            trend_alignment = -0.1

        # Корректировка по моментуму
        momentum_factor = min(0.2, abs(momentum) * 10)  # Максимум +20%

        strength = base_strength + trend_alignment + momentum_factor
        return max(0.0, min(1.0, strength))  # Ограничиваем 0-1

    def _calculate_confidence(self) -> float:
        """🎯 Расчет уверенности в анализе"""

        # База = количество данных
        data_confidence = min(1.0, len(self.prices_1m) / 120)  # 2 часа для 100%

        # Корректировка по количеству таймфреймов
        timeframe_bonus = 0.0
        if len(self.prices_5m) >= 12:   # 1 час 5-минутных данных
            timeframe_bonus += 0.1
        if len(self.prices_15m) >= 8:   # 2 часа 15-минутных данных
            timeframe_bonus += 0.1
        if len(self.prices_1h) >= 4:    # 4 часа часовых данных
            timeframe_bonus += 0.2

        confidence = data_confidence + timeframe_bonus
        return min(1.0, confidence)

    def _make_trading_decisions(self, direction: TrendDirection, trend_4h: float,
                              trend_1h: float, volatility: float,
                              strength: float) -> Tuple[bool, bool, str]:
        """🤖 Принятие торговых решений"""

        should_allow_dca = True
        should_allow_buy = True
        reasons = []

        # 🚫 Блокировка DCA в сильном медвежьем тренде
        if trend_4h <= self.dca_disable_threshold:
            should_allow_dca = False
            reasons.append(f"DCA заблокирована: падение {trend_4h*100:.1f}% за 4ч")

        # 🚫 Блокировка покупок в критическом падении
        if trend_4h <= self.buy_disable_threshold:
            should_allow_buy = False
            reasons.append(f"Покупки заблокированы: критическое падение {trend_4h*100:.1f}%")

        # 🌊 Ограничения при высокой волатильности
        if volatility > self.high_volatility_threshold:
            if direction in [TrendDirection.BEARISH, TrendDirection.STRONG_BEARISH]:
                should_allow_dca = False
                reasons.append(f"DCA заблокирована: высокая волатильность {volatility*100:.1f}% + медвежий тренд")

        # ⚡ Дополнительные проверки для краткосрочного тренда
        if trend_1h <= -0.06:  # -6% за час = критично
            should_allow_buy = False
            should_allow_dca = False
            reasons.append("Все покупки заблокированы: критическое часовое падение")

        # 🎯 Разрешения в благоприятных условиях
        if direction in [TrendDirection.BULLISH, TrendDirection.STRONG_BULLISH]:
            should_allow_dca = True
            should_allow_buy = True
            if not reasons:
                reasons.append(f"Бычий тренд: все операции разрешены")

        if direction == TrendDirection.SIDEWAYS and volatility < 0.02:
            # Низкая волатильность + боковик = идеально для торговли
            should_allow_dca = True
            should_allow_buy = True
            if not reasons:
                reasons.append("Боковой тренд с низкой волатильностью: торговля разрешена")

        reason = "; ".join(reasons) if reasons else "Стандартные условия"
        return should_allow_dca, should_allow_buy, reason

    def _log_analysis(self, analysis: TrendAnalysis, current_price: float):
        """📝 Детальное логирование анализа"""

        self.logger.info(f"🧠 АНАЛИЗ ТРЕНДА:")
        self.logger.info(f"   💰 Цена: {current_price:.8f}")
        self.logger.info(f"   📊 Направление: {analysis.direction.value}")
        self.logger.info(f"   💪 Сила: {analysis.strength:.2f}")
        self.logger.info(f"   🎯 Уверенность: {analysis.confidence:.2f}")

        self.logger.info(f"   📈 Тренды:")
        self.logger.info(f"      4ч: {analysis.trend_4h*100:+.2f}%")
        self.logger.info(f"      1ч: {analysis.trend_1h*100:+.2f}%")
        self.logger.info(f"      15м: {analysis.trend_15m*100:+.2f}%")

        self.logger.info(f"   📊 Метки:")
        self.logger.info(f"      Волатильность: {analysis.volatility*100:.2f}%")
        self.logger.info(f"      Моментум: {analysis.momentum*100:+.2f}%")

        # Цветное логирование решений
        dca_status = "✅ РАЗРЕШЕНА" if analysis.should_allow_dca else "🚫 ЗАБЛОКИРОВАНА"
        buy_status = "✅ РАЗРЕШЕНЫ" if analysis.should_allow_buy else "🚫 ЗАБЛОКИРОВАНЫ"

        self.logger.info(f"   🎯 Решения:")
        self.logger.info(f"      DCA: {dca_status}")
        self.logger.info(f"      Покупки: {buy_status}")
        self.logger.info(f"      Причина: {analysis.reason}")

    def _create_default_analysis(self, reason: str) -> TrendAnalysis:
        """🛡️ Создание безопасного анализа по умолчанию"""
        return TrendAnalysis(
            direction=TrendDirection.SIDEWAYS,
            strength=0.0,
            trend_4h=0.0,
            trend_1h=0.0,
            trend_15m=0.0,
            volatility=0.0,
            momentum=0.0,
            confidence=0.0,
            should_allow_dca=False,  # По умолчанию блокируем
            should_allow_buy=False,
            reason=reason
        )

    def get_trend_summary(self) -> Dict:
        """📋 Краткая сводка по тренду"""
        if len(self.prices_1m) == 0:
            return {"status": "no_data"}

        current_price = self.prices_1m[-1][1]
        analysis = self.analyze_trend(current_price)

        return {
            "direction": analysis.direction.value,
            "strength": analysis.strength,
            "confidence": analysis.confidence,
            "trend_4h_percent": analysis.trend_4h * 100,
            "trend_1h_percent": analysis.trend_1h * 100,
            "volatility_percent": analysis.volatility * 100,
            "dca_allowed": analysis.should_allow_dca,
            "buy_allowed": analysis.should_allow_buy,
            "reason": analysis.reason,
            "data_points": {
                "1m": len(self.prices_1m),
                "5m": len(self.prices_5m),
                "15m": len(self.prices_15m),
                "1h": len(self.prices_1h)
            }
        }

    def should_disable_dca(self, current_price: float) -> Tuple[bool, str]:
        """🚫 Быстрая проверка: нужно ли отключить DCA"""
        analysis = self.analyze_trend(current_price)
        return not analysis.should_allow_dca, analysis.reason

    def should_disable_buying(self, current_price: float) -> Tuple[bool, str]:
        """🚫 Быстрая проверка: нужно ли отключить покупки"""
        analysis = self.analyze_trend(current_price)
        return not analysis.should_allow_buy, analysis.reason


# 🔌 Интеграция с основным ботом
class TrendAwareBot:
    """🤖 Торговый бот с интеграцией trend filter"""

    def __init__(self, config):
        self.config = config
        self.trend_filter = AdvancedTrendFilter(config)
        self.logger = logging.getLogger(__name__)
        # ... остальная инициализация бота

    def should_execute_dca(self, current_price: float, drop_percent: float) -> Tuple[bool, str]:
        """🛒 Проверка DCA с учетом тренда"""

        # Стандартные проверки DCA
        if drop_percent < 0.025:  # 2.5%
            return False, f"Недостаточное падение: {drop_percent*100:.1f}%"

        # Проверка тренда
        should_disable, reason = self.trend_filter.should_disable_dca(current_price)
        if should_disable:
            self.logger.warning(f"🚫 DCA заблокирована трендом: {reason}")
            return False, f"Trend filter: {reason}"

        return True, "DCA разрешена"

    def should_execute_buy(self, current_price: float) -> Tuple[bool, str]:
        """🛒 Проверка покупки с учетом тренда"""

        # Проверка тренда
        should_disable, reason = self.trend_filter.should_disable_buying(current_price)
        if should_disable:
            self.logger.warning(f"🚫 Покупки заблокированы трендом: {reason}")
            return False, f"Trend filter: {reason}"

        return True, "Покупки разрешены"


if __name__ == "__main__":
    # Пример использования
    from config import TradingConfig

    config = TradingConfig()
    trend_filter = AdvancedTrendFilter(config)

    # Симуляция ценовых данных
    import random
    base_price = 0.19

    print("🧪 ТЕСТИРОВАНИЕ TREND FILTER")
    print("=" * 50)

    # Симуляция падающего тренда
    for i in range(100):
        # Симулируем падение с небольшой волатильностью
        price_change = -0.001 + random.uniform(-0.002, 0.001)
        base_price *= (1 + price_change)

        if i % 20 == 0:  # Каждые 20 итераций
            analysis = trend_filter.analyze_trend(base_price)
            print(f"\nИтерация {i}: Цена {base_price:.6f}")
            print(f"Тренд 4ч: {analysis.trend_4h*100:+.2f}%")
            print(f"DCA разрешена: {'ДА' if analysis.should_allow_dca else 'НЕТ'}")
            print(f"Причина: {analysis.reason}")

    # Финальная сводка
    summary = trend_filter.get_trend_summary()
    print(f"\n📊 ФИНАЛЬНАЯ СВОДКА:")
    print(f"Направление: {summary['direction']}")
    print(f"Сила тренда: {summary['strength']:.2f}")
    print(f"Тренд 4ч: {summary['trend_4h_percent']:+.2f}%")
    print(f"DCA разрешена: {'ДА' if summary['dca_allowed'] else 'НЕТ'}")
