# pyramid_strategy.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
import logging
import time
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime


class SmartPyramidStrategy:
    """🏗️ ИСПРАВЛЕННАЯ пирамидальная стратегия с защитой от убытков"""

    def __init__(self, config, position_manager):
        self.config = config
        self.position_manager = position_manager
        self.logger = logging.getLogger(__name__)

        # 🎯 ИСПРАВЛЕННЫЕ настройки пирамиды (более консервативные)
        self.pyramid_levels = [
            {
                'name': 'Быстрая прибыль',
                'price_multiplier': 1.015,    # +1.5% вместо 0.8% (ИСПРАВЛЕНО)
                'sell_percent': 25,
                'min_profit_eur': 0.15
            },
            {
                'name': 'Средняя прибыль',
                'price_multiplier': 1.03,     # +3% вместо 2.0% (ИСПРАВЛЕНО)
                'sell_percent': 35,
                'min_profit_eur': 0.25
            },
            {
                'name': 'Хорошая прибыль',
                'price_multiplier': 1.05,     # +5% вместо 4.0% (ИСПРАВЛЕНО)
                'sell_percent': 25,
                'min_profit_eur': 0.35
            },
            {
                'name': 'Отличная прибыль',
                'price_multiplier': 1.08,     # +8% вместо 7% (ИСПРАВЛЕНО)
                'sell_percent': 15,
                'min_profit_eur': 0.60
            }
        ]

        # 🛡️ НОВЫЕ защитные настройки
        self.min_profit_threshold = 0.012     # 1.2% минимальная прибыль ВСЕГДА
        self.commission_buffer = 0.008        # 0.8% буфер на комиссии
        self.enable_loss_protection = True    # Включить защиту от убытков

        # Остальные настройки
        self.min_sell_quantity = 5.0
        self.max_sell_per_cycle = 0.4
        self.cooldown_between_sells = 300
        self.last_sell_time = 0

        self.logger.info("🏗️ ИСПРАВЛЕННАЯ пирамидальная стратегия инициализирована")
        self.logger.info(f"   🛡️ Минимальная прибыль: {self.min_profit_threshold * 100:.1f}%")
        self.logger.info(f"   🔒 Защита от убытков: {'ВКЛ' if self.enable_loss_protection else 'ВЫКЛ'}")

    def analyze_sell_opportunity(self, current_price: float, position_data: Dict[str, Any]) -> Dict[str, Any]:
        """🔍 ИСПРАВЛЕННЫЙ анализ возможности продажи"""

        try:
            # 🔧 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем актуальные данные позиции
            accurate_data = self.position_manager.get_accurate_position_data(self.config.CURRENCY_1)

            if not accurate_data or accurate_data['quantity'] <= 0:
                return {'should_sell': False, 'reason': 'Нет актуальных данных позиции'}

            total_quantity = accurate_data['quantity']
            avg_price = accurate_data['avg_price']

            self.logger.info(f"🏗️ ИСПРАВЛЕННЫЙ анализ пирамиды:")
            self.logger.info(f"   📊 Актуальные данные: {total_quantity:.6f} по {avg_price:.8f}")
            self.logger.info(f"   💰 Текущая цена: {current_price:.8f}")

            # 🛡️ КРИТИЧЕСКАЯ ПРОВЕРКА: Общая прибыльность позиции
            overall_profit = (current_price - avg_price) / avg_price
            min_required_profit = self.min_profit_threshold + self.commission_buffer

            if self.enable_loss_protection and overall_profit < min_required_profit:
                self.logger.warning(f"🛡️ ЗАЩИТА ОТ УБЫТКОВ АКТИВИРОВАНА!")
                self.logger.warning(f"   Текущая прибыль: {overall_profit * 100:+.2f}%")
                self.logger.warning(f"   Минимум требуется: {min_required_profit * 100:.1f}%")
                self.logger.warning(f"   ПРОДАЖА ЗАБЛОКИРОВАНА!")

                return {
                    'should_sell': False,
                    'reason': f'Защита от убытков: {overall_profit * 100:+.2f}% < {min_required_profit * 100:.1f}%'
                }

            # Проверяем кулдаун
            if not self._can_sell_now():
                remaining_cooldown = self._get_remaining_cooldown()
                return {
                    'should_sell': False,
                    'reason': f'Кулдаун: {remaining_cooldown:.0f} сек'
                }

            # Анализируем уровни пирамиды с актуальными данными
            best_opportunity = None
            max_profit = 0

            for level in self.pyramid_levels:
                opportunity = self._analyze_pyramid_level_safe(
                    current_price, avg_price, total_quantity, level
                )

                if (opportunity['can_sell'] and
                    opportunity['total_profit'] > max_profit and
                    opportunity['total_profit'] >= level['min_profit_eur']):

                    best_opportunity = opportunity
                    max_profit = opportunity['total_profit']

            if best_opportunity:
                return {
                    'should_sell': True,
                    'strategy': 'safe_pyramid',
                    **best_opportunity
                }

            return {
                'should_sell': False,
                'reason': 'Нет безопасных уровней для продажи'
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка исправленного анализа пирамиды: {e}")
            return {'should_sell': False, 'reason': f'Ошибка анализа: {str(e)}'}

    def _analyze_pyramid_level_safe(self, current_price: float, avg_price: float,
                                   total_quantity: float, level: Dict) -> Dict[str, Any]:
        """🔍 БЕЗОПАСНЫЙ анализ уровня пирамиды"""

        level_name = level['name']
        target_multiplier = level['price_multiplier']
        sell_percentage = level['sell_percent'] / 100

        # Используем актуальную среднюю цену
        required_price = avg_price * target_multiplier

        if current_price < required_price:
            return {
                'can_sell': False,
                'level': level_name,
                'reason': f'Цена {current_price:.8f} < цели {required_price:.8f}'
            }

        # Рассчитываем количество
        sell_quantity = min(
            total_quantity * sell_percentage,
            total_quantity * self.max_sell_per_cycle
        )

        if sell_quantity < self.min_sell_quantity:
            return {
                'can_sell': False,
                'level': level_name,
                'reason': f'Количество {sell_quantity:.2f} < минимума'
            }

        # ПРАВИЛЬНЫЙ расчет прибыли
        total_profit = sell_quantity * (current_price - avg_price)
        profit_percent = (current_price - avg_price) / avg_price * 100

        return {
            'can_sell': True,
            'level': level_name,
            'sell_quantity': sell_quantity,
            'sell_price': current_price * 0.9995,
            'total_profit': total_profit,
            'profit_percent': profit_percent,
            'avg_price_used': avg_price,
            'reason': f'{level_name}: продажа {sell_quantity:.2f} DOGE с прибылью {total_profit:.4f} EUR'
        }

    def execute_pyramid_sell(self, sell_data: Dict[str, Any], api_client) -> bool:
        """🚀 БЕЗОПАСНОЕ исполнение пирамидальной продажи"""

        if not sell_data.get('should_sell'):
            return False

        quantity = sell_data['sell_quantity']
        price = sell_data['sell_price']
        level = sell_data['level']
        avg_price_used = sell_data.get('avg_price_used', 0)

        # 🛡️ ФИНАЛЬНАЯ проверка прибыльности
        if avg_price_used > 0:
            profit_check = (price - avg_price_used) / avg_price_used
            if profit_check < self.min_profit_threshold:
                self.logger.error(f"🚨 ФИНАЛЬНАЯ БЛОКИРОВКА: Недостаточная прибыль {profit_check*100:.2f}%")
                return False

        self.logger.info(f"🏗️ БЕЗОПАСНАЯ ПИРАМИДАЛЬНАЯ ПРОДАЖА: {level}")
        self.logger.info(f"   Количество: {quantity:.6f} DOGE")
        self.logger.info(f"   Цена продажи: {price:.8f} EUR")
        self.logger.info(f"   Цена покупки: {avg_price_used:.8f} EUR")
        self.logger.info(f"   Прибыль: {((price - avg_price_used) / avg_price_used * 100):+.2f}%")

        try:
            pair = f"{self.config.CURRENCY_1}_{self.config.CURRENCY_2}"

            pair_settings = api_client.get_pair_settings()
            precision = int(pair_settings.get(pair, {}).get('price_precision', 8))
            price_rounded = round(price, precision)

            result = api_client.create_order(pair, quantity, price_rounded, 'sell')

            if result.get('result'):
                self.logger.info(f"✅ БЕЗОПАСНАЯ ПИРАМИДАЛЬНАЯ ПРОДАЖА ИСПОЛНЕНА!")
                self.logger.info(f"   Ордер ID: {result.get('order_id', 'N/A')}")
                self.last_sell_time = time.time()
                return True
            else:
                self.logger.error(f"❌ Ошибка создания ордера: {result}")

        except Exception as e:
            self.logger.error(f"❌ Исключение при создании ордера: {e}")

        return False

    def _can_sell_now(self) -> bool:
        """⏰ Проверка кулдауна"""
        current_time = time.time()
        return (current_time - self.last_sell_time) >= self.cooldown_between_sells

    def _get_remaining_cooldown(self) -> float:
        """⏰ Оставшееся время кулдауна"""
        current_time = time.time()
        elapsed = current_time - self.last_sell_time
        return max(0, self.cooldown_between_sells - elapsed)

    def get_pyramid_status(self, current_price: float, position_data: Dict[str, Any]) -> Dict[str, Any]:
        """📊 Статус пирамидальной стратегии"""
        return {
            'strategy': 'safe_pyramid',
            'loss_protection': self.enable_loss_protection,
            'min_profit_threshold': f"{self.min_profit_threshold * 100:.1f}%",
            'current_price': current_price,
            'cooldown_remaining': self._get_remaining_cooldown()
        }
