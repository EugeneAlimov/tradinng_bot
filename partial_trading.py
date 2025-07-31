"""
🎯 Система частичной торговли по слоям
Решает проблему высокой средней цены при усреднении
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

@dataclass
class TradingLayer:
    """📊 Торговый слой"""
    trades: List[Dict]
    avg_price: float
    total_quantity: float
    age_hours: float
    can_sell: bool
    profit_percent: float
    layer_id: int

class PartialTradingStrategy:
    """🧠 Стратегия частичной торговли"""

    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Настройки из конфига
        self.min_layer_profit = getattr(config, 'PARTIAL_MIN_LAYER_PROFIT', 0.012)
        self.max_hold_days = getattr(config, 'PARTIAL_MAX_HOLD_DAYS', 7) 
        self.layer_tolerance = getattr(config, 'PARTIAL_LAYER_TOLERANCE', 0.02)
        self.min_sell_quantity = 5.0  # Минимум для EXMO

    def analyze_trading_layers(self, trades: List[Dict], current_price: float) -> List[TradingLayer]:
        """📊 Разделение на торговые слои"""
        if not trades:
            return []

        # Фильтруем только покупки и сортируем по времени
        buy_trades = [t for t in trades if t.get('side') == 'buy' or t.get('type') == 'buy']
        if not buy_trades:
            return []

        buy_trades.sort(key=lambda x: x['date'], reverse=True)

        layers = []
        current_layer = []
        layer_id = 1

        for trade in buy_trades:
            if not current_layer:
                current_layer = [trade]
                continue

            # Проверяем совместимость с текущим слоем
            layer_avg = sum(float(t['price']) for t in current_layer) / len(current_layer)
            trade_price = float(trade['price'])
            price_diff = abs(trade_price - layer_avg) / layer_avg

            # Разница во времени
            time_diff = abs((current_layer[0]['date'] - trade['date']).days)

            # Если цены и время близки - добавляем в слой
            if price_diff <= self.layer_tolerance and time_diff <= 2:
                current_layer.append(trade)
            else:
                # Создаем слой и начинаем новый
                if current_layer:
                    layer = self._create_layer(current_layer, current_price, layer_id)
                    layers.append(layer)
                    layer_id += 1
                current_layer = [trade]

        # Добавляем последний слой
        if current_layer:
            layer = self._create_layer(current_layer, current_price, layer_id)
            layers.append(layer)

        return layers

    def _create_layer(self, trades: List[Dict], current_price: float, layer_id: int) -> TradingLayer:
        """🏗️ Создание торгового слоя"""

        # Рассчитываем параметры слоя
        total_quantity = sum(float(t['quantity']) for t in trades)
        total_cost = sum(float(t['quantity']) * float(t['price']) for t in trades)
        avg_price = total_cost / total_quantity if total_quantity > 0 else 0

        # Возраст слоя (по самой старой сделке)
        oldest_trade = min(trades, key=lambda x: x['date'])
        age_hours = (datetime.now() - oldest_trade['date']).total_seconds() / 3600

        # Прибыльность слоя
        profit_percent = ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else -100

        # Решение о продаже
        can_sell = self._should_sell_layer(profit_percent, age_hours, total_quantity)

        return TradingLayer(
            trades=trades,
            avg_price=avg_price,
            total_quantity=total_quantity,
            age_hours=age_hours,
            can_sell=can_sell,
            profit_percent=profit_percent,
            layer_id=layer_id
        )

    def _should_sell_layer(self, profit_percent: float, age_hours: float, quantity: float) -> bool:
        """🎯 Решение о продаже слоя"""

        # Недостаточно для продажи
        if quantity < self.min_sell_quantity:
            return False

        # Есть достаточная прибыль
        if profit_percent >= (self.min_layer_profit * 100):
            return True

        # Слой слишком старый (принудительная продажа)
        if age_hours >= (self.max_hold_days * 24):
            return True

        # Небольшая прибыль, но слой довольно старый
        if profit_percent >= 0.5 and age_hours >= 48:  # 2 дня
            return True

        return False

    def should_sell_partial(self, position_data: Dict, current_price: float) -> Dict:
        """💰 Анализ частичной продажи"""
        try:
            trades = position_data.get('trades', [])
            if not trades:
                return {'action': 'hold', 'reason': 'Нет истории сделок'}

            # Анализируем слои
            layers = self.analyze_trading_layers(trades, current_price)
            if not layers:
                return {'action': 'hold', 'reason': 'Не удалось создать слои'}

            # Находим слои для продажи
            sellable_layers = [layer for layer in layers if layer.can_sell]

            if not sellable_layers:
                oldest_layer = max(layers, key=lambda x: x.age_hours)
                return {
                    'action': 'hold', 
                    'reason': f'Нет прибыльных слоев. Старейший: {oldest_layer.age_hours:.1f}ч ({oldest_layer.profit_percent:+.1f}%)'
                }

            # Рассчитываем общее количество для продажи
            total_sellable = sum(layer.total_quantity for layer in sellable_layers)

            if total_sellable < self.min_sell_quantity:
                return {
                    'action': 'hold',
                    'reason': f'Недостаточно для продажи: {total_sellable:.2f} < {self.min_sell_quantity}'
                }

            # Логируем анализ слоев
            self._log_layers_analysis(layers, current_price)

            # Формируем причины продажи
            reasons = []
            for layer in sellable_layers:
                if layer.profit_percent >= (self.min_layer_profit * 100):
                    reason = f"прибыль {layer.profit_percent:+.1f}%"
                elif layer.age_hours >= (self.max_hold_days * 24):
                    reason = f"возраст {layer.age_hours/24:.1f} дн"
                else:
                    reason = f"старый+прибыль {layer.profit_percent:+.1f}%"

                reasons.append(f"Слой{layer.layer_id}: {layer.total_quantity:.1f} ({reason})")

            return {
                'action': 'partial_sell',
                'quantity': total_sellable,
                'layers_count': len(sellable_layers),
                'total_layers': len(layers),
                'avg_profit': sum(l.profit_percent for l in sellable_layers) / len(sellable_layers),
                'reason': '; '.join(reasons)
            }

        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа слоев: {e}")
            return {'action': 'hold', 'reason': f'Ошибка: {str(e)}'}

    def _log_layers_analysis(self, layers: List[TradingLayer], current_price: float):
        """📊 Логирование анализа слоев"""

        self.logger.info("📊 АНАЛИЗ ТОРГОВЫХ СЛОЕВ:")
        self.logger.info(f"   💰 Текущая цена: {current_price:.6f}")
        self.logger.info(f"   📋 Всего слоев: {len(layers)}")

        total_quantity = sum(layer.total_quantity for layer in layers)
        weighted_avg = sum(layer.avg_price * layer.total_quantity for layer in layers) / total_quantity

        self.logger.info(f"   ⚖️ Общий объем: {total_quantity:.2f}")
        self.logger.info(f"   💲 Средневзвешенная: {weighted_avg:.6f}")
        self.logger.info(f"   📈 Общий P&L: {((current_price - weighted_avg) / weighted_avg * 100):+.1f}%")

        for layer in layers:
            status = "✅ ПРОДАЕМ" if layer.can_sell else "❌ ДЕРЖИМ"
            self.logger.info(f"   Слой {layer.layer_id}: {layer.total_quantity:.1f} по {layer.avg_price:.6f} "
                           f"({layer.profit_percent:+.1f}%, {layer.age_hours:.1f}ч) {status}")

    def calculate_layer_targets(self, layers: List[TradingLayer]) -> Dict:
        """🎯 Целевые цены для слоев"""
        targets = {}

        for layer in layers:
            target_price = layer.avg_price * (1 + self.min_layer_profit)
            targets[f'layer_{layer.layer_id}'] = {
                'current_price': layer.avg_price,
                'target_price': target_price,
                'quantity': layer.total_quantity,
                'current_profit': layer.profit_percent,
                'needed_profit': (self.min_layer_profit * 100) - layer.profit_percent,
                'age_hours': layer.age_hours,
                'can_sell_now': layer.can_sell
            }

        return targets

    def get_strategy_stats(self, trades: List[Dict], current_price: float) -> Dict:
        """📊 Статистика стратегии"""
        try:
            layers = self.analyze_trading_layers(trades, current_price)
            if not layers:
                return {'status': 'no_data'}

            sellable = [l for l in layers if l.can_sell]

            return {
                'total_layers': len(layers),
                'sellable_layers': len(sellable),
                'total_quantity': sum(l.total_quantity for l in layers),
                'sellable_quantity': sum(l.total_quantity for l in sellable),
                'avg_age_hours': sum(l.age_hours for l in layers) / len(layers),
                'avg_profit_percent': sum(l.profit_percent for l in layers) / len(layers),
                'best_layer_profit': max(l.profit_percent for l in layers) if layers else 0,
                'worst_layer_profit': min(l.profit_percent for l in layers) if layers else 0
            }

        except Exception as e:
            return {'status': 'error', 'error': str(e)}

# Интеграция с основным ботом
def integrate_partial_trading(bot_instance):
    """🔗 Интеграция в основной бот"""

    if not getattr(bot_instance.config, 'ENABLE_PARTIAL_TRADING', False):
        return lambda decision, *args: decision  # Возвращаем оригинальное решение

    bot_instance.partial_strategy = PartialTradingStrategy(bot_instance.config)

    def enhanced_sell_decision(original_decision, position_data, current_price):
        """🎯 Улучшенное решение о продаже"""

        # Сначала проверяем частичную продажу
        partial_analysis = bot_instance.partial_strategy.should_sell_partial(
            position_data, current_price
        )

        if partial_analysis['action'] == 'partial_sell':
            bot_instance.logger.info(f"🎯 ЧАСТИЧНАЯ ПРОДАЖА РЕКОМЕНДОВАНА:")
            bot_instance.logger.info(f"   📊 {partial_analysis['reason']}")
            return partial_analysis

        # Если частичная продажа не нужна, возвращаем оригинальное решение
        return original_decision

    return enhanced_sell_decision

if __name__ == "__main__":
    # Тестирование
    from datetime import datetime, timedelta

    print("🎯 ТЕСТ ЧАСТИЧНОЙ ТОРГОВЛИ")
    print("=" * 40)

    # Создаем тестовую конфигурацию
    class TestConfig:
        PARTIAL_MIN_LAYER_PROFIT = 0.012
        PARTIAL_MAX_HOLD_DAYS = 7
        PARTIAL_LAYER_TOLERANCE = 0.02

    strategy = PartialTradingStrategy(TestConfig())

    # Тестовые данные
    test_trades = [
        {
            'date': datetime.now() - timedelta(days=6),
            'side': 'buy',
            'price': '0.200',
            'quantity': '10'
        },
        {
            'date': datetime.now() - timedelta(days=3),
            'side': 'buy', 
            'price': '0.195',
            'quantity': '10'
        },
        {
            'date': datetime.now() - timedelta(hours=4),
            'side': 'buy',
            'price': '0.190',
            'quantity': '10'
        }
    ]

    test_position = {'trades': test_trades}
    current_price = 0.193

    # Анализируем
    analysis = strategy.should_sell_partial(test_position, current_price)

    print(f"Решение: {analysis['action']}")
    print(f"Причина: {analysis.get('reason', 'N/A')}")

    if analysis['action'] == 'partial_sell':
        print(f"Количество: {analysis.get('quantity', 0):.2f}")
        print(f"Слоев для продажи: {analysis.get('layers_count', 0)}")

    # Статистика
    stats = strategy.get_strategy_stats(test_trades, current_price)
    print(f"\nСтатистика:")
    print(f"Всего слоев: {stats.get('total_layers', 0)}")
    print(f"К продаже: {stats.get('sellable_layers', 0)}")
    print(f"Средняя прибыль: {stats.get('avg_profit_percent', 0):+.1f}%")
