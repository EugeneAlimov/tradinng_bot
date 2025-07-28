# technical_indicators.py
import statistics
from typing import List, Tuple


class TechnicalIndicators:
    """Технические индикаторы для анализа"""

    @staticmethod
    def sma(prices: List[float], period: int) -> float:
        """Простая скользящая средняя"""
        if len(prices) < period:
            return sum(prices) / len(prices) if prices else 0
        return sum(prices[-period:]) / period

    @staticmethod
    def ema(prices: List[float], period: int) -> float:
        """Экспоненциальная скользящая средняя"""
        if not prices:
            return 0
        if len(prices) == 1:
            return prices[0]

        multiplier = 2 / (period + 1)
        ema = prices[0]

        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))

        return ema

    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        """🔧 ИСПРАВЛЕННЫЙ расчет RSI с защитой от глюков"""

        # 🛡️ Базовые проверки
        if not prices or len(prices) < 2:
            return 50.0  # Нейтральное значение

        # Для RSI нужно минимум period + 1 значений
        if len(prices) < period + 1:
            return 50.0  # Недостаточно данных

        # 🔧 ИСПРАВЛЕНИЕ: Ограничиваем размер массива для стабильности
        if len(prices) > period * 3:
            prices = prices[-(period * 2):]  # Берем только последние значения

        # 📊 Рассчитываем изменения цен
        changes = []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            changes.append(change)

        # 🛡️ Проверяем есть ли изменения
        if not changes:
            return 50.0

        # 🔧 ИСПРАВЛЕНИЕ: Проверяем на вырожденные случаи
        max_change = max(abs(c) for c in changes)
        if max_change < 0.000001:  # Цены практически не меняются
            return 50.0  # RSI неопределен

        # 📈 Разделяем на рост и падения
        gains = []
        losses = []

        for change in changes:
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            elif change < 0:
                gains.append(0.0)
                losses.append(-change)  # Превращаем в положительное
            else:
                gains.append(0.0)
                losses.append(0.0)

        # 🔧 ИСПРАВЛЕНИЕ: Используем только последние period значений
        if len(gains) > period:
            gains = gains[-period:]
            losses = losses[-period:]

        # 📊 Рассчитываем средние значения
        avg_gain = sum(gains) / len(gains) if gains else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        # 🛡️ ИСПРАВЛЕНИЕ: Защита от деления на ноль
        if avg_loss == 0.0:
            if avg_gain == 0.0:
                return 50.0  # Нет изменений
            else:
                return 100.0  # Только рост

        if avg_gain == 0.0:
            return 0.0  # Только падения

        # 📈 Финальный расчет RSI
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # 🔧 ИСПРАВЛЕНИЕ: Ограничиваем диапазон
        rsi = max(0.0, min(100.0, rsi))

        # 🛡️ ИСПРАВЛЕНИЕ: Проверяем на разумность результата
        if rsi < 0.1 or rsi > 99.9:
            # Экстремальные значения часто означают ошибку
            return 50.0

        return rsi

    @staticmethod
    def bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2) -> Tuple[float, float, float]:
        """Полосы Боллинджера (верхняя, средняя, нижняя)"""
        if len(prices) < period:
            sma = sum(prices) / len(prices) if prices else 0
            return sma, sma, sma

        recent_prices = prices[-period:]
        sma = sum(recent_prices) / period
        variance = sum((price - sma) ** 2 for price in recent_prices) / period
        std = variance ** 0.5

        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)

        return upper, sma, lower

    # 🔍 ДОПОЛНИТЕЛЬНО: Функция диагностики RSI для отладки
    @staticmethod
    def debug_rsi(prices: List[float], period: int = 14) -> dict:
        """🔍 Диагностика расчета RSI"""

        if len(prices) < period + 1:
            return {
                'error': 'Недостаточно данных',
                'prices_count': len(prices),
                'required': period + 1
            }

        # Берем последние значения
        recent_prices = prices[-(period + 5):] if len(prices) > period + 5 else prices

        # Рассчитываем изменения
        changes = []
        for i in range(1, len(recent_prices)):
            change = recent_prices[i] - recent_prices[i - 1]
            changes.append(change)

        # Анализируем изменения
        gains = [c for c in changes if c > 0]
        losses = [-c for c in changes if c < 0]  # Положительные значения

        recent_changes = changes[-10:] if len(changes) > 10 else changes

        return {
            'prices_count': len(recent_prices),
            'changes_count': len(changes),
            'recent_prices': [round(p, 6) for p in recent_prices[-5:]],
            'recent_changes': [round(c, 6) for c in recent_changes],
            'gains_count': len(gains),
            'losses_count': len(losses),
            'avg_gain': sum(gains[-period:]) / min(period, len(gains)) if gains else 0,
            'avg_loss': sum(losses[-period:]) / min(period, len(losses)) if losses else 0,
            'max_change': max(abs(c) for c in changes) if changes else 0,
            'price_range': max(recent_prices) - min(recent_prices)
        }