from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple, List
import logging
import time
from config import TradingConfig
from technical_indicators import TechnicalIndicators


class TradingStrategy(ABC):
    def __init__(self, config: TradingConfig, api_client, risk_manager):
        self.config = config
        self.api = api_client
        self.risk_manager = risk_manager
        self.logger = logging.getLogger(__name__)

    @abstractmethod
    def should_buy(self, market_data: Dict[str, Any]) -> Tuple[bool, float, float]:
        """Возвращает (should_buy, quantity, price)"""
        pass

    @abstractmethod
    def should_sell(self, market_data: Dict[str, Any], position: Dict[str, Any]) -> Tuple[bool, float, float]:
        """Возвращает (should_sell, quantity, price)"""
        pass


class MeanReversionStrategy(TradingStrategy):
    def __init__(self, config: TradingConfig, api_client, risk_manager, position_manager):
        super().__init__(config, api_client, risk_manager)
        self.recent_prices = []
        self.position_manager = position_manager
        self.indicators = TechnicalIndicators()

        # 🛡️ КОНСЕРВАТИВНЫЕ параметры
        self.min_data_points = self.config.MIN_DATA_POINTS
        self.last_trade_time = 0
        self.min_time_between_trades = self.config.MIN_TIME_BETWEEN_TRADES

        # 📊 Счетчики для статистики
        self.trade_count_today = 0
        self.last_trade_reset = time.time()

        # 🚫 ОТКЛЮЧАЕМ принудительную торговлю
        if self.config.FORCE_TRADE_DISABLED:
            self.logger.info("🛡️  Принудительная торговля ОТКЛЮЧЕНА")

    def _update_prices(self, current_price: float):
        """📊 Обновление списка цен"""
        self.recent_prices.append(current_price)
        if len(self.recent_prices) > self.config.VOLATILITY_PERIOD:
            self.recent_prices.pop(0)

    def get_average_price(self) -> float:
        """📊 Получение средней цены"""
        if not self.recent_prices:
            return 0.0
        return sum(self.recent_prices) / len(self.recent_prices)

    def _check_trade_limits(self) -> Tuple[bool, str]:
        """🚫 Проверка лимитов на торговлю"""
        current_time = time.time()

        # Сброс счетчика в новом дне
        if current_time - self.last_trade_reset > 86400:  # 24 часа
            self.trade_count_today = 0
            self.last_trade_reset = current_time

        # Проверка лимита сделок в час
        if hasattr(self.config, 'MAX_TRADES_PER_HOUR'):
            # Простая проверка - не более 2 сделок в час
            if current_time - self.last_trade_time < 1800:  # 30 минут
                remaining = 1800 - (current_time - self.last_trade_time)
                return False, f"Кулдаун между сделками: {remaining / 60:.0f} мин"

        # Проверка минимального времени между сделками
        if current_time - self.last_trade_time < self.min_time_between_trades:
            remaining = self.min_time_between_trades - (current_time - self.last_trade_time)
            return False, f"Минимальный интервал: {remaining / 60:.0f} мин"

        return True, "OK"

    def _validate_trade_profitability(self, order_type: str, price: float, quantity: float,
                                      position_price: float = None) -> Tuple[bool, str]:
        """💰 Проверка прибыльности сделки до ее совершения"""

        commission_cost = 0.006  # 0.6% туда и обратно

        if order_type == 'buy':
            # Для покупки: проверяем что сможем продать с прибылью
            min_sell_price = price * (1 + self.config.MIN_PROFIT_TO_SELL + commission_cost)

            self.logger.info(f"💡 Анализ покупки:")
            self.logger.info(f"   Цена покупки: {price:.8f}")
            self.logger.info(f"   Минимальная цена продажи: {min_sell_price:.8f}")
            self.logger.info(f"   Требуемая прибыль: {self.config.MIN_PROFIT_TO_SELL * 100:.1f}%")

            return True, "Покупка разрешена"

        elif order_type == 'sell' and position_price:
            # Для продажи: обязательная проверка прибыли
            profit_percent = (price - position_price) / position_price
            profit_after_commission = profit_percent - commission_cost

            self.logger.info(f"💡 Анализ продажи:")
            self.logger.info(f"   Цена покупки: {position_price:.8f}")
            self.logger.info(f"   Цена продажи: {price:.8f}")
            self.logger.info(f"   Прибыль до комиссий: {profit_percent * 100:.2f}%")
            self.logger.info(f"   Прибыль после комиссий: {profit_after_commission * 100:.2f}%")
            self.logger.info(f"   Требуемая прибыль: {self.config.MIN_PROFIT_TO_SELL * 100:.1f}%")

            if profit_percent < self.config.MIN_PROFIT_TO_SELL:
                return False, f"Недостаточная прибыль: {profit_percent * 100:.2f}% < {self.config.MIN_PROFIT_TO_SELL * 100:.1f}%"

            if profit_after_commission < 0:
                return False, f"Убыток после комиссий: {profit_after_commission * 100:.2f}%"

            return True, f"Прибыльная продажа: {profit_after_commission * 100:.2f}%"

        return True, "OK"

    def _analyze_market_conditions(self, current_price: float) -> Dict[str, Any]:
        """📊 Комплексный анализ рынка с улучшенными фильтрами"""
        if len(self.recent_prices) < self.min_data_points:
            return {
                'ready': False,
                'reason': f'Накапливаем данные: {len(self.recent_prices)}/{self.min_data_points}',
                'data_points': len(self.recent_prices)
            }

        # Базовые показатели
        sma_short = self.indicators.sma(self.recent_prices, 10)
        sma_long = self.indicators.sma(self.recent_prices, 20) if len(self.recent_prices) >= 20 else sma_short
        ema = self.indicators.ema(self.recent_prices, 12)
        rsi = self.indicators.rsi(self.recent_prices)

        # Полосы Боллинджера
        bb_upper, bb_middle, bb_lower = self.indicators.bollinger_bands(self.recent_prices)

        # Волатильность
        volatility = self.risk_manager.calculate_volatility(self.recent_prices)

        # 🚫 СТРОГАЯ проверка волатильности
        if volatility < self.config.MIN_VOLATILITY_THRESHOLD:
            return {
                'ready': False,
                'reason': f'Низкая волатильность: {volatility:.4f} < {self.config.MIN_VOLATILITY_THRESHOLD:.4f}',
                'volatility': volatility
            }

        # Тренд
        trend_strength = (sma_short - sma_long) / sma_long if sma_long > 0 else 0

        # Позиция относительно Боллинджера
        bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5

        return {
            'ready': True,
            'current_price': current_price,
            'sma_short': sma_short,
            'sma_long': sma_long,
            'ema': ema,
            'rsi': rsi,
            'bb_upper': bb_upper,
            'bb_middle': bb_middle,
            'bb_lower': bb_lower,
            'bb_position': bb_position,
            'volatility': volatility,
            'trend_strength': trend_strength,
            'data_points': len(self.recent_prices)
        }

    def _calculate_conservative_buy_price(self, current_price: float, analysis: Dict, signal_strength: int) -> float:
        """💰 Консервативное ценообразование для покупки"""

        volatility = analysis.get('volatility', 0.002)

        # Базовый спред увеличен для прибыльности
        base_spread = self.config.BASE_PROFIT_MARKUP

        # Адаптация к волатильности (консервативная)
        volatility_multiplier = min(1.5, max(0.8, volatility * 50))
        adaptive_spread = base_spread * volatility_multiplier

        # Корректировка на силу сигнала (более консервативная)
        if signal_strength >= 4:
            # Очень сильный сигнал - небольшая скидка
            price_adjustment = -adaptive_spread * 0.3
            signal_desc = "ОЧЕНЬ СИЛЬНЫЙ"
        elif signal_strength >= 3:
            # Сильный сигнал - средняя скидка
            price_adjustment = -adaptive_spread * 0.5
            signal_desc = "СИЛЬНЫЙ"
        elif signal_strength >= 2:
            # Средний сигнал - обычная скидка
            price_adjustment = -adaptive_spread * 0.7
            signal_desc = "СРЕДНИЙ"
        else:
            # Слабый сигнал - большая скидка
            price_adjustment = -adaptive_spread * 1.0
            signal_desc = "СЛАБЫЙ"

        buy_price = current_price * (1 + price_adjustment)

        # Первое ограничение: MAX_PRICE_DEVIATION из конфига
        max_discount_config = self.config.MAX_PRICE_DEVIATION
        min_buy_price_config = current_price * (1 - max_discount_config)
        buy_price = max(buy_price, min_buy_price_config)

        # 🎯 ВТОРОЕ ОГРАНИЧЕНИЕ: Специально для DOGE (более строгое)
        max_allowed_discount_percent = 0.0015  # 0.15% максимум для DOGE
        min_allowed_price = current_price * (1 - max_allowed_discount_percent)

        if buy_price < min_allowed_price:
            old_discount_percent = (current_price - buy_price) / current_price * 100
            buy_price = min_allowed_price
            new_discount_percent = (current_price - buy_price) / current_price * 100

            self.logger.info(f"🔧 ОГРАНИЧЕНИЕ СКИДКИ ДЛЯ DOGE:")
            self.logger.info(f"   Расчетная скидка: {old_discount_percent:.2f}%")
            self.logger.info(f"   Ограничена до: {new_discount_percent:.2f}%")
            self.logger.info(f"   Причина: DOGE требует малых скидок для исполнения")

        # Финальное логирование
        self.logger.info(f"💰 Ценообразование покупки:")
        self.logger.info(f"   Сигнал: {signal_desc} ({signal_strength} баллов)")
        self.logger.info(f"   Волатильность: {volatility:.4f}, множитель: {volatility_multiplier:.2f}")
        self.logger.info(f"   Базовый спред: {base_spread:.4f}, адаптивный: {adaptive_spread:.4f}")
        self.logger.info(f"   Корректировка: {price_adjustment:+.4f} ({price_adjustment * 100:+.2f}%)")
        self.logger.info(
            f"   Финальная цена: {buy_price:.8f} (скидка {((current_price - buy_price) / current_price * 100):.2f}%)")

        return buy_price

    def should_buy(self, market_data: Dict[str, Any]) -> Tuple[bool, float, float]:
        """🛒 КОНСЕРВАТИВНАЯ логика покупки"""
        current_price = market_data.get('current_price', 0.0)
        balance = market_data.get('balance', 0.0)

        self._update_prices(current_price)

        if len(self.recent_prices) >= 10:
            self._debug_rsi_issues(self.recent_prices)

        # 🚫 Проверка лимитов торговли
        can_trade, limit_reason = self._check_trade_limits()
        if not can_trade:
            self.logger.info(f"⏸️  {limit_reason}")
            return False, 0.0, 0.0

        # 📊 Анализ рынка
        analysis = self._analyze_market_conditions(current_price)

        if not analysis['ready']:
            self.logger.info(f"⏸️  {analysis['reason']}")
            return False, 0.0, 0.0

        self.logger.info(f"📊 Технический анализ:")
        self.logger.info(f"   💹 RSI: {analysis['rsi']:.1f}")
        self.logger.info(f"   📏 Bollinger позиция: {analysis['bb_position']:.2f}")
        self.logger.info(f"   📈 Тренд: {analysis['trend_strength']:+.3f}")
        self.logger.info(f"   🌊 Волатильность: {analysis['volatility']:.4f}")

        # 🎯 СТРОГИЕ условия для покупки
        conditions = {
            'deeply_oversold': analysis['rsi'] < 30,  # Глубоко перепродан
            'very_low_bb': analysis['bb_position'] < 0.2,  # В нижних 20% Bollinger
            'below_ema': current_price < analysis['ema'] * 0.995,  # Ниже EMA на 0.5%+
            'downtrend': analysis['trend_strength'] < -0.005,  # Четкий нисходящий тренд
            'sufficient_volatility': analysis['volatility'] > self.config.MIN_VOLATILITY_THRESHOLD,
            'strong_dip': current_price < analysis['sma_short'] * 0.99  # Ниже короткой MA на 1%+
        }

        # Логируем каждое условие
        met_conditions = []
        for condition_name, is_met in conditions.items():
            status = "✅" if is_met else "❌"
            self.logger.info(f"   {status} {condition_name}")
            if is_met:
                met_conditions.append(condition_name)

        conditions_met = len(met_conditions)

        # 🚫 ТРЕБУЕМ МИНИМУМ 3 УСЛОВИЯ для покупки
        if conditions_met < 2: # 3:
            self.logger.info(f"⏸️  Недостаточно условий для покупки: {conditions_met}/6")
            self.logger.info(f"💡 Нужно минимум 2 условия для безопасной покупки")
            return False, 0.0, 0.0

        # 💰 Рассчитываем цену и количество
        buy_price = self._calculate_conservative_buy_price(current_price, analysis, conditions_met)
        max_spend = balance * self.config.MAX_POSITION_SIZE
        quantity = max_spend / buy_price

        # 🛡️ Валидация прибыльности
        is_profitable, profit_reason = self._validate_trade_profitability('buy', buy_price, quantity)
        if not is_profitable:
            self.logger.warning(f"🚫 Покупка отменена: {profit_reason}")
            return False, 0.0, 0.0

        self.logger.info(f"🎯 СИГНАЛ ПОКУПКИ!")
        self.logger.info(f"   Условий выполнено: {conditions_met}/6: {', '.join(met_conditions)}")
        self.logger.info(f"   Планируем купить: {quantity:.4f} по {buy_price:.8f}")
        self.logger.info(f"   Сумма: {max_spend:.2f} EUR ({self.config.MAX_POSITION_SIZE * 100:.0f}% от баланса)")
        self.logger.info(f"   Скидка от рынка: {((current_price - buy_price) / current_price * 100):.2f}%")

        if self.risk_manager.can_open_position(max_spend, balance):
            self.last_trade_time = time.time()
            self.trade_count_today += 1
            return True, quantity, buy_price
        else:
            self.logger.warning("🚫 Риск-менеджер запретил открытие позиции")

        return False, 0.0, 0.0

    def should_sell(self, market_data: Dict[str, Any], position: Dict[str, Any]) -> Tuple[bool, float, float]:
        """💎 КОНСЕРВАТИВНАЯ логика продажи с защитой от убытков"""
        current_price = market_data.get('current_price', 0.0)
        quantity = position.get('quantity', 0.0)

        if not quantity:
            return False, 0.0, 0.0

        # 🚫 Проверка лимитов торговли
        can_trade, limit_reason = self._check_trade_limits()
        if not can_trade:
            self.logger.info(f"⏸️  {limit_reason}")
            return False, 0.0, 0.0

        # Получаем реальную позицию из истории торгов
        real_position = self.position_manager.get_position(self.config.CURRENCY_1)
        if not real_position:
            self.logger.warning("❓ Нет данных о позиции в истории торгов")
            return False, 0.0, 0.0

        position_price = real_position.avg_price
        quantity = min(quantity, real_position.quantity)

        # Рассчитываем потенциальную прибыль
        potential_profit = (current_price - position_price) / position_price

        self.logger.info(f"💎 Анализ продажи:")
        self.logger.info(f"   Цена покупки: {position_price:.8f}")
        self.logger.info(f"   Текущая цена: {current_price:.8f}")
        self.logger.info(f"   Потенциальная прибыль: {potential_profit * 100:+.2f}%")
        self.logger.info(f"   Количество: {quantity:.6f}")

        # 🚨 ЭКСТРЕННЫЙ СТОП-ЛОСС
        stop_loss_threshold = -self.config.STOP_LOSS_PERCENT
        if potential_profit <= stop_loss_threshold:
            loss_percent = potential_profit * 100
            self.logger.error(f"🚨 СТОП-ЛОСС! Убыток: {loss_percent:.2f}%")
            sell_price = current_price * 0.999  # Продаем немного ниже рынка для быстрого исполнения
            self.last_trade_time = time.time()
            return True, quantity, sell_price

        # 🚫 НЕ ПРОДАЕМ при недостаточной прибыли
        if potential_profit < self.config.MIN_PROFIT_TO_SELL:
            self.logger.info(
                f"⏸️  Держим позицию: прибыль {potential_profit * 100:.2f}% < порога {self.config.MIN_PROFIT_TO_SELL * 100:.1f}%")
            return False, 0.0, 0.0

        # 📊 Получаем технический анализ
        analysis = self._analyze_market_conditions(current_price)

        if not analysis['ready']:
            # Если нет достаточных данных для анализа, но прибыль большая - продаем
            if potential_profit >= self.config.FAST_PROFIT_THRESHOLD / 100:
                self.logger.info(f"💎 БЫСТРАЯ ПРОДАЖА! Отличная прибыль: {potential_profit * 100:.2f}%")
                sell_price = current_price * 0.9998
                self.last_trade_time = time.time()
                return True, quantity, sell_price
            return False, 0.0, 0.0

        # 🎯 БЫСТРАЯ ПРОДАЖА при отличной прибыли
        if potential_profit >= self.config.FAST_PROFIT_THRESHOLD / 100:
            self.logger.info(f"💎 БЫСТРАЯ ПРОДАЖА! Отличная прибыль: {potential_profit * 100:.2f}%")
            sell_price = current_price * 0.9998  # Продаем близко к рынку

            # Валидация прибыльности
            is_profitable, profit_reason = self._validate_trade_profitability('sell', sell_price, quantity,
                                                                              position_price)
            if is_profitable:
                self.last_trade_time = time.time()
                return True, quantity, sell_price
            else:
                self.logger.warning(f"🚫 Быстрая продажа отменена: {profit_reason}")

        # 📊 ТЕХНИЧЕСКИЙ АНАЛИЗ для обычных продаж
        self.logger.info(f"📊 Технический анализ для продажи:")
        self.logger.info(f"   💹 RSI: {analysis['rsi']:.1f}")
        self.logger.info(f"   📏 Bollinger позиция: {analysis['bb_position']:.2f}")
        self.logger.info(f"   📈 vs EMA: {(current_price / analysis['ema'] - 1) * 100:+.2f}%")
        self.logger.info(f"   🌊 Волатильность: {analysis['volatility']:.4f}")

        # 🎯 СТРОГИЕ условия продажи
        sell_conditions = {
            'good_profit': potential_profit >= self.config.MIN_PROFIT_TO_SELL,
            'overbought_rsi': analysis['rsi'] > 70,  # Строже: 70 вместо 55
            'high_bb_position': analysis['bb_position'] > 0.8,  # Строже: 80% вместо 65%
            'above_ema': current_price > analysis['ema'] * 1.01,  # Строже: +1% вместо +0.03%
            'uptrend': analysis['trend_strength'] > 0.005,  # Восходящий тренд
        }

        # Логируем условия продажи
        met_sell_conditions = []
        for condition_name, is_met in sell_conditions.items():
            status = "✅" if is_met else "❌"
            self.logger.info(f"   {status} {condition_name}")
            if is_met:
                met_sell_conditions.append(condition_name)

        sell_conditions_met = len(met_sell_conditions)

        # 🚫 ТРЕБУЕМ МИНИМУМ 3 УСЛОВИЯ для продажи (кроме быстрой прибыли)
        if sell_conditions_met < 3:
            self.logger.info(f"⏸️  Недостаточно условий для продажи: {sell_conditions_met}/5")
            self.logger.info(f"💎 Держим позицию, ждем лучших условий")
            return False, 0.0, 0.0

        # 💰 Рассчитываем цену продажи с достаточной надбавкой
        volatility = analysis['volatility']
        spread_multiplier = max(1.0, min(2.0, volatility * 100))  # От 1x до 2x от волатильности
        spread = self.config.MIN_SPREAD * spread_multiplier

        sell_price = current_price * (1 + spread)

        # 🛡️ Валидация прибыльности
        is_profitable, profit_reason = self._validate_trade_profitability('sell', sell_price, quantity, position_price)
        if not is_profitable:
            self.logger.warning(f"🚫 Продажа отменена: {profit_reason}")
            return False, 0.0, 0.0

        final_profit = (sell_price - position_price) / position_price

        self.logger.info(f"🎯 СИГНАЛ ПРОДАЖИ!")
        self.logger.info(f"   Условий выполнено: {sell_conditions_met}/5: {', '.join(met_sell_conditions)}")
        self.logger.info(f"   Цена продажи: {sell_price:.8f} (+{spread * 100:.2f}% к рынку)")
        self.logger.info(f"   Финальная прибыль: {final_profit * 100:+.2f}%")

        self.last_trade_time = time.time()
        self.trade_count_today += 1
        return True, quantity, sell_price

    # 🔧 Дополнительно:
    def _debug_rsi_issues(self, prices: List[float]):
        """🔍 Отладка проблем с RSI"""

        if len(prices) >= 10:
            # ИСПРАВЛЕНИЕ: Используем debug_rsi из indicators
            debug_info = self.indicators.debug_rsi(prices)

            # Проверяем есть ли ошибка
            if 'error' in debug_info:
                self.logger.info(f"🔍 RSI ДИАГНОСТИКА: {debug_info['error']}")
                return

            self.logger.info(f"🔍 RSI ДИАГНОСТИКА:")
            self.logger.info(f"   📊 Точек данных: {debug_info.get('prices_count', 0)}")
            self.logger.info(f"   📈 Последние цены: {debug_info.get('recent_prices', [])}")
            self.logger.info(f"   🔄 Изменения: {debug_info.get('recent_changes', [])}")
            self.logger.info(f"   ⬆️ Средний рост: {debug_info.get('avg_gain', 0):.6f}")
            self.logger.info(f"   ⬇️ Средний спад: {debug_info.get('avg_loss', 0):.6f}")
            self.logger.info(f"   🌊 Макс. изменение: {debug_info.get('max_change', 0):.6f}")

            # Вычисляем RSI вручную для проверки
            avg_gain = debug_info.get('avg_gain', 0)
            avg_loss = debug_info.get('avg_loss', 0)

            if avg_loss > 0:
                rs = avg_gain / avg_loss
                calculated_rsi = 100 - (100 / (1 + rs))
                self.logger.info(f"   💹 Расчетный RSI: {calculated_rsi:.1f}")
            else:
                self.logger.info(f"   💹 RSI: {100 if avg_gain > 0 else 50}")