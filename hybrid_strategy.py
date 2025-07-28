# hybrid_strategy.py - Гибридная стратегия: Пирамида + Умная DCA
import logging
import time
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime
from dataclasses import dataclass


@dataclass
class PositionMetrics:
    """📊 Метрики позиции для принятия решений"""
    quantity: float
    avg_price: float
    current_price: float
    total_cost: float
    current_value: float
    pnl_percent: float
    pnl_amount: float

    @property
    def is_profitable(self) -> bool:
        return self.pnl_percent > 0

    @property
    def drop_from_avg(self) -> float:
        return (self.avg_price - self.current_price) / self.avg_price


class HybridStrategy:
    """🔄 Гибридная стратегия: сочетает пирамидальные продажи и умную DCA"""

    def __init__(self, config, api_client, position_manager, pyramid_strategy):
        self.config = config
        self.api = api_client
        self.position_manager = position_manager
        self.pyramid_strategy = pyramid_strategy
        self.logger = logging.getLogger(__name__)

        # 🎯 Настройки гибридной стратегии
        self.enable_smart_dca = True
        self.dca_drop_threshold = 0.03        # DCA при падении >3%
        self.dca_max_position_percent = 0.65  # Максимум 65% депозита в позиции
        self.dca_purchase_size = 0.06         # 6% депозита на DCA докупку
        self.adaptive_stop_loss = True
        self.base_stop_loss = 0.18            # Базовый стоп-лосс 18%

        # Минимальные интервалы между действиями
        self.min_time_between_dca = 600       # 10 минут между DCA
        self.min_time_between_pyramid = 300   # 5 минут между пирамидой

        # История действий
        self.last_dca_time = 0
        self.last_pyramid_time = 0
        self.dca_purchases_count = 0

        self.logger.info("🔄 Гибридная стратегия инициализирована")
        self.logger.info(f"   🛒 DCA при падении: >{self.dca_drop_threshold*100:.0f}%")
        self.logger.info(f"   📊 Максимум позиции: {self.dca_max_position_percent*100:.0f}%")
        self.logger.info(f"   🚨 Адаптивный стоп-лосс: {self.base_stop_loss*100:.0f}%")

    def analyze_and_execute(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """🎯 Главный анализ и принятие решений"""

        current_price = market_data['current_price']
        balance = market_data['balance']
        position_data = market_data['accurate_position']

        # Получаем метрики позиции
        metrics = self._calculate_position_metrics(current_price, position_data, balance)

        if not metrics:
            return {'action': 'no_position', 'reason': 'Нет позиции для анализа'}

        self.logger.info(f"🔄 Гибридный анализ позиции:")
        self.logger.info(f"   📊 {metrics.quantity:.4f} DOGE по {metrics.avg_price:.6f}")
        self.logger.info(f"   💰 P&L: {metrics.pnl_percent:+.2f}% ({metrics.pnl_amount:+.4f} EUR)")
        self.logger.info(f"   📉 Падение от средней: {metrics.drop_from_avg*100:.2f}%")

        # Проверяем стоп-лосс (приоритет #1)
        stop_loss_result = self._check_adaptive_stop_loss(metrics)
        if stop_loss_result['should_execute']:
            return stop_loss_result

        # Анализируем возможности пирамидальной продажи (приоритет #2)
        pyramid_result = self._analyze_pyramid_opportunity(current_price, position_data)
        if pyramid_result['should_execute']:
            return pyramid_result

        # Анализируем возможности умной DCA (приоритет #3)
        dca_result = self._analyze_smart_dca_opportunity(metrics, balance)
        if dca_result['should_execute']:
            return dca_result

        # Если ничего не нужно делать
        return {
            'action': 'hold',
            'reason': f'Держим позицию: P&L {metrics.pnl_percent:+.2f}%',
            'should_execute': False
        }

    def _calculate_position_metrics(self, current_price: float, position_data: Dict, balance: float) -> Optional[PositionMetrics]:
        """📊 Расчет метрик позиции"""

        quantity = position_data.get('quantity', 0)
        avg_price = position_data.get('avg_price', 0)

        if quantity <= 0 or avg_price <= 0:
            return None

        total_cost = quantity * avg_price
        current_value = quantity * current_price
        pnl_amount = current_value - total_cost
        pnl_percent = (current_price - avg_price) / avg_price

        return PositionMetrics(
            quantity=quantity,
            avg_price=avg_price,
            current_price=current_price,
            total_cost=total_cost,
            current_value=current_value,
            pnl_percent=pnl_percent,
            pnl_amount=pnl_amount
        )

    def _check_adaptive_stop_loss(self, metrics: PositionMetrics) -> Dict[str, Any]:
        """🚨 Проверка адаптивного стоп-лосса"""

        # Рассчитываем адаптивный стоп-лосс
        stop_loss_threshold = self.base_stop_loss

        if self.adaptive_stop_loss:
            # Если делали DCA докупки - увеличиваем терпимость
            if self.dca_purchases_count > 0:
                stop_loss_threshold = self.base_stop_loss + (self.dca_purchases_count * 0.03)
                stop_loss_threshold = min(stop_loss_threshold, 0.25)  # Максимум 25%

        loss_percent = -metrics.pnl_percent  # Превращаем в положительное число убытка

        if loss_percent >= stop_loss_threshold:
            self.logger.error(f"🚨 АДАПТИВНЫЙ СТОП-ЛОСС!")
            self.logger.error(f"   Убыток: {loss_percent*100:.2f}%")
            self.logger.error(f"   Порог: {stop_loss_threshold*100:.2f}%")
            self.logger.error(f"   DCA докупок: {self.dca_purchases_count}")

            return {
                'action': 'adaptive_stop_loss',
                'should_execute': True,
                'quantity': metrics.quantity,
                'reason': f'Адаптивный стоп-лосс: убыток {loss_percent*100:.1f}% >= {stop_loss_threshold*100:.1f}%',
                'urgency': 'critical',
                'sell_price': metrics.current_price * 0.995  # Агрессивная продажа
            }

        return {'should_execute': False}

    def _analyze_pyramid_opportunity(self, current_price: float, position_data: Dict) -> Dict[str, Any]:
        """🏗️ Анализ пирамидальной продажи"""

        # Проверяем кулдаун
        current_time = time.time()
        if current_time - self.last_pyramid_time < self.min_time_between_pyramid:
            remaining = (self.min_time_between_pyramid - (current_time - self.last_pyramid_time)) / 60
            return {
                'should_execute': False,
                'reason': f'Пирамида кулдаун: {remaining:.0f} мин'
            }

        try:
            # Используем существующую пирамидальную стратегию
            position_for_pyramid = {
                'quantity': position_data['quantity'],
                'avg_price': position_data['avg_price']
            }

            pyramid_result = self.pyramid_strategy.analyze_sell_opportunity(current_price, position_for_pyramid)

            if pyramid_result.get('should_sell'):
                self.last_pyramid_time = current_time

                return {
                    'action': 'pyramid_sell',
                    'should_execute': True,
                    'pyramid_data': pyramid_result,
                    'reason': f"Пирамида: {pyramid_result.get('reason', 'продажа')}"
                }

        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа пирамиды: {e}")

        return {'should_execute': False}

    def _analyze_smart_dca_opportunity(self, metrics: PositionMetrics, balance: float) -> Dict[str, Any]:
        """🛒 Анализ умной DCA докупки"""

        if not self.enable_smart_dca:
            return {'should_execute': False, 'reason': 'Smart DCA отключена'}

        # Проверяем условия для DCA
        drop_from_avg = metrics.drop_from_avg
        current_position_percent = metrics.current_value / (balance + metrics.current_value)

        # Условие 1: Достаточное падение от средней цены
        if drop_from_avg < self.dca_drop_threshold:
            return {
                'should_execute': False,
                'reason': f'Падение {drop_from_avg*100:.1f}% < порога {self.dca_drop_threshold*100:.0f}%'
            }

        # Условие 2: Не превышаем максимальную позицию
        dca_amount = balance * self.dca_purchase_size
        new_position_value = metrics.current_value + dca_amount
        new_position_percent = new_position_value / (balance + new_position_value)

        if new_position_percent > self.dca_max_position_percent:
            return {
                'should_execute': False,
                'reason': f'Позиция {new_position_percent*100:.0f}% > лимита {self.dca_max_position_percent*100:.0f}%'
            }

        # Условие 3: Кулдаун между DCA
        current_time = time.time()
        if current_time - self.last_dca_time < self.min_time_between_dca:
            remaining = (self.min_time_between_dca - (current_time - self.last_dca_time)) / 60
            return {
                'should_execute': False,
                'reason': f'DCA кулдаун: {remaining:.0f} мин'
            }

        # Условие 4: Достаточный баланс
        if balance < dca_amount:
            return {
                'should_execute': False,
                'reason': f'Недостаточно баланса: {balance:.2f} < {dca_amount:.2f}'
            }

        # Рассчитываем новую среднюю цену после DCA
        dca_quantity = dca_amount / metrics.current_price
        new_total_quantity = metrics.quantity + dca_quantity
        new_total_cost = metrics.total_cost + dca_amount
        new_avg_price = new_total_cost / new_total_quantity

        price_improvement = (metrics.avg_price - new_avg_price) / metrics.avg_price * 100

        self.logger.info(f"🛒 УМНАЯ DCA ВОЗМОЖНА!")
        self.logger.info(f"   Падение: {drop_from_avg*100:.1f}%")
        self.logger.info(f"   Докупка: {dca_quantity:.4f} DOGE за {dca_amount:.2f} EUR")
        self.logger.info(f"   Новая средняя: {metrics.avg_price:.6f} → {new_avg_price:.6f}")
        self.logger.info(f"   Улучшение цены: {price_improvement:.2f}%")
        self.logger.info(f"   Новая позиция: {new_position_percent*100:.0f}% депозита")

        return {
            'action': 'smart_dca_buy',
            'should_execute': True,
            'quantity': dca_quantity,
            'price': metrics.current_price * 0.9995,  # Небольшая скидка
            'amount': dca_amount,
            'new_avg_price': new_avg_price,
            'price_improvement': price_improvement,
            'reason': f'Smart DCA: падение {drop_from_avg*100:.1f}%, улучшение цены на {price_improvement:.2f}%'
        }

    def execute_action(self, action_data: Dict[str, Any]) -> bool:
        """🚀 Исполнение действия"""

        action = action_data['action']

        try:
            if action == 'pyramid_sell':
                return self._execute_pyramid_sell(action_data)

            elif action == 'smart_dca_buy':
                return self._execute_smart_dca_buy(action_data)

            elif action == 'adaptive_stop_loss':
                return self._execute_adaptive_stop_loss(action_data)

            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка исполнения {action}: {e}")
            return False

    def _execute_pyramid_sell(self, action_data: Dict[str, Any]) -> bool:
        """🏗️ Исполнение пирамидальной продажи"""
        pyramid_data = action_data['pyramid_data']

        success = self.pyramid_strategy.execute_pyramid_sell(pyramid_data, self.api)

        if success:
            self.logger.info(f"✅ Пирамидальная продажа исполнена")
            return True

        return False

    def _execute_smart_dca_buy(self, action_data: Dict[str, Any]) -> bool:
        """🛒 Исполнение умной DCA покупки"""

        quantity = action_data['quantity']
        price = action_data['price']

        try:
            pair = f"{self.config.CURRENCY_1}_{self.config.CURRENCY_2}"

            # Получаем настройки пары
            pair_settings = self.api.get_pair_settings()
            precision = int(pair_settings.get(pair, {}).get('price_precision', 8))
            price_rounded = round(price, precision)

            result = self.api.create_order(pair, quantity, price_rounded, 'buy')

            if result.get('result'):
                self.logger.info(f"✅ УМНАЯ DCA ПОКУПКА ИСПОЛНЕНА!")
                self.logger.info(f"   Количество: {quantity:.6f} DOGE")
                self.logger.info(f"   Цена: {price_rounded:.8f} EUR")
                self.logger.info(f"   Ордер ID: {result.get('order_id', 'N/A')}")

                # Обновляем счетчики
                self.last_dca_time = time.time()
                self.dca_purchases_count += 1

                # Обновляем позицию
                trade_info = {
                    'type': 'buy',
                    'quantity': quantity,
                    'price': price_rounded,
                    'amount': quantity * price_rounded,
                    'commission': quantity * price_rounded * self.config.AUTO_COMMISSION_RATE,
                    'timestamp': int(time.time())
                }

                self.position_manager.update_position(self.config.CURRENCY_1, trade_info)

                return True
            else:
                self.logger.error(f"❌ Ошибка создания DCA ордера: {result}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка исполнения DCA: {e}")

        return False

    def _execute_adaptive_stop_loss(self, action_data: Dict[str, Any]) -> bool:
        """🚨 Исполнение адаптивного стоп-лосса"""

        quantity = action_data['quantity']
        price = action_data['sell_price']

        try:
            pair = f"{self.config.CURRENCY_1}_{self.config.CURRENCY_2}"

            # Получаем настройки пары
            pair_settings = self.api.get_pair_settings()
            precision = int(pair_settings.get(pair, {}).get('price_precision', 8))
            price_rounded = round(price, precision)

            result = self.api.create_order(pair, quantity, price_rounded, 'sell')

            if result.get('result'):
                self.logger.error(f"🚨 АДАПТИВНЫЙ СТОП-ЛОСС ИСПОЛНЕН!")
                self.logger.error(f"   Количество: {quantity:.6f} DOGE")
                self.logger.error(f"   Цена: {price_rounded:.8f} EUR")
                self.logger.error(f"   Ордер ID: {result.get('order_id', 'N/A')}")

                # Сбрасываем счетчики
                self.dca_purchases_count = 0
                self.last_dca_time = 0

                return True
            else:
                self.logger.error(f"❌ Ошибка создания стоп-лосс ордера: {result}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка исполнения стоп-лосса: {e}")

        return False

    def get_strategy_status(self) -> Dict[str, Any]:
        """📊 Статус гибридной стратегии"""
        current_time = time.time()

        return {
            'strategy_name': 'hybrid',
            'smart_dca_enabled': self.enable_smart_dca,
            'dca_purchases_count': self.dca_purchases_count,
            'last_dca_minutes_ago': (current_time - self.last_dca_time) / 60 if self.last_dca_time > 0 else None,
            'last_pyramid_minutes_ago': (current_time - self.last_pyramid_time) / 60 if self.last_pyramid_time > 0 else None,
            'settings': {
                'dca_drop_threshold': f"{self.dca_drop_threshold*100:.0f}%",
                'max_position': f"{self.dca_max_position_percent*100:.0f}%",
                'dca_size': f"{self.dca_purchase_size*100:.0f}%",
                'base_stop_loss': f"{self.base_stop_loss*100:.0f}%",
                'adaptive_stop_loss': self.adaptive_stop_loss
            }
        }


# Интеграция в торговый оркестратор
class HybridTradeOrchestrator:
    """🎼 Торговый оркестратор с гибридной стратегией"""

    def __init__(self, config, api_client, risk_manager, position_manager,
                 pyramid_strategy, trailing_stop):
        self.config = config
        self.api = api_client
        self.risk_manager = risk_manager
        self.position_manager = position_manager
        self.trailing_stop = trailing_stop

        # 🔄 Создаем гибридную стратегию
        self.hybrid_strategy = HybridStrategy(
            config, api_client, position_manager, pyramid_strategy
        )

        self.logger = logging.getLogger(__name__)
        self.pair = f"{config.CURRENCY_1}_{config.CURRENCY_2}"

    def execute_trade_cycle(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """🔄 Главный торговый цикл с гибридной стратегией"""

        try:
            # Валидация данных
            if not self._validate_market_data(market_data):
                return {'success': False, 'reason': 'Невалидные рыночные данные'}

            # Проверяем открытые ордера
            if self._has_pending_orders():
                return {'success': True, 'reason': 'Есть открытые ордера', 'action': 'wait'}

            # Определяем состояние позиции
            position_state = self._analyze_position_state(market_data)

            if position_state['has_position']:
                # Есть позиция - используем гибридную стратегию
                action_result = self.hybrid_strategy.analyze_and_execute(market_data)

                if action_result.get('should_execute'):
                    success = self.hybrid_strategy.execute_action(action_result)

                    return {
                        'success': True,
                        'action': action_result['action'],
                        'reason': action_result['reason'],
                        'trade_executed': success
                    }
                else:
                    return {
                        'success': True,
                        'action': action_result['action'],
                        'reason': action_result['reason'],
                        'trade_executed': False
                    }
            else:
                # Нет позиции - ищем точки входа
                return self._handle_no_position(market_data)

        except Exception as e:
            self.logger.error(f"❌ Ошибка в гибридном торговом цикле: {e}")
            return {'success': False, 'reason': f'Ошибка: {str(e)}'}

    def _validate_market_data(self, market_data: Dict[str, Any]) -> bool:
        """✅ Валидация рыночных данных"""
        required_fields = ['current_price', 'balance', 'accurate_position']
        return all(field in market_data for field in required_fields)

    def _has_pending_orders(self) -> bool:
        """📋 Проверка открытых ордеров"""
        try:
            open_orders = self.api.get_open_orders()
            pair_orders = open_orders.get(self.pair, [])
            return len(pair_orders) > 0
        except:
            return True  # В случае ошибки - считаем что есть ордера

    def _analyze_position_state(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """📊 Анализ состояния позиции"""
        accurate_data = market_data['accurate_position']

        # Минимальное количество для торговли
        min_quantity = self._get_min_quantity()

        return {
            'has_position': accurate_data['quantity'] >= min_quantity,
            'quantity': accurate_data['quantity'],
            'avg_price': accurate_data['avg_price']
        }

    def _handle_no_position(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """🛒 Обработка отсутствия позиции (поиск точек входа)"""
        # Здесь можно добавить логику поиска новых точек входа
        # Пока возвращаем ожидание
        return {
            'success': True,
            'action': 'wait_entry',
            'reason': 'Ждем точку входа',
            'trade_executed': False
        }

    def _get_min_quantity(self) -> float:
        """📏 Минимальное количество для торговли"""
        try:
            pair_settings = self.api.get_pair_settings()
            return float(pair_settings.get(self.pair, {}).get('min_quantity', 0.01))
        except:
            return 0.01

    def get_orchestrator_status(self) -> Dict[str, Any]:
        """📊 Статус оркестратора"""
        return {
            'type': 'hybrid_orchestrator',
            'pair': self.pair,
            'hybrid_strategy_status': self.hybrid_strategy.get_strategy_status(),
            'last_update': datetime.now().isoformat()
        }
