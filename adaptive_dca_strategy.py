# adaptive_dca_strategy_updated.py - DCA с ультра-быстрым детектором дна
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import logging
import time


@dataclass
class BottomPurchase:
    """Покупка на дне"""
    price: float
    quantity: float
    timestamp: datetime
    bottom_confirmed_at: datetime


class AdaptiveDCAStrategy:
    """🎯 Адаптивная DCA с ультра-быстрым определением дна (30 секунд!)"""

    def __init__(self, config, api_client, risk_manager, position_manager):
        self.config = config
        self.api = api_client
        self.risk_manager = risk_manager
        self.position_manager = position_manager
        self.logger = logging.getLogger(__name__)

        # Настройки стратегии
        self.max_position_percent = 0.56  # Максимум 56% депозита в DOGE
        self.bottom_purchase_size = 0.08  # 8% депозита на каждую покупку на дне
        self.max_purchases = 7  # Максимум 7 покупок (7*8% = 56%)

        # ⚡ УЛЬТРА-БЫСТРЫЕ настройки для определения дна
        self.stabilization_minutes = 0.5  # 30 СЕКУНД! (было 15 минут)
        self.bounce_threshold = 0.0003  # 0.03% микро-отскок (было 0.3%)
        self.max_range_percent = 0.002  # 0.2% диапазон (было 1%)
        self.min_time_between_bottoms = 180  # 3 минуты кулдаун (было 30 мин)

        # 🔧 ДОПОЛНИТЕЛЬНЫЕ фильтры для ультра-быстрого режима
        self.min_drop_for_dca = 0.015  # Минимум 1.5% падения (было 2%)
        self.price_action_weight = 0.8  # 80% веса на price action анализ
        self.volume_confirmation = False  # Пока отключаем проверку объемов
        self.micro_bounce_detection = True  # Включаем детекцию микро-отскоков

        # Активная позиция
        self.first_entry_price: Optional[float] = None
        self.purchases: List[BottomPurchase] = []
        self.total_invested = 0.0
        self.total_quantity = 0.0

        # История цен для определения дна
        self.price_history = []  # [(timestamp, price)]
        self.last_bottom_time = None

        self.logger.info("⚡ УЛЬТРА-БЫСТРАЯ DCA стратегия инициализирована:")
        self.logger.info(f"   ⏰ Стабилизация: {self.stabilization_minutes * 60:.0f} СЕКУНД!")
        self.logger.info(f"   📈 Отскок: {self.bounce_threshold * 100:.3f}%")
        self.logger.info(f"   📏 Диапазон: {self.max_range_percent * 100:.2f}%")
        self.logger.info(f"   🕐 Кулдаун: {self.min_time_between_bottoms // 60} минут")
        self.logger.info(f"   🎯 Максимум покупок: {self.max_purchases}")

    def should_buy_initial(self, market_data: Dict) -> Tuple[bool, float, float]:
        """Первая покупка - используем существующую логику"""
        if self.first_entry_price is not None:
            return False, 0.0, 0.0  # Уже есть позиция

        current_price = market_data.get('current_price', 0.0)
        balance = market_data.get('balance', 0.0)

        if self._is_good_initial_entry(current_price, balance):
            quantity = balance * self.bottom_purchase_size / current_price
            buy_price = current_price * 0.999

            self.logger.info(f"🎯 ПЕРВОНАЧАЛЬНАЯ ПОКУПКА:")
            self.logger.info(f"   Цена: {buy_price:.8f}")
            self.logger.info(f"   Количество: {quantity:.4f}")

            return True, quantity, buy_price

        return False, 0.0, 0.0

    def should_buy_on_bottom(self, market_data: Dict) -> Tuple[bool, float, float]:
        """⚡ УЛЬТРА-БЫСТРАЯ покупка на дне (30 секунд определения!)"""
        if self.first_entry_price is None:
            return False, 0.0, 0.0  # Нет первой позиции

        current_price = market_data.get('current_price', 0.0)
        balance = market_data.get('balance', 0.0)

        # Проверяем ограничения
        if not self._can_make_bottom_purchase(balance):
            return False, 0.0, 0.0

        # ⚡ УЛЬТРА-БЫСТРОЕ определение дна
        if not self._is_confirmed_bottom_ultra_fast(current_price):
            return False, 0.0, 0.0

        # Дно подтверждено - покупаем!
        quantity = balance * self.bottom_purchase_size / current_price
        buy_price = current_price * 0.9995  # Минимальная скидка для быстрого исполнения

        drop_from_first = (self.first_entry_price - current_price) / self.first_entry_price * 100

        self.logger.info(f"⚡ УЛЬТРА-БЫСТРАЯ ПОКУПКА НА ДНЕ #{len(self.purchases) + 1}:")
        self.logger.info(f"   Первая покупка: {self.first_entry_price:.8f}")
        self.logger.info(f"   Цена дна: {buy_price:.8f}")
        self.logger.info(f"   Падение от первой: {drop_from_first:.1f}%")
        self.logger.info(f"   Количество: {quantity:.4f}")
        self.logger.info(f"   Время определения: {self.stabilization_minutes * 60:.0f} секунд")

        return True, quantity, buy_price

    def _is_confirmed_bottom_ultra_fast(self, current_price: float) -> bool:
        """⚡ УЛЬТРА-БЫСТРОЕ подтверждение дна за 30 секунд"""

        # Обновляем историю цен
        current_time = time.time()
        self.price_history.append((current_time, current_price))

        # Оставляем только последние 2 часа для экономии памяти
        two_hours_ago = current_time - 7200
        self.price_history = [(t, p) for t, p in self.price_history if t > two_hours_ago]

        # ⚡ Нужно минимум 30 секунд данных
        stabilization_seconds = int(self.stabilization_minutes * 60)

        if len(self.price_history) < stabilization_seconds:
            self.logger.debug(f"⏳ Накапливаем данные: {len(self.price_history)}/{stabilization_seconds} секунд")
            return False

        # Анализируем период стабилизации (последние 30 секунд!)
        analysis_period = self.price_history[-stabilization_seconds:]
        analysis_prices = [p[1] for p in analysis_period]

        if len(analysis_prices) < stabilization_seconds:
            return False

        return self._ultra_fast_bottom_analysis(current_price, analysis_prices)

    def _ultra_fast_bottom_analysis(self, current_price: float, prices: List[float]) -> bool:
        """🎯 Ультра-быстрый анализ дна за 30 секунд с price action"""

        # 1. 📏 СТРОГИЙ диапазон стабилизации
        min_price = min(prices)
        max_price = max(prices)
        price_range = (max_price - min_price) / min_price

        if price_range > self.max_range_percent:
            self.logger.debug(f"🔧 Диапазон {price_range * 100:.3f}% > {self.max_range_percent * 100:.2f}%")
            return False

        # 2. 📈 МИКРО-ОТСКОК (даже 0.03% достаточно!)
        recent_prices = prices[-5:] if len(prices) >= 5 else prices[-len(prices) // 2:]
        if len(recent_prices) == 0:
            return False

        recent_avg = sum(recent_prices) / len(recent_prices)
        micro_bounce = (recent_avg - min_price) / min_price

        if micro_bounce < self.bounce_threshold:
            self.logger.debug(f"🔧 Отскок {micro_bounce * 100:.4f}% < {self.bounce_threshold * 100:.3f}%")
            return False

        # 3. 🎯 PRICE ACTION анализ (ключевой фильтр!)
        price_action_score = self._analyze_price_action_ultra_fast(prices, min_price)

        if price_action_score < 0.6:  # 60% confidence минимум
            self.logger.debug(f"🔧 Price action слабый: {price_action_score:.2f}")
            return False

        # 4. 🚀 ПРОВЕРКА НА ПРОДОЛЖАЮЩЕЕСЯ ПАДЕНИЕ
        if len(prices) >= 4:
            # Последняя четверть должна быть стабильнее первой четверти
            first_quarter = prices[:len(prices) // 4]
            last_quarter = prices[-len(prices) // 4:]

            if len(first_quarter) > 0 and len(last_quarter) > 0:
                first_avg = sum(first_quarter) / len(first_quarter)
                last_avg = sum(last_quarter) / len(last_quarter)

                # Если в последней четверти цена продолжает падать - НЕ покупаем
                if last_avg < first_avg * 0.9985:  # Падение >0.15% внутри стабилизации
                    self.logger.debug(f"🔧 Продолжающееся падение внутри периода")
                    return False

        # 5. 🔍 ДОПОЛНИТЕЛЬНЫЙ фильтр: значительное падение от недавнего максимума
        if len(self.price_history) >= 60:  # Есть данные за минуту экстра
            hour_prices = [p[1] for p in self.price_history[-60:]]  # Последняя минута экстра
            if hour_prices:
                recent_high = max(hour_prices)
                total_drop = (recent_high - min_price) / recent_high

                if total_drop < self.min_drop_for_dca:
                    self.logger.debug(f"🔧 Падение {total_drop * 100:.1f}% < {self.min_drop_for_dca * 100:.1f}%")
                    return False

        # ✅ ВСЕ УСЛОВИЯ ВЫПОЛНЕНЫ!
        confidence = price_action_score * 100

        self.logger.info(f"⚡ УЛЬТРА-БЫСТРОЕ ДНО ПОДТВЕРЖДЕНО!")
        self.logger.info(f"   ⏰ Время анализа: {len(prices)} секунд")
        self.logger.info(f"   📏 Диапазон: {price_range * 100:.3f}%")
        self.logger.info(f"   📈 Микро-отскок: {micro_bounce * 100:.4f}%")
        self.logger.info(f"   🎯 Price action: {confidence:.0f}%")
        self.logger.info(f"   💎 Цена дна: {min_price:.8f}")

        return True

    def _analyze_price_action_ultra_fast(self, prices: List[float], min_price: float) -> float:
        """🎯 Ультра-быстрый анализ price action за 30 секунд"""

        if len(prices) < 4:
            return 0.3  # Недостаточно данных, низкий скор

        score = 0.0

        # 1. Проверяем формирование "V" паттерна
        min_index = prices.index(min_price)

        # Минимум должен быть не в самом конце (есть отскок)
        position_ratio = min_index / len(prices)
        if 0.2 <= position_ratio <= 0.8:  # Минимум в "правильном" месте
            score += 0.3  # +30% за правильное расположение минимума

        # 2. Проверяем что после минимума цена растет
        if min_index < len(prices) - 2:
            prices_after_min = prices[min_index + 1:]
            avg_after = sum(prices_after_min) / len(prices_after_min)

            if avg_after > min_price * 1.0001:  # Хотя бы 0.01% роста после минимума
                score += 0.3  # +30% за рост после минимума

        # 3. Проверяем стабилизацию (отсутствие новых минимумов)
        last_portion = prices[-len(prices) // 3:] if len(prices) >= 6 else prices[-2:]
        if len(last_portion) > 1:
            last_portion_min = min(last_portion)
            # Новый минимум не более чем на 0.01% ниже
            if last_portion_min >= min_price * 0.9999:
                score += 0.2  # +20% за стабилизацию

        # 4. Проверяем общий тренд до минимума (должен быть нисходящий)
        if len(prices) >= 6:
            first_half = prices[:len(prices) // 2]

            if len(first_half) >= 2:
                first_half_trend = (first_half[-1] - first_half[0]) / first_half[0]
                if first_half_trend < -0.001:  # Нисходящий тренд >0.1%
                    score += 0.2  # +20% за правильный тренд до минимума

        return min(1.0, score)  # Максимум 100%

    def should_sell(self, market_data: Dict[str, Any], position: Dict[str, Any]) -> Tuple[bool, float, float]:
        """💎 Логика продажи (без изменений)"""
        current_price = market_data.get('current_price', 0.0)
        quantity = position.get('quantity', 0.0)

        if not quantity:
            return False, 0.0, 0.0

        # Получаем реальную позицию
        real_position = self.position_manager.get_position(self.config.CURRENCY_1)
        if not real_position:
            return False, 0.0, 0.0

        position_price = real_position.avg_price
        quantity = min(quantity, real_position.quantity)
        potential_profit = (current_price - position_price) / position_price

        self.logger.info(f"💎 Анализ продажи:")
        self.logger.info(f"   Цена покупки: {position_price:.8f}")
        self.logger.info(f"   Текущая цена: {current_price:.8f}")
        self.logger.info(f"   Потенциальная прибыль: {potential_profit * 100:+.2f}%")

        # 🚨 ЭКСТРЕННЫЙ СТОП-ЛОСС
        if potential_profit <= -self.config.STOP_LOSS_PERCENT:
            self.logger.error(f"🚨 СТОП-ЛОСС! Убыток: {potential_profit * 100:.2f}%")
            sell_price = current_price * 0.999
            return True, quantity, sell_price

        # 🚫 НЕ ПРОДАЕМ при недостаточной прибыли
        if potential_profit < self.config.MIN_PROFIT_TO_SELL:
            self.logger.info(
                f"⏸️  Держим позицию: прибыль {potential_profit * 100:.2f}% < порога {self.config.MIN_PROFIT_TO_SELL * 100:.1f}%")
            return False, 0.0, 0.0

        # 🎯 БЫСТРАЯ продажа при хорошей прибыли БЕЗ технического анализа
        if potential_profit >= 0.015:  # 1.5% и выше - продаем сразу
            self.logger.info(f"💎 БЫСТРАЯ ПРОДАЖА! Хорошая прибыль: {potential_profit * 100:.2f}%")
            sell_price = current_price * 0.9998

            # Валидация прибыльности
            is_profitable, profit_reason = self._validate_trade_profitability('sell', sell_price, quantity,
                                                                              position_price)
            if is_profitable:
                return True, quantity, sell_price
            else:
                self.logger.warning(f"🚫 Быстрая продажа отменена: {profit_reason}")

        # 📊 Технический анализ только для средней прибыли
        analysis = self._analyze_market_conditions(current_price)
        if not analysis['ready']:
            if potential_profit >= 0.013:
                self.logger.info(f"💎 ПРОДАЖА БЕЗ ТЕХНИЧЕСКОГО АНАЛИЗА: {potential_profit * 100:.2f}%")
                sell_price = current_price * 0.9998
                return True, quantity, sell_price
            return False, 0.0, 0.0

        # 🎯 ОСЛАБЛЕННЫЕ условия продажи для средней прибыли
        sell_conditions = {
            'sufficient_profit': potential_profit >= self.config.MIN_PROFIT_TO_SELL,
            'not_crashing': analysis['rsi'] > 25,
            'reasonable_bb_position': analysis['bb_position'] > 0.3,
            'not_deep_red': current_price > analysis['ema'] * 0.99,
        }

        # Логируем условия
        met_conditions = []
        for condition_name, is_met in sell_conditions.items():
            status = "✅" if is_met else "❌"
            self.logger.info(f"   {status} {condition_name}")
            if is_met:
                met_conditions.append(condition_name)

        conditions_met = len(met_conditions)

        # 🎯 Требуем только 2 из 4 условий
        if conditions_met >= 2:
            spread = self.config.MIN_SPREAD
            sell_price = current_price * (1 + spread)

            # Валидация прибыльности
            is_profitable, profit_reason = self._validate_trade_profitability('sell', sell_price, quantity,
                                                                              position_price)
            if is_profitable:
                final_profit = (sell_price - position_price) / position_price
                self.logger.info(f"🎯 СИГНАЛ ПРОДАЖИ!")
                self.logger.info(f"   Условий выполнено: {conditions_met}/4: {', '.join(met_conditions)}")
                self.logger.info(f"   Финальная прибыль: {final_profit * 100:+.2f}%")
                return True, quantity, sell_price
            else:
                self.logger.warning(f"🚫 Продажа отменена: {profit_reason}")

        # Если условия не выполнены
        self.logger.info(f"⏸️  Технические условия не выполнены: {conditions_met}/4")
        self.logger.info(f"💎 Держим позицию, ждем лучших условий или роста до 1.5%")

        return False, 0.0, 0.0

    def _can_make_bottom_purchase(self, balance: float) -> bool:
        """Проверка возможности покупки на дне"""
        # Проверяем лимит покупок
        if len(self.purchases) >= self.max_purchases - 1:
            self.logger.info(f"⚠️ Достигнут лимит покупок на дне: {self.max_purchases}")
            return False

        # Проверяем лимит использования депозита
        total_position_value = self.total_invested + (balance * self.bottom_purchase_size)
        total_balance = balance + self.total_invested

        if total_position_value / total_balance > self.max_position_percent:
            self.logger.info(f"⚠️ Достигнут лимит позиции: {self.max_position_percent * 100}%")
            return False

        # ⚡ УСКОРЕННАЯ проверка времени между покупками (3 минуты вместо 30)
        if self.last_bottom_time:
            time_since_last = (datetime.now() - self.last_bottom_time).total_seconds()
            if time_since_last < self.min_time_between_bottoms:
                remaining = (self.min_time_between_bottoms - time_since_last) / 60
                self.logger.info(f"⏰ Кулдаун между покупками: {remaining:.0f} мин")
                return False

        return True

    def _is_good_initial_entry(self, current_price: float, balance: float) -> bool:
        """🐕 DOGE-оптимизированный первый вход"""
        self.price_history.append((time.time(), current_price))

        if len(self.price_history) < 5:  # Еще быстрее: 5 точек вместо 10
            return False

        # 🚀 Еще более агрессивные условия для DOGE
        recent_prices = [p[1] for p in self.price_history[-15:]]  # Последние 15 секунд
        if len(recent_prices) >= 10:
            recent_high = max(recent_prices)
            current_drop = (recent_high - current_price) / recent_high

            # 🎯 Покупаем при падении 1% за 15 секунд (было 1.5% за 30 минут)
            if current_drop >= 0.01:
                self.logger.info(f"🎯 ПЕРВЫЙ ВХОД: падение {current_drop * 100:.1f}% за 15 сек")
                return True

        # 🔧 Альтернативное условие: резкое падение за 5 секунд
        if len(self.price_history) >= 5:
            five_sec_ago_price = self.price_history[-5][1]
            quick_drop = (five_sec_ago_price - current_price) / five_sec_ago_price

            if quick_drop >= 0.005:  # 0.5% за 5 секунд
                self.logger.info(f"🚀 МГНОВЕННЫЙ ВХОД: падение {quick_drop * 100:.1f}% за 5 сек")
                return True

        return False

    def _analyze_market_conditions(self, current_price: float) -> Dict[str, Any]:
        """📊 Облегченный анализ рынка для быстрой DCA"""
        if len(self.price_history) < 10:  # Снижено с 15
            return {
                'ready': False,
                'reason': f'Накапливаем данные: {len(self.price_history)}/10',
                'data_points': len(self.price_history)
            }

        recent_prices = [p[1] for p in self.price_history[-20:]]  # Последние 20 точек

        # Упрощенные индикаторы
        sma = sum(recent_prices) / len(recent_prices)
        ema = recent_prices[-1]  # Упрощаем EMA до последней цены

        # Упрощенный RSI
        changes = []
        for i in range(1, len(recent_prices)):
            changes.append(recent_prices[i] - recent_prices[i - 1])

        if len(changes) > 0:
            gains = [c for c in changes if c > 0]
            losses = [-c for c in changes if c < 0]
            avg_gain = sum(gains) / len(gains) if gains else 0.001
            avg_loss = sum(losses) / len(losses) if losses else 0.001
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        else:
            rsi = 50

        # Упрощенные Bollinger Bands
        std_dev = (sum([(p - sma) ** 2 for p in recent_prices]) / len(recent_prices)) ** 0.5
        bb_upper = sma + (std_dev * 2)
        bb_lower = sma - (std_dev * 2)
        bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5

        return {
            'ready': True,
            'current_price': current_price,
            'sma_short': sma,
            'ema': ema,
            'rsi': rsi,
            'bb_upper': bb_upper,
            'bb_middle': sma,
            'bb_lower': bb_lower,
            'bb_position': bb_position,
            'data_points': len(recent_prices)
        }

    def _validate_trade_profitability(self, order_type: str, price: float, quantity: float,
                                      position_price: float = None) -> Tuple[bool, str]:
        """💰 Быстрая проверка прибыльности сделки"""
        commission_cost = 0.006  # 0.6% туда и обратно

        if order_type == 'buy':
            return True, "Покупка разрешена"

        elif order_type == 'sell' and position_price:
            profit_percent = (price - position_price) / position_price
            profit_after_commission = profit_percent - commission_cost

            if profit_percent < self.config.MIN_PROFIT_TO_SELL:
                return False, f"Недостаточная прибыль: {profit_percent * 100:.2f}% < {self.config.MIN_PROFIT_TO_SELL * 100:.1f}%"

            if profit_after_commission < 0:
                return False, f"Убыток после комиссий: {profit_after_commission * 100:.2f}%"

            return True, f"Прибыльная продажа: {profit_after_commission * 100:.2f}%"

        return True, "OK"

    def on_purchase_executed(self, price: float, quantity: float, is_initial: bool = False):
        """Обработка исполненной покупки"""
        if is_initial:
            self.first_entry_price = price
            self.total_quantity = quantity
            self.total_invested = price * quantity

            self.logger.info(f"🎯 Зафиксирована первая покупка:")
            self.logger.info(f"   Цена: {price:.8f}")
            self.logger.info(f"   Количество: {quantity:.4f}")
            self.logger.info(f"   Цель продажи: {price * 1.007:.8f}")
        else:
            # Покупка на дне
            purchase = BottomPurchase(
                price=price,
                quantity=quantity,
                timestamp=datetime.now(),
                bottom_confirmed_at=datetime.now()
            )
            self.purchases.append(purchase)

            self.total_quantity += quantity
            self.total_invested += price * quantity
            self.last_bottom_time = datetime.now()

            avg_price = self.total_invested / self.total_quantity

            self.logger.info(f"⚡ УЛЬТРА-БЫСТРАЯ покупка на дне зафиксирована:")
            self.logger.info(f"   Покупка #{len(self.purchases)}")
            self.logger.info(f"   Цена: {price:.8f}")
            self.logger.info(f"   Количество: {quantity:.4f}")
            self.logger.info(f"   Общее количество: {self.total_quantity:.4f}")
            self.logger.info(f"   Новая средняя цена: {avg_price:.8f}")

    def on_position_closed(self):
        """Обработка закрытия позиции"""
        total_purchases = len(self.purchases) + 1

        self.logger.info(f"🎯 ПОЗИЦИЯ ЗАКРЫТА:")
        self.logger.info(f"   Всего покупок: {total_purchases}")
        if self.purchases:
            duration = datetime.now() - self.purchases[0].timestamp
            self.logger.info(f"   Период: {duration.total_seconds() / 60:.0f} минут")

        # Сбрасываем состояние
        self.first_entry_price = None
        self.purchases = []
        self.total_invested = 0.0
        self.total_quantity = 0.0
        self.last_bottom_time = None

    def get_status(self) -> Dict:
        """Получение текущего статуса стратегии"""
        if self.first_entry_price is None:
            return {'active': False}

        avg_price = self.total_invested / self.total_quantity if self.total_quantity > 0 else 0
        target_price = self.first_entry_price * 1.007

        return {
            'active': True,
            'first_entry_price': self.first_entry_price,
            'target_sell_price': target_price,
            'total_purchases': len(self.purchases) + 1,
            'total_quantity': self.total_quantity,
            'total_invested': self.total_invested,
            'avg_price': avg_price,
            'remaining_purchases': self.max_purchases - len(self.purchases) - 1,
            'can_buy_more': len(self.purchases) < self.max_purchases - 1,
            'ultra_fast_mode': True,
            'stabilization_seconds': int(self.stabilization_minutes * 60),
            'last_bottom_time': self.last_bottom_time.isoformat() if self.last_bottom_time else None
        }

    def update_price_history(self, current_price: float):
        """🔄 Обновление истории цен"""
        current_time = time.time()
        self.price_history.append((current_time, current_price))

        # Оставляем только последние 30 минут для экономии памяти
        thirty_min_ago = current_time - 1800
        self.price_history = [(t, p) for t, p in self.price_history if t > thirty_min_ago]

    def get_debug_info(self) -> Dict:
        """🔍 НОВЫЙ МЕТОД: Отладочная информация"""
        if len(self.price_history) < 5:
            return {'status': 'insufficient_data', 'points': len(self.price_history)}

        recent_prices = [p[1] for p in self.price_history[-30:]]  # Последние 30 секунд

        return {
            'price_history_points': len(self.price_history),
            'recent_price_range': {
                'min': min(recent_prices) if recent_prices else 0,
                'max': max(recent_prices) if recent_prices else 0,
                'current': recent_prices[-1] if recent_prices else 0
            },
            'settings': {
                'stabilization_seconds': int(self.stabilization_minutes * 60),
                'bounce_threshold_percent': self.bounce_threshold * 100,
                'max_range_percent': self.max_range_percent * 100,
                'cooldown_minutes': self.min_time_between_bottoms / 60
            },
            'last_analysis_time': time.time(),
            'time_since_last_bottom': (
                (datetime.now() - self.last_bottom_time).total_seconds() / 60
                if self.last_bottom_time else None
            )
        }

    def enable_test_mode(self):
        """🧪 Тестовый режим с еще более быстрыми параметрами"""
        self.stabilization_minutes = 0.25  # 15 секунд для тестов!
        self.bounce_threshold = 0.0001  # 0.01% отскок
        self.max_range_percent = 0.001  # 0.1% диапазон
        self.min_time_between_bottoms = 60  # 1 минута кулдаун

        self.logger.warning("🧪 ТЕСТОВЫЙ РЕЖИМ УЛЬТРА-БЫСТРОЙ DCA АКТИВЕН!")
        self.logger.warning("   ⚡ Определение дна за 15 СЕКУНД!")
        self.logger.warning("   🎯 Максимально агрессивные параметры")

    def force_bottom_detection_now(self) -> bool:
        """🔧 НОВЫЙ МЕТОД: Принудительная проверка дна (для отладки)"""
        if len(self.price_history) == 0:
            return False

        current_price = self.price_history[-1][1] if self.price_history else 0
        result = self._is_confirmed_bottom_ultra_fast(current_price)

        self.logger.info(f"🔧 ПРИНУДИТЕЛЬНАЯ ПРОВЕРКА ДНА: {'✅ ПОДТВЕРЖДЕНО' if result else '❌ НЕ ПОДТВЕРЖДЕНО'}")
        return result
