# loss_recovery_manager.py - Система восстановления убыточных позиций
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional
from config import TradingConfig


class LossRecoveryManager:
    """🩹 Менеджер восстановления убыточных позиций"""

    def __init__(self, config: TradingConfig, api_client, position_manager):
        self.config = config
        self.api = api_client
        self.position_manager = position_manager
        self.logger = logging.getLogger(__name__)

        # 🎯 Настройки восстановления
        self.dca_loss_threshold = 0.02      # Докупка при убытке >2%
        self.dca_max_attempts = 3           # Максимум 3 докупки
        self.emergency_stop_loss = 0.08     # Экстренный стоп при -8%
        self.time_based_stop_hours = 6      # Стоп по времени через 6 часов
        self.trailing_activation_in_loss = True  # Активируем trailing даже в убытке

        # Состояние
        self.dca_attempts = 0
        self.position_start_time = None
        self.last_dca_time = None
        self.min_time_between_dca = 1800    # 30 минут между докупками

        self.logger.info("🩹 Система восстановления убыточных позиций активирована")
        self.logger.info(f"   DCA при убытке: >{self.dca_loss_threshold*100:.0f}%")
        self.logger.info(f"   Экстренный стоп: {self.emergency_stop_loss*100:.0f}%")
        self.logger.info(f"   Временной стоп: {self.time_based_stop_hours} часов")

    def analyze_loss_situation(self, current_price: float, position_data: Dict[str, Any]) -> Dict[str, Any]:
        """📊 Анализ убыточной ситуации и определение действий"""

        if not position_data or position_data.get('quantity', 0) == 0:
            return {'action': 'none', 'reason': 'Нет позиции'}

        avg_price = position_data.get('avg_price', 0)
        quantity = position_data.get('quantity', 0)

        if avg_price == 0:
            return {'action': 'none', 'reason': 'Некорректная средняя цена'}

        # Рассчитываем убыток
        loss_percent = (avg_price - current_price) / avg_price
        loss_amount = (avg_price - current_price) * quantity

        # Инициализируем время позиции если нужно
        if loss_percent > 0.005 and not self.position_start_time:  # >0.5% убыток
            self.position_start_time = datetime.now()

        analysis = {
            'current_price': current_price,
            'avg_price': avg_price,
            'quantity': quantity,
            'loss_percent': loss_percent,
            'loss_amount': loss_amount,
            'dca_attempts': self.dca_attempts,
            'time_in_position': self._get_time_in_position(),
            'is_profitable': loss_percent <= 0
        }

        # Логируем текущее состояние
        if loss_percent > 0.01:  # Логируем только значимые убытки
            self.logger.info(f"📊 Анализ убыточной позиции:")
            self.logger.info(f"   Убыток: {loss_percent*100:.2f}%")
            self.logger.info(f"   Время в позиции: {analysis['time_in_position']:.1f} часов")
            self.logger.info(f"   DCA попыток: {self.dca_attempts}/{self.dca_max_attempts}")

        # Определяем рекомендуемое действие
        action_result = self._determine_recovery_action(analysis)
        analysis.update(action_result)

        return analysis

    def _determine_recovery_action(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """🎯 Определение действия для восстановления"""

        loss_percent = analysis['loss_percent']
        current_price = analysis['current_price']
        time_in_position = analysis['time_in_position']

        # Если прибыльная позиция - не вмешиваемся
        if loss_percent <= 0:
            return {
                'action': 'none',
                'reason': f'Позиция прибыльная: {abs(loss_percent)*100:+.2f}%',
                'urgency': 'none'
            }

        # 🚨 КРИТИЧЕСКИЙ СТОП-ЛОСС
        if loss_percent >= self.emergency_stop_loss:
            return {
                'action': 'emergency_stop',
                'reason': f'Критический убыток {loss_percent*100:.1f}% >= {self.emergency_stop_loss*100:.0f}%',
                'urgency': 'critical',
                'sell_price': current_price * 0.995,  # Агрессивная продажа
                'quantity': analysis['quantity']
            }

        # ⏰ ВРЕМЕННОЙ СТОП
        if (time_in_position > self.time_based_stop_hours and
            loss_percent > 0.04):  # Убыток >4% держится >6 часов
            return {
                'action': 'time_stop',
                'reason': f'Убыток {loss_percent*100:.1f}% держится {time_in_position:.1f} часов',
                'urgency': 'high',
                'sell_price': current_price * 0.998,
                'quantity': analysis['quantity']
            }

        # 🩹 DCA ДОКУПКА
        if (loss_percent >= self.dca_loss_threshold and
            self.dca_attempts < self.dca_max_attempts and
            self._can_make_dca()):

            # Размер докупки зависит от размера убытка
            if loss_percent > 0.05:      # >5% убыток
                dca_size_percent = 0.15   # 15% депозита
            elif loss_percent > 0.03:    # >3% убыток
                dca_size_percent = 0.12   # 12% депозита
            else:                        # 2-3% убыток
                dca_size_percent = 0.08   # 8% депозита

            return {
                'action': 'dca_buy',
                'reason': f'DCA докупка #{self.dca_attempts + 1} при убытке {loss_percent*100:.1f}%',
                'urgency': 'medium',
                'buy_size_percent': dca_size_percent,
                'buy_price': current_price * 0.9995  # Небольшая скидка
            }

        # 🔄 АКТИВАЦИЯ TRAILING В УБЫТКЕ (новая логика)
        if (loss_percent > 0.005 and loss_percent < 0.03 and
            self.trailing_activation_in_loss):
            return {
                'action': 'activate_trailing_in_loss',
                'reason': f'Активируем trailing stop в убытке {loss_percent*100:.1f}%',
                'urgency': 'low',
                'trailing_distance': 0.01  # 1% trailing в убытке
            }

        # 💎 HODL - держим позицию
        return {
            'action': 'hold',
            'reason': f'Держим позицию, убыток {loss_percent*100:.1f}% в пределах нормы',
            'urgency': 'low'
        }

    def _can_make_dca(self) -> bool:
        """✅ Проверка возможности DCA докупки"""

        # Проверяем временной интервал
        if self.last_dca_time:
            time_since_dca = (datetime.now() - self.last_dca_time).total_seconds()
            if time_since_dca < self.min_time_between_dca:
                remaining_minutes = (self.min_time_between_dca - time_since_dca) / 60
                self.logger.info(f"⏰ DCA кулдаун: {remaining_minutes:.0f} минут до следующей докупки")
                return False

        # Проверяем лимит попыток
        if self.dca_attempts >= self.dca_max_attempts:
            self.logger.info(f"🚫 Достигнут лимит DCA: {self.dca_attempts}/{self.dca_max_attempts}")
            return False

        return True

    def _get_time_in_position(self) -> float:
        """⏰ Время в позиции (часы)"""
        if not self.position_start_time:
            return 0

        return (datetime.now() - self.position_start_time).total_seconds() / 3600

    def execute_recovery_action(self, action_data: Dict[str, Any], balance: float) -> bool:
        """🚀 Исполнение действия восстановления"""

        action = action_data['action']

        try:
            if action == 'emergency_stop':
                return self._execute_emergency_stop(action_data)

            elif action == 'time_stop':
                return self._execute_time_stop(action_data)

            elif action == 'dca_buy':
                return self._execute_dca_buy(action_data, balance)

            elif action == 'activate_trailing_in_loss':
                self.logger.info(f"🔄 {action_data['reason']}")
                return True  # Trailing активируется в основном боте

            elif action == 'hold':
                self.logger.info(f"💎 {action_data['reason']}")
                return True

            elif action == 'none':
                return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка исполнения {action}: {e}")
            return False

        return False

    def _execute_emergency_stop(self, action_data: Dict[str, Any]) -> bool:
        """🚨 Исполнение экстренного стоп-лосса"""

        self.logger.error(f"🚨 ЭКСТРЕННЫЙ СТОП-ЛОСС!")
        self.logger.error(f"   Причина: {action_data['reason']}")

        sell_price = action_data['sell_price']
        quantity = action_data['quantity']

        try:
            pair = f"{self.config.CURRENCY_1}_{self.config.CURRENCY_2}"
            precision = 8  # Стандартная точность для цены
            price_rounded = round(sell_price, precision)

            result = self.api.create_order(pair, quantity, price_rounded, 'sell')

            if result.get('result'):
                self.logger.error(f"✅ ЭКСТРЕННАЯ ПРОДАЖА ИСПОЛНЕНА!")
                self.logger.error(f"   Количество: {quantity:.6f}")
                self.logger.error(f"   Цена: {price_rounded:.8f}")
                self.logger.error(f"   Ордер ID: {result.get('order_id', 'N/A')}")

                # Сбрасываем состояние
                self._reset_recovery_state()
                return True
            else:
                self.logger.error(f"❌ Ошибка экстренной продажи: {result}")
        except Exception as e:
            self.logger.error(f"❌ Исключение при экстренной продаже: {e}")

        return False

    def _execute_time_stop(self, action_data: Dict[str, Any]) -> bool:
        """⏰ Исполнение временного стоп-лосса"""

        self.logger.warning(f"⏰ ВРЕМЕННОЙ СТОП-ЛОСС!")
        self.logger.warning(f"   Причина: {action_data['reason']}")

        sell_price = action_data['sell_price']
        quantity = action_data['quantity']

        try:
            pair = f"{self.config.CURRENCY_1}_{self.config.CURRENCY_2}"
            precision = 8
            price_rounded = round(sell_price, precision)

            result = self.api.create_order(pair, quantity, price_rounded, 'sell')

            if result.get('result'):
                self.logger.warning(f"✅ ВРЕМЕННОЙ СТОП ИСПОЛНЕН!")
                self.logger.warning(f"   Количество: {quantity:.6f}")
                self.logger.warning(f"   Цена: {price_rounded:.8f}")

                # Сбрасываем состояние
                self._reset_recovery_state()
                return True
            else:
                self.logger.error(f"❌ Ошибка временного стопа: {result}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка временного стопа: {e}")

        return False

    def _execute_dca_buy(self, action_data: Dict[str, Any], balance: float) -> bool:
        """🩹 ИСПРАВЛЕННОЕ исполнение DCA докупки с правильным обновлением позиции"""

        buy_size_percent = action_data['buy_size_percent']
        buy_price = action_data['buy_price']

        # Рассчитываем размер докупки
        buy_amount = balance * buy_size_percent
        quantity = buy_amount / buy_price

        self.logger.info(f"🩹 DCA ДОКУПКА #{self.dca_attempts + 1}")
        self.logger.info(f"   Причина: {action_data['reason']}")
        self.logger.info(f"   Размер: {buy_size_percent * 100:.0f}% депозита")
        self.logger.info(f"   Сумма: {buy_amount:.2f} EUR")
        self.logger.info(f"   Количество: {quantity:.6f}")
        self.logger.info(f"   Цена: {buy_price:.8f}")

        # Проверяем минимальные требования
        pair_settings = self.api.get_pair_settings()
        pair = f"{self.config.CURRENCY_1}_{self.config.CURRENCY_2}"
        min_amount = float(pair_settings.get(pair, {}).get('min_amount', 10.0))

        if buy_amount < min_amount:
            self.logger.warning(f"⚠️ Сумма докупки {buy_amount:.2f} < минимума {min_amount}")
            return False

        try:
            precision = int(pair_settings.get(pair, {}).get('price_precision', 8))
            price_rounded = round(buy_price, precision)

            result = self.api.create_order(pair, quantity, price_rounded, 'buy')

            if result.get('result'):
                self.logger.info(f"✅ DCA ДОКУПКА ИСПОЛНЕНА!")
                self.logger.info(f"   Ордер ID: {result.get('order_id', 'N/A')}")

                # Обновляем состояние восстановления
                self.dca_attempts += 1
                self.last_dca_time = datetime.now()

                # 📊 ИСПРАВЛЕНИЕ: Правильно обновляем позицию в менеджере
                trade_info = {
                    'type': 'buy',
                    'quantity': quantity,
                    'price': price_rounded,
                    'amount': buy_amount,
                    'commission': buy_amount * self.config.AUTO_COMMISSION_RATE,
                    'timestamp': int(time.time())  # Unix timestamp
                }

                # Обновляем позицию
                self.position_manager.update_position(self.config.CURRENCY_1, trade_info)

                # 🔧 ИСПРАВЛЕНИЕ: Добавляем задержку для синхронизации с биржей
                time.sleep(2)  # 2 секунды на обновление данных биржи

                # Логируем новую позицию
                updated_position = self.position_manager.get_position(self.config.CURRENCY_1)
                if updated_position:
                    self.logger.info(f"📊 Обновленная позиция:")
                    self.logger.info(f"   Новая средняя цена: {updated_position.avg_price:.8f}")
                    self.logger.info(f"   Общее количество: {updated_position.quantity:.6f}")

                return True
            else:
                self.logger.error(f"❌ Ошибка DCA докупки: {result}")
        except Exception as e:
            self.logger.error(f"❌ Исключение при DCA докупке: {e}")

        return False

    def _reset_recovery_state(self):
        """🔄 Сброс состояния после закрытия позиции"""
        self.logger.info("🔄 Сброс состояния системы восстановления")
        self.dca_attempts = 0
        self.position_start_time = None
        self.last_dca_time = None

    def get_recovery_status(self) -> Dict[str, Any]:
        """📊 Получение статуса системы восстановления"""
        return {
            'dca_attempts': self.dca_attempts,
            'max_dca_attempts': self.dca_max_attempts,
            'time_in_position_hours': self._get_time_in_position(),
            'can_make_dca': self._can_make_dca(),
            'last_dca_time': self.last_dca_time.isoformat() if self.last_dca_time else None,
            'emergency_stop_threshold': self.emergency_stop_loss * 100,
            'time_stop_threshold_hours': self.time_based_stop_hours
        }

    def force_reset_state(self):
        """🔧 Принудительный сброс состояния (для отладки)"""
        self.logger.warning("🔧 ПРИНУДИТЕЛЬНЫЙ СБРОС состояния восстановления")
        self._reset_recovery_state()


if __name__ == "__main__":
    print("🩹 Система восстановления убыточных позиций")
    print("=" * 50)
    print("Функции:")
    print("• DCA докупка при убытке >2%")
    print("• Экстренный стоп-лосс при -8%")
    print("• Временной стоп через 6 часов")
    print("• Активация trailing в убытке")
    print("• Максимум 3 DCA попытки")
    print("• Интервал между DCA: 30 минут")
