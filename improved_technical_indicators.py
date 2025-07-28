# improved_technical_indicators.py - Исправленные технические индикаторы
import statistics
from typing import List, Tuple, Optional, Dict
import logging


class ImprovedTechnicalIndicators:
    """📈 Улучшенные технические индикаторы без глюков"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # Кэш для оптимизации повторных вычислений
        self._rsi_cache = {}
        self._price_hash_cache = None

    @staticmethod
    def sma(prices: List[float], period: int) -> float:
        """📊 Простая скользящая средняя"""
        if not prices:
            return 0.0
        if len(prices) < period:
            return sum(prices) / len(prices)
        return sum(prices[-period:]) / period

    @staticmethod
    def ema(prices: List[float], period: int) -> float:
        """📈 Экспоненциальная скользящая средняя"""
        if not prices:
            return 0.0
        if len(prices) == 1:
            return prices[0]

        multiplier = 2.0 / (period + 1)
        ema = prices[0]

        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))

        return ema

    def rsi(self, prices: List[float], period: int = 14) -> float:
        """🎯 ИСПРАВЛЕННЫЙ RSI без глюков"""

        # Валидация входных данных
        if not prices or len(prices) < 2:
            return 50.0

        if period < 2:
            period = 14

        # Нужно минимум period + 1 значений для корректного RSI
        if len(prices) < period + 1:
            return 50.0

        # Проверяем кэш (оптимизация)
        prices_hash = hash(tuple(prices[-period - 5:]))  # Хэш последних значений
        cache_key = (prices_hash, period)

        if cache_key in self._rsi_cache:
            return self._rsi_cache[cache_key]

        try:
            # Используем проверенный алгоритм Wilder
            rsi_value = self._calculate_rsi_wilder(prices, period)

            # Кэшируем результат
            self._rsi_cache[cache_key] = rsi_value

            # Ограничиваем размер кэша
            if len(self._rsi_cache) > 100:
                # Удаляем старые записи
                old_keys = list(self._rsi_cache.keys())[:-50]
                for key in old_keys:
                    del self._rsi_cache[key]

            return rsi_value

        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета RSI: {e}")
            return 50.0  # Безопасное значение

    def _calculate_rsi_wilder(self, prices: List[float], period: int) -> float:
        """📊 RSI по методу Уайлдера (классический алгоритм)"""

        # Берем нужное количество цен
        working_prices = prices[-(period + 10):] if len(prices) > period + 10 else prices

        if len(working_prices) < period + 1:
            return 50.0

        # Рассчитываем изменения
        changes = []
        for i in range(1, len(working_prices)):
            change = working_prices[i] - working_prices[i - 1]
            changes.append(change)

        if len(changes) < period:
            return 50.0

        # Разделяем на прибыли и убытки
        gains = []
        losses = []

        for change in changes:
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            elif change < 0:
                gains.append(0.0)
                losses.append(-change)  # Положительное значение
            else:
                gains.append(0.0)
                losses.append(0.0)

        # Инициализация первых средних значений (простая средняя)
        first_gains = gains[:period]
        first_losses = losses[:period]

        avg_gain = sum(first_gains) / period
        avg_loss = sum(first_losses) / period

        # Применяем сглаживание Уайлдера для остальных значений
        for i in range(period, len(gains)):
            avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

        # Рассчитываем RSI
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # Санитарная проверка результата
        if rsi < 0 or rsi > 100 or not isinstance(rsi, (int, float)):
            self.logger.warning(f"⚠️ Некорректный RSI: {rsi}, возвращаем 50")
            return 50.0

        return rsi

    def rsi_with_validation(self, prices: List[float], period: int = 14) -> Tuple[float, Dict[str, any]]:
        """🔍 RSI с полной диагностикой для отладки"""

        validation_info = {
            'input_valid': True,
            'prices_count': len(prices),
            'period': period,
            'sufficient_data': len(prices) >= period + 1,
            'price_range': 0.0,
            'avg_change': 0.0,
            'calculation_method': 'wilder'
        }

        if not prices or len(prices) < 2:
            validation_info['input_valid'] = False
            validation_info['error'] = 'Недостаточно цен'
            return 50.0, validation_info

        if len(prices) >= 2:
            validation_info['price_range'] = max(prices) - min(prices)

            changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
            validation_info['avg_change'] = sum(changes) / len(changes) if changes else 0
            validation_info['max_change'] = max(abs(c) for c in changes) if changes else 0

        if validation_info['max_change'] < 0.000001:
            validation_info['error'] = 'Цены практически не меняются'
            return 50.0, validation_info

        rsi_value = self.rsi(prices, period)
        validation_info['calculated_rsi'] = rsi_value

        return rsi_value, validation_info

    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float]:
        """📊 Полосы Боллинджера"""
        if not prices:
            return 0.0, 0.0, 0.0

        if len(prices) < period:
            # Если данных мало, используем все доступные
            working_prices = prices
            period = len(prices)
        else:
            working_prices = prices[-period:]

        # Средняя
        sma = sum(working_prices) / len(working_prices)

        # Стандартное отклонение
        if len(working_prices) == 1:
            std = 0.0
        else:
            variance = sum((price - sma) ** 2 for price in working_prices) / len(working_prices)
            std = variance ** 0.5

        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)

        return upper, sma, lower

    def stochastic_rsi(self, prices: List[float], period: int = 14, stoch_period: int = 14) -> Tuple[float, float]:
        """📈 Стохастический RSI (альтернатива обычному RSI)"""

        if len(prices) < period + stoch_period:
            return 50.0, 50.0

        # Рассчитываем RSI для каждой точки
        rsi_values = []
        for i in range(period, len(prices) + 1):
            slice_prices = prices[i - period:i]
            rsi_val = self.rsi(slice_prices, period)
            rsi_values.append(rsi_val)

        if len(rsi_values) < stoch_period:
            return 50.0, 50.0

        # Берем последние stoch_period значений RSI
        recent_rsi = rsi_values[-stoch_period:]

        rsi_min = min(recent_rsi)
        rsi_max = max(recent_rsi)
        current_rsi = recent_rsi[-1]

        # Стохастический RSI
        if rsi_max == rsi_min:
            stoch_rsi = 50.0
        else:
            stoch_rsi = ((current_rsi - rsi_min) / (rsi_max - rsi_min)) * 100

        # %D (сглаженная версия)
        if len(recent_rsi) >= 3:
            recent_stoch = []
            for i in range(len(recent_rsi)):
                if i < len(recent_rsi) - 2:
                    continue

                slice_rsi = recent_rsi[max(0, i - 2):i + 1]
                slice_min = min(slice_rsi)
                slice_max = max(slice_rsi)

                if slice_max == slice_min:
                    slice_stoch = 50.0
                else:
                    slice_stoch = ((slice_rsi[-1] - slice_min) / (slice_max - slice_min)) * 100

                recent_stoch.append(slice_stoch)

            stoch_rsi_d = sum(recent_stoch) / len(recent_stoch) if recent_stoch else stoch_rsi
        else:
            stoch_rsi_d = stoch_rsi

        return stoch_rsi, stoch_rsi_d

    def williams_r(self, high_prices: List[float], low_prices: List[float],
                   close_prices: List[float], period: int = 14) -> float:
        """📉 Williams %R (еще одна альтернатива RSI)"""

        if (len(high_prices) < period or len(low_prices) < period or
                len(close_prices) < period):
            return -50.0  # Нейтральное значение для Williams %R

        # Берем последние period значений
        recent_highs = high_prices[-period:]
        recent_lows = low_prices[-period:]
        current_close = close_prices[-1]

        highest_high = max(recent_highs)
        lowest_low = min(recent_lows)

        if highest_high == lowest_low:
            return -50.0

        williams_r = ((highest_high - current_close) / (highest_high - lowest_low)) * -100

        return williams_r

    def adaptive_rsi(self, prices: List[float], min_period: int = 8, max_period: int = 21) -> float:
        """🎯 Адаптивный RSI - автоматически подбирает период"""

        if len(prices) < max_period + 1:
            # Недостаточно данных для адаптивного RSI
            return self.rsi(prices, min_period)

        # Рассчитываем волатильность для определения оптимального периода
        recent_prices = prices[-max_period:]
        returns = [recent_prices[i] / recent_prices[i - 1] - 1 for i in range(1, len(recent_prices))]

        volatility = statistics.stdev(returns) if len(returns) > 1 else 0

        # Высокая волатильность -> короткий период
        # Низкая волатильность -> длинный период
        if volatility > 0.02:  # 2% дневная волатильность
            period = min_period
        elif volatility < 0.005:  # 0.5% дневная волатильность
            period = max_period
        else:
            # Линейная интерполяция
            period = int(min_period + (max_period - min_period) * (0.02 - volatility) / 0.015)
            period = max(min_period, min(max_period, period))

        return self.rsi(prices, period)

    def get_indicator_summary(self, prices: List[float]) -> Dict[str, float]:
        """📊 Сводка всех индикаторов"""

        if len(prices) < 20:
            return {'error': 'Недостаточно данных для полного анализа'}

        summary = {}

        try:
            # Основные индикаторы
            summary['rsi_14'] = self.rsi(prices, 14)
            summary['rsi_21'] = self.rsi(prices, 21)
            summary['adaptive_rsi'] = self.adaptive_rsi(prices)

            # Стохастический RSI
            stoch_rsi, stoch_rsi_d = self.stochastic_rsi(prices)
            summary['stoch_rsi'] = stoch_rsi
            summary['stoch_rsi_d'] = stoch_rsi_d

            # Скользящие средние
            summary['sma_10'] = self.sma(prices, 10)
            summary['sma_20'] = self.sma(prices, 20)
            summary['ema_12'] = self.ema(prices, 12)

            # Bollinger Bands
            bb_upper, bb_middle, bb_lower = self.bollinger_bands(prices)
            summary['bb_upper'] = bb_upper
            summary['bb_middle'] = bb_middle
            summary['bb_lower'] = bb_lower
            summary['bb_position'] = ((prices[-1] - bb_lower) / (bb_upper - bb_lower)) if bb_upper != bb_lower else 0.5

            # Дополнительные метрики
            summary['current_price'] = prices[-1]
            summary['price_vs_sma20'] = (prices[-1] / summary['sma_20'] - 1) * 100 if summary['sma_20'] > 0 else 0
            summary['price_vs_ema12'] = (prices[-1] / summary['ema_12'] - 1) * 100 if summary['ema_12'] > 0 else 0

        except Exception as e:
            self.logger.error(f"❌ Ошибка расчета индикаторов: {e}")
            summary['error'] = str(e)

        return summary


# Функция для замены старого класса
def get_improved_indicators():
    """🔧 Получение улучшенных индикаторов"""
    return ImprovedTechnicalIndicators()


# Тестирование нового RSI
if __name__ == "__main__":

    # Тестовые данные - реальные цены DOGE
    test_prices = [
        0.18234, 0.18245, 0.18198, 0.18167, 0.18189,
        0.18156, 0.18178, 0.18234, 0.18267, 0.18298,
        0.18245, 0.18223, 0.18178, 0.18134, 0.18156,
        0.18189, 0.18234, 0.18267, 0.18289, 0.18234,
        0.18198, 0.18167, 0.18134, 0.18098, 0.18067,
        0.18089, 0.18123, 0.18156, 0.18189, 0.18234
    ]

    indicators = ImprovedTechnicalIndicators()

    print("🧪 ТЕСТИРОВАНИЕ УЛУЧШЕННЫХ ИНДИКАТОРОВ")
    print("=" * 50)

    # Тест RSI
    print("📈 RSI тестирование:")
    rsi_value = indicators.rsi(test_prices)
    print(f"   RSI(14): {rsi_value:.2f}")

    # Тест с валидацией
    rsi_val, validation = indicators.rsi_with_validation(test_prices)
    print(f"   RSI с валидацией: {rsi_val:.2f}")
    print(f"   Диагностика: {validation}")

    # Адаптивный RSI
    adaptive_rsi = indicators.adaptive_rsi(test_prices)
    print(f"   Адаптивный RSI: {adaptive_rsi:.2f}")

    # Стохастический RSI
    stoch_rsi, stoch_d = indicators.stochastic_rsi(test_prices)
    print(f"   Стохастический RSI: {stoch_rsi:.2f}, %D: {stoch_d:.2f}")

    # Полная сводка
    print("\n📊 Полная сводка индикаторов:")
    summary = indicators.get_indicator_summary(test_prices)
    for key, value in summary.items():
        if isinstance(value, float):
            print(f"   {key}: {value:.4f}")
        else:
            print(f"   {key}: {value}")

    print("\n✅ Тестирование завершено!")