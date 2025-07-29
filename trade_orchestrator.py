import logging
import time
from typing import Dict, Any, Tuple, Optional
from datetime import datetime


class TradeOrchestrator:
    """🎼 Оркестратор торговых операций - вынесена логика из bot.py"""

    def __init__(self, config, api_client, risk_manager, position_manager,
                 dca_strategy, pyramid_strategy, trailing_stop):
        self.config = config
        self.api = api_client
        self.risk_manager = risk_manager
        self.position_manager = position_manager
        self.dca_strategy = dca_strategy
        self.pyramid_strategy = pyramid_strategy
        self.trailing_stop = trailing_stop

        self.logger = logging.getLogger(__name__)
        self.pair = f"{config.CURRENCY_1}_{config.CURRENCY_2}"

        # Кэш для оптимизации
        self._last_price_update = 0
        self._cached_price = 0.0
        self._price_cache_duration = 2  # 2 секунды

    def execute_trade_cycle(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """🔄 Главный торговый цикл"""

        cycle_result = {
            'success': False,
            'action': 'none',
            'reason': '',
            'trade_executed': False
        }

        try:
            # Валидация входных данных
            if not self._validate_market_data(market_data):
                cycle_result['reason'] = 'Невалидные рыночные данные'
                return cycle_result

            # Проверяем открытые ордера
            if self._has_pending_orders():
                cycle_result['reason'] = 'Есть открытые ордера'
                return cycle_result

            # Определяем текущее состояние
            position_state = self._analyze_position_state(market_data)

            # Выполняем соответствующую логику
            if position_state['has_position']:
                cycle_result = self._handle_existing_position(market_data, position_state)
            else:
                cycle_result = self._handle_no_position(market_data)

            cycle_result['success'] = True
            return cycle_result

        except Exception as e:
            self.logger.error(f"❌ Ошибка в торговом цикле: {e}")
            cycle_result['reason'] = f'Ошибка: {str(e)}'
            return cycle_result

    def _validate_market_data(self, market_data: Dict[str, Any]) -> bool:
        """✅ Валидация рыночных данных"""
        required_fields = ['current_price', 'balance', 'doge_balance']

        for field in required_fields:
            if field not in market_data or market_data[field] is None:
                self.logger.error(f"❌ Отсутствует поле: {field}")
                return False

        if market_data['current_price'] <= 0:
            self.logger.error(f"❌ Некорректная цена: {market_data['current_price']}")
            return False

        return True

    def _has_pending_orders(self) -> bool:
        """📋 Проверка открытых ордеров"""
        try:
            open_orders = self.api.get_open_orders()
            pair_orders = open_orders.get(self.pair, [])

            if pair_orders:
                self.logger.info(f"⏳ Открытых ордеров: {len(pair_orders)}")
                # Здесь можно добавить логику отмены старых ордеров
                return True

            return False
        except Exception as e:
            self.logger.error(f"❌ Ошибка проверки ордеров: {e}")
            return True  # В случае ошибки лучше не торговать

    def _analyze_position_state(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """📊 Анализ текущего состояния позиции"""
        accurate_data = self.position_manager.get_accurate_position_data(self.config.CURRENCY_1)
        min_quantity = self._get_min_quantity()

        has_position = accurate_data['quantity'] >= min_quantity

        return {
            'has_position': has_position,
            'quantity': accurate_data['quantity'],
            'avg_price': accurate_data['avg_price'],
            'accurate_data': accurate_data,
            'min_quantity': min_quantity
        }

    def _handle_existing_position(self, market_data: Dict[str, Any],
                                  position_state: Dict[str, Any]) -> Dict[str, Any]:
        """💎 Обработка существующей позиции"""

        current_price = market_data['current_price']
        accurate_data = position_state['accurate_data']

        self.logger.info(f"💎 Анализ позиции:")
        self.logger.info(f"   Количество: {accurate_data['quantity']:.6f} DOGE")
        self.logger.info(f"   Средняя цена: {accurate_data['avg_price']:.8f}")

        # Пытаемся пирамидальную продажу
        pyramid_result = self._try_pyramid_sell(current_price, position_state)
        if pyramid_result['should_sell']:
            return self._execute_pyramid_sell(pyramid_result)

        # Если пирамида не сработала - пробуем trailing stop
        trailing_result = self._try_trailing_stop(current_price, position_state)
        if trailing_result['should_sell']:
            return self._execute_trailing_sell(trailing_result)

        return {
            'action': 'hold',
            'reason': 'Удерживаем позицию',
            'trade_executed': False
        }

    def _handle_no_position(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """🛒 Обработка отсутствия позиции"""

        current_price = market_data['current_price']
        balance_eur = market_data['balance']

        # Обновляем историю цен для DCA
        self.dca_strategy.update_price_history(current_price)

        # Проверяем DCA докупку на дне
        should_buy_bottom, bottom_qty, bottom_price = self.dca_strategy.should_buy_on_bottom(market_data)
        if should_buy_bottom:
            return self._execute_dca_buy(bottom_qty, bottom_price, 'bottom_buy')

        # Проверяем первоначальную DCA покупку
        should_buy_initial, initial_qty, initial_price = self.dca_strategy.should_buy_initial(market_data)
        if should_buy_initial:
            return self._execute_dca_buy(initial_qty, initial_price, 'initial_buy')

        return {
            'action': 'wait',
            'reason': 'Ждем подходящего момента для входа',
            'trade_executed': False
        }

    def _try_pyramid_sell(self, current_price: float,
                          position_state: Dict[str, Any]) -> Dict[str, Any]:
        """🏗️ Попытка пирамидальной продажи"""
        try:
            position_data = {
                'quantity': position_state['quantity'],
                'avg_price': position_state['avg_price']
            }

            return self.pyramid_strategy.analyze_sell_opportunity(current_price, position_data)

        except Exception as e:
            self.logger.error(f"❌ Ошибка пирамидальной стратегии: {e}")
            return {'should_sell': False, 'reason': f'Ошибка пирамиды: {str(e)}'}

    def _try_trailing_stop(self, current_price: float,
                           position_state: Dict[str, Any]) -> Dict[str, Any]:
        """🎯 Попытка trailing stop"""
        try:
            should_sell, sell_qty, reason = self.trailing_stop.update_position(
                currency=self.config.CURRENCY_1,
                current_price=current_price,
                entry_price=position_state['avg_price'],
                total_quantity=position_state['quantity'],
                get_fresh_price_callback=self._get_fresh_price
            )

            return {
                'should_sell': should_sell,
                'sell_quantity': sell_qty,
                'reason': reason
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка trailing stop: {e}")
            return {'should_sell': False, 'reason': f'Ошибка trailing: {str(e)}'}

    def _execute_pyramid_sell(self, pyramid_data: Dict[str, Any]) -> Dict[str, Any]:
        """🚀 Исполнение пирамидальной продажи"""
        try:
            success = self.pyramid_strategy.execute_pyramid_sell(pyramid_data, self.api)

            if success:
                # Обновляем позицию после продажи
                trade_info = {
                    'type': 'sell',
                    'quantity': pyramid_data['sell_quantity'],
                    'price': pyramid_data['sell_price'],
                    'amount': pyramid_data['sell_quantity'] * pyramid_data['sell_price'],
                    'commission': pyramid_data['sell_quantity'] * pyramid_data[
                        'sell_price'] * self.config.AUTO_COMMISSION_RATE,
                    'timestamp': int(time.time())
                }
                self.position_manager.update_position(self.config.CURRENCY_1, trade_info)

                return {
                    'action': 'pyramid_sell',
                    'reason': f"Пирамидальная продажа: {pyramid_data.get('reason', '')}",
                    'trade_executed': True,
                    'quantity': pyramid_data['sell_quantity'],
                    'price': pyramid_data['sell_price']
                }
            else:
                return {
                    'action': 'pyramid_sell_failed',
                    'reason': 'Не удалось исполнить пирамидальную продажу',
                    'trade_executed': False
                }

        except Exception as e:
            self.logger.error(f"❌ Ошибка исполнения пирамидальной продажи: {e}")
            return {
                'action': 'pyramid_sell_error',
                'reason': f'Ошибка: {str(e)}',
                'trade_executed': False
            }

    def _execute_trailing_sell(self, trailing_data: Dict[str, Any]) -> Dict[str, Any]:
        """🎯 Исполнение trailing stop продажи"""
        try:
            quantity = trailing_data['sell_quantity']
            reason = trailing_data['reason']

            # Определяем тип продажи по reason
            if reason.startswith("AGGRESSIVE_SELL:"):
                parts = reason.split(":")
                trigger_price = float(parts[1])
                sell_price = self._calculate_aggressive_sell_price(trigger_price, "partial")
            elif reason.startswith("MARKET_SELL:"):
                parts = reason.split(":")
                trigger_price = float(parts[1])
                sell_price = self._calculate_aggressive_sell_price(trigger_price, "market")
            else:
                # Обычная продажа
                current_price = self._get_fresh_price()
                sell_price = current_price * 0.9998

            success = self._execute_sell_order(quantity, sell_price)

            if success:
                return {
                    'action': 'trailing_sell',
                    'reason': f"Trailing stop: {reason}",
                    'trade_executed': True,
                    'quantity': quantity,
                    'price': sell_price
                }
            else:
                return {
                    'action': 'trailing_sell_failed',
                    'reason': 'Не удалось исполнить trailing продажу',
                    'trade_executed': False
                }

        except Exception as e:
            self.logger.error(f"❌ Ошибка исполнения trailing продажи: {e}")
            return {
                'action': 'trailing_sell_error',
                'reason': f'Ошибка: {str(e)}',
                'trade_executed': False
            }

    def _execute_dca_buy(self, quantity: float, price: float, buy_type: str) -> Dict[str, Any]:
        """🛒 Исполнение DCA покупки"""
        try:
            success = self._execute_buy_order(quantity, price)

            if success:
                # Уведомляем DCA стратегию
                is_initial = (buy_type == 'initial_buy')
                self.dca_strategy.on_purchase_executed(price, quantity, is_initial=is_initial)

                return {
                    'action': f'dca_{buy_type}',
                    'reason': f'DCA покупка: {buy_type}',
                    'trade_executed': True,
                    'quantity': quantity,
                    'price': price
                }
            else:
                return {
                    'action': f'dca_{buy_type}_failed',
                    'reason': f'Не удалось исполнить DCA покупку: {buy_type}',
                    'trade_executed': False
                }

        except Exception as e:
            self.logger.error(f"❌ Ошибка DCA покупки: {e}")
            return {
                'action': f'dca_{buy_type}_error',
                'reason': f'Ошибка: {str(e)}',
                'trade_executed': False
            }

    def _execute_buy_order(self, quantity: float, price: float) -> bool:
        """🛒 Базовое исполнение ордера на покупку"""
        try:
            # Получаем настройки пары
            pair_settings = self.api.get_pair_settings()
            pair_info = pair_settings.get(self.pair, {})

            # Проверки
            min_amount = float(pair_info.get('min_amount', 10.0))
            order_amount = quantity * price

            if order_amount < min_amount:
                self.logger.warning(f"❌ Сумма ордера {order_amount:.4f} < минимума {min_amount}")
                return False

            # Создание ордера
            precision = int(pair_info.get('price_precision', 8))
            price_rounded = round(price, precision)

            result = self.api.create_order(self.pair, quantity, price_rounded, 'buy')

            if result.get('result'):
                self.logger.info(f"✅ ОРДЕР НА ПОКУПКУ: {quantity:.6f} по {price_rounded:.8f}")
                return True
            else:
                self.logger.error(f"❌ Ошибка создания ордера: {result}")
                return False

        except Exception as e:
            self.logger.error(f"❌ Ошибка создания ордера на покупку: {e}")
            return False

    def _execute_sell_order(self, quantity: float, price: float) -> bool:
        """💎 Базовое исполнение ордера на продажу"""
        try:
            # Получаем настройки пары
            pair_settings = self.api.get_pair_settings()
            pair_info = pair_settings.get(self.pair, {})

            precision = int(pair_info.get('price_precision', 8))
            price_rounded = round(price, precision)

            result = self.api.create_order(self.pair, quantity, price_rounded, 'sell')

            if result.get('result'):
                self.logger.info(f"✅ ОРДЕР НА ПРОДАЖУ: {quantity:.6f} по {price_rounded:.8f}")
                return True
            else:
                self.logger.error(f"❌ Ошибка создания ордера: {result}")
                return False

        except Exception as e:
            self.logger.error(f"❌ Ошибка создания ордера на продажу: {e}")
            return False

    def _get_fresh_price(self) -> float:
        """💱 Получение свежей цены с кэшированием"""
        current_time = time.time()

        # Проверяем кэш
        if (current_time - self._last_price_update < self._price_cache_duration and
                self._cached_price > 0):
            return self._cached_price

        try:
            trades = self.api.get_trades(self.pair)
            if self.pair in trades and trades[self.pair]:
                price = float(trades[self.pair][0]['price'])

                # Обновляем кэш
                self._cached_price = price
                self._last_price_update = current_time

                return price
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения свежей цены: {e}")

        return self._cached_price if self._cached_price > 0 else 0.0

    def _calculate_aggressive_sell_price(self, trigger_price: float, sell_type: str) -> float:
        """📊 Расчет агрессивной цены продажи"""
        current_market_price = self._get_fresh_price()

        if current_market_price == 0:
            current_market_price = trigger_price

        if sell_type == "market":
            discount = 0.003  # 0.3%
        elif sell_type == "partial":
            discount = 0.001  # 0.1%
        else:
            discount = 0.0005  # 0.05%

        return current_market_price * (1 - discount)

    def _get_min_quantity(self) -> float:
        """📏 Получение минимального количества для торговли"""
        try:
            pair_settings = self.api.get_pair_settings()
            return float(pair_settings.get(self.pair, {}).get('min_quantity', 0.01))
        except:
            return 0.01

    def get_orchestrator_status(self) -> Dict[str, Any]:
        """📊 Статус оркестратора"""
        return {
            'price_cache_age': time.time() - self._last_price_update,
            'cached_price': self._cached_price,
            'pair': self.pair,
            'last_update': datetime.now().isoformat()
        }