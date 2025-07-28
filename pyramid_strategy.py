import logging
import time
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime


class SmartPyramidStrategy:
    """🏗️ Умная пирамидальная стратегия: продаем по уровням прибыльности"""

    def __init__(self, config, position_manager):
        self.config = config
        self.position_manager = position_manager
        self.logger = logging.getLogger(__name__)

        # 🎯 НАСТРОЙКИ ПИРАМИДЫ (оптимизированы для DOGE)
        self.pyramid_levels = [
            {
                'name': 'Быстрая прибыль',
                'price_multiplier': 1.008,    # +0.8% - быстрая фиксация
                'sell_percent': 25,           # 25% позиции
                'min_profit_eur': 0.10        # Минимум 0.10 EUR прибыли
            },
            {
                'name': 'Средняя прибыль',
                'price_multiplier': 1.02,     # +2% - хорошая прибыль
                'sell_percent': 35,           # 35% позиции
                'min_profit_eur': 0.20        # Минимум 0.20 EUR прибыли
            },
            {
                'name': 'Хорошая прибыль',
                'price_multiplier': 1.04,     # +4% - отличная прибыль
                'sell_percent': 25,           # 25% позиции
                'min_profit_eur': 0.30        # Минимум 0.30 EUR прибыли
            },
            {
                'name': 'Отличная прибыль',
                'price_multiplier': 1.07,     # +7% - максимальная прибыль
                'sell_percent': 15,           # 15% позиции
                'min_profit_eur': 0.50        # Минимум 0.50 EUR прибыли
            }
        ]

        # 🛡️ ЗАЩИТНЫЕ НАСТРОЙКИ
        self.min_sell_quantity = 5.0          # Минимум 5 DOGE для продажи
        self.max_sell_per_cycle = 0.4          # Максимум 40% за один раз
        self.cooldown_between_sells = 300      # 5 минут между продажами
        self.last_sell_time = 0

        self.logger.info("🏗️ Умная пирамидальная стратегия инициализирована")
        self.logger.info(f"   📊 Уровней: {len(self.pyramid_levels)}")
        self.logger.info(f"   🛡️ Мин. количество: {self.min_sell_quantity} DOGE")
        self.logger.info(f"   ⏰ Кулдаун: {self.cooldown_between_sells} сек")

    def analyze_sell_opportunity(self, current_price: float, position_data: Dict[str, Any]) -> Dict[str, Any]:
        """🔍 Анализ возможности продажи по пирамидальной стратегии"""

        try:
            if not position_data or position_data.get('quantity', 0) == 0:
                return {'should_sell': False, 'reason': 'Нет позиции'}

            total_quantity = position_data['quantity']

            # Проверяем кулдаун
            if not self._can_sell_now():
                remaining_cooldown = self._get_remaining_cooldown()
                return {
                    'should_sell': False,
                    'reason': f'Кулдаун: {remaining_cooldown:.0f} сек до следующей продажи'
                }

            # Получаем детальную информацию о покупках
            purchase_levels = self._get_purchase_levels()

            if not purchase_levels:
                return {'should_sell': False, 'reason': 'Нет истории покупок'}

            # Анализируем каждый уровень пирамиды
            best_opportunity = None
            max_profit = 0

            for level in self.pyramid_levels:
                opportunity = self._analyze_pyramid_level(
                    current_price,
                    purchase_levels,
                    level,
                    total_quantity
                )

                if (opportunity['can_sell'] and
                    opportunity['total_profit'] > max_profit and
                    opportunity['total_profit'] >= level['min_profit_eur']):

                    best_opportunity = opportunity
                    max_profit = opportunity['total_profit']

            if best_opportunity:
                return {
                    'should_sell': True,
                    'strategy': 'smart_pyramid',
                    **best_opportunity
                }

            # Если нет подходящих уровней - показываем следующую цель
            next_target = self._get_next_target_price(current_price, purchase_levels)

            return {
                'should_sell': False,
                'reason': 'Нет прибыльных уровней для продажи',
                'next_target': next_target
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа пирамидальной стратегии: {e}")
            return {'should_sell': False, 'reason': f'Ошибка анализа: {str(e)}'}

    def _get_purchase_levels(self) -> List[Dict[str, Any]]:
        """📊 Получение уровней покупок из позиции"""

        try:
            position_obj = self.position_manager.get_position(self.config.CURRENCY_1)

            if not position_obj or not position_obj.trades:
                self.logger.warning("⚠️ Нет истории сделок в позиции")
                return []

            purchase_groups = []

            for trade in position_obj.trades:
                if trade.get('type') == 'buy':
                    purchase_groups.append({
                        'price': float(trade.get('price', 0)),
                        'quantity': float(trade.get('quantity', 0)),
                        'cost': float(trade.get('amount', 0)),
                        'date': trade.get('timestamp', 'unknown')
                    })

            # Сортируем по цене (от дешевых к дорогим)
            purchase_groups.sort(key=lambda x: x['price'])

            self.logger.debug(f"📊 Найдено {len(purchase_groups)} покупок для анализа")
            return purchase_groups

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения покупок: {e}")
            return []

    def _analyze_pyramid_level(self, current_price: float, purchases: List[Dict], level: Dict, total_quantity: float) -> Dict[str, Any]:
        """🔍 Анализ конкретного уровня пирамиды"""

        level_name = level['name']
        target_multiplier = level['price_multiplier']
        sell_percentage = level['sell_percent'] / 100

        # Находим покупки, которые можно продать с прибылью на этом уровне
        profitable_purchases = []

        for purchase in purchases:
            if purchase['price'] <= 0:
                continue

            required_price = purchase['price'] * target_multiplier

            if current_price >= required_price:
                profit_per_coin = current_price - purchase['price']
                total_profit_from_purchase = profit_per_coin * purchase['quantity']
                profit_percent = (profit_per_coin / purchase['price']) * 100

                profitable_purchases.append({
                    'purchase': purchase,
                    'profit_per_coin': profit_per_coin,
                    'total_profit_from_purchase': total_profit_from_purchase,
                    'profit_percent': profit_percent,
                    'required_price': required_price
                })

        if not profitable_purchases:
            return {'can_sell': False, 'level': level_name, 'reason': 'Нет прибыльных покупок'}

        # Рассчитываем количество для продажи
        total_profitable_quantity = sum(p['purchase']['quantity'] for p in profitable_purchases)
        max_sell_by_percentage = total_quantity * sell_percentage
        max_sell_by_cycle_limit = total_quantity * self.max_sell_per_cycle

        sell_quantity = min(
            total_profitable_quantity,
            max_sell_by_percentage,
            max_sell_by_cycle_limit
        )

        # Проверяем минимальное количество
        if sell_quantity < self.min_sell_quantity:
            return {
                'can_sell': False,
                'level': level_name,
                'reason': f'Количество {sell_quantity:.2f} < минимума {self.min_sell_quantity}'
            }

        # Выбираем самые дешевые покупки для продажи (FIFO по прибыльности)
        profitable_purchases.sort(key=lambda x: x['purchase']['price'])

        selected_for_sell = []
        remaining_to_sell = sell_quantity
        total_cost_of_sold = 0

        for p in profitable_purchases:
            if remaining_to_sell <= 0:
                break

            sell_from_this = min(remaining_to_sell, p['purchase']['quantity'])
            cost_of_this_part = sell_from_this * p['purchase']['price']

            selected_for_sell.append({
                'quantity': sell_from_this,
                'buy_price': p['purchase']['price'],
                'cost': cost_of_this_part,
                'profit': (current_price - p['purchase']['price']) * sell_from_this
            })

            total_cost_of_sold += cost_of_this_part
            remaining_to_sell -= sell_from_this

        total_profit = sum(s['profit'] for s in selected_for_sell)
        revenue = sell_quantity * current_price
        profit_percent_total = (total_profit / total_cost_of_sold * 100) if total_cost_of_sold > 0 else 0

        return {
            'can_sell': True,
            'level': level_name,
            'sell_quantity': sell_quantity,
            'sell_price': current_price * 0.9995,  # Небольшая скидка для исполнения
            'total_profit': total_profit,
            'profit_percent': profit_percent_total,
            'revenue': revenue,
            'cost': total_cost_of_sold,
            'selected_purchases': selected_for_sell,
            'target_multiplier': target_multiplier,
            'reason': f'{level_name}: продажа {sell_quantity:.2f} DOGE с прибылью {total_profit:.4f} EUR ({profit_percent_total:.1f}%)'
        }

    def _get_next_target_price(self, current_price: float, purchases: List[Dict]) -> Dict[str, Any]:
        """🎯 Определение следующей целевой цены"""

        if not purchases:
            return {'price': current_price * 1.02, 'reason': 'Нет данных о покупках'}

        # Находим ближайший достижимый уровень прибыли
        min_required_price = float('inf')
        target_info = None

        for purchase in purchases:
            for level in self.pyramid_levels:
                required_price = purchase['price'] * level['price_multiplier']
                if required_price > current_price and required_price < min_required_price:
                    min_required_price = required_price
                    target_info = {
                        'purchase_price': purchase['price'],
                        'level': level,
                        'required_price': required_price
                    }

        if target_info:
            growth_needed = (min_required_price - current_price) / current_price * 100
            return {
                'price': min_required_price,
                'growth_needed': growth_needed,
                'target_level': target_info['level']['name'],
                'purchase_price': target_info['purchase_price'],
                'reason': f"До {target_info['level']['name']}: рост на {growth_needed:.1f}% до {min_required_price:.6f}"
            }

        return {
            'price': current_price * 1.02,
            'growth_needed': 2.0,
            'reason': 'Все уровни достигнуты, ожидаем роста +2%'
        }

    def _can_sell_now(self) -> bool:
        """⏰ Проверка возможности продажи (кулдаун)"""
        current_time = time.time()
        return (current_time - self.last_sell_time) >= self.cooldown_between_sells

    def _get_remaining_cooldown(self) -> float:
        """⏰ Получение оставшегося времени кулдауна"""
        current_time = time.time()
        elapsed = current_time - self.last_sell_time
        return max(0, self.cooldown_between_sells - elapsed)

    def execute_pyramid_sell(self, sell_data: Dict[str, Any], api_client) -> bool:
        """🚀 Исполнение пирамидальной продажи"""

        if not sell_data.get('should_sell'):
            return False

        quantity = sell_data['sell_quantity']
        price = sell_data['sell_price']
        level = sell_data['level']
        expected_profit = sell_data['total_profit']

        self.logger.info(f"🏗️ ПИРАМИДАЛЬНАЯ ПРОДАЖА: {level}")
        self.logger.info(f"   Количество: {quantity:.6f} DOGE")
        self.logger.info(f"   Цена: {price:.8f} EUR")
        self.logger.info(f"   Ожидаемая прибыль: {expected_profit:.4f} EUR")
        self.logger.info(f"   Процент прибыли: {sell_data.get('profit_percent', 0):.1f}%")

        # Детализация по покупкам
        self.logger.info(f"   📊 Детализация продажи:")
        for i, purchase in enumerate(sell_data.get('selected_purchases', []), 1):
            self.logger.info(
                f"     {i}. {purchase['quantity']:.4f} DOGE "
                f"(куплено по {purchase['buy_price']:.6f}) → "
                f"прибыль {purchase['profit']:.4f} EUR"
            )

        try:
            pair = f"{self.config.CURRENCY_1}_{self.config.CURRENCY_2}"

            # Округляем цену согласно настройкам биржи
            pair_settings = api_client.get_pair_settings()
            precision = int(pair_settings.get(pair, {}).get('price_precision', 8))
            price_rounded = round(price, precision)

            result = api_client.create_order(pair, quantity, price_rounded, 'sell')

            if result.get('result'):
                self.logger.info(f"✅ ПИРАМИДАЛЬНАЯ ПРОДАЖА ИСПОЛНЕНА!")
                self.logger.info(f"   Ордер ID: {result.get('order_id', 'N/A')}")

                # Обновляем время последней продажи
                self.last_sell_time = time.time()

                return True
            else:
                self.logger.error(f"❌ Ошибка пирамидальной продажи: {result}")

        except Exception as e:
            self.logger.error(f"❌ Исключение при пирамидальной продаже: {e}")

        return False

    def get_pyramid_status(self, current_price: float, position_data: Dict[str, Any]) -> Dict[str, Any]:
        """📊 Статус пирамидальной стратегии"""

        try:
            analysis = self.analyze_sell_opportunity(current_price, position_data)

            status = {
                'strategy': 'smart_pyramid',
                'current_price': current_price,
                'can_sell_now': analysis.get('should_sell', False),
                'cooldown_remaining': self._get_remaining_cooldown(),
                'levels_status': []
            }

            if analysis.get('should_sell'):
                status['ready_level'] = analysis['level']
                status['sell_quantity'] = analysis['sell_quantity']
                status['expected_profit'] = analysis['total_profit']
                status['reason'] = analysis.get('reason', 'Готов к продаже')
            else:
                status['reason'] = analysis.get('reason', 'Нет возможности продажи')
                if 'next_target' in analysis:
                    status['next_target'] = analysis['next_target']

            # Статус каждого уровня пирамиды
            purchase_levels = self._get_purchase_levels()

            if purchase_levels:
                for level in self.pyramid_levels:
                    level_analysis = self._analyze_pyramid_level(
                        current_price, purchase_levels, level, position_data.get('quantity', 0)
                    )

                    status['levels_status'].append({
                        'name': level['name'],
                        'target_multiplier': level['price_multiplier'],
                        'target_price_range': f"{min(p['price'] * level['price_multiplier'] for p in purchase_levels):.6f}",
                        'can_sell': level_analysis.get('can_sell', False),
                        'potential_profit': level_analysis.get('total_profit', 0),
                        'sell_percent': level['sell_percent']
                    })

            return status

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения статуса пирамиды: {e}")
            return {
                'strategy': 'smart_pyramid',
                'error': str(e),
                'can_sell_now': False
            }
