from typing import Tuple
import logging
from config import TradingConfig


class TradeValidator:
    """✅ Единая валидация всех торговых операций"""

    def __init__(self, config: TradingConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.commission_rate = config.AUTO_COMMISSION_RATE

    def validate_profitability(self, order_type: str, price: float,
                             quantity: float, position_price: float = None) -> Tuple[bool, str]:
        """💰 Проверка прибыльности сделки"""

        total_commission = self.commission_rate * 2  # Туда и обратно

        if order_type == 'buy':
            # Для покупки: проверяем что сможем продать с прибылью
            min_sell_price = price * (1 + self.config.MIN_PROFIT_TO_SELL + total_commission)

            self.logger.debug(f"💡 Анализ покупки:")
            self.logger.debug(f"   Цена покупки: {price:.8f}")
            self.logger.debug(f"   Мин. цена продажи: {min_sell_price:.8f}")
            self.logger.debug(f"   Требуемая прибыль: {self.config.MIN_PROFIT_TO_SELL * 100:.1f}%")

            return True, "Покупка разрешена"

        elif order_type == 'sell' and position_price:
            # Для продажи: обязательная проверка прибыли
            profit_percent = (price - position_price) / position_price
            profit_after_commission = profit_percent - total_commission

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

    def validate_position_size(self, position_size: float, balance: float) -> Tuple[bool, str]:
        """📊 Проверка размера позиции"""
        max_position_value = balance * self.config.MAX_POSITION_SIZE

        if position_size > max_position_value:
            return False, f"Размер позиции {position_size:.2f} > лимита {max_position_value:.2f}"

        return True, "Размер позиции в норме"

    def validate_order_limits(self, pair: str, quantity: float, price: float,
                            pair_settings: dict) -> Tuple[bool, str]:
        """📏 Проверка лимитов ордера"""
        pair_info = pair_settings.get(pair, {})

        # Минимальное количество
        min_quantity = float(pair_info.get('min_quantity', 0))
        if quantity < min_quantity:
            return False, f"Количество {quantity:.6f} < минимума {min_quantity:.6f}"

        # Минимальная сумма
        min_amount = float(pair_info.get('min_amount', 0))
        order_amount = quantity * price
        if order_amount < min_amount:
            return False, f"Сумма ордера {order_amount:.4f} < минимума {min_amount:.4f}"

        return True, "Лимиты ордера соблюдены"
