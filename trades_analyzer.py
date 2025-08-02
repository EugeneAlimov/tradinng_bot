#!/usr/bin/env python3
"""📊 Анализатор истории сделок из JSON файлов"""

import json
import os
import glob
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging


@dataclass
class TradeProfitAnalysis:
    """💰 Анализ прибыльности сделок"""
    total_profit: float
    profitable_trades: int
    losing_trades: int
    success_rate: float
    avg_profit_per_trade: float
    best_trade: float
    worst_trade: float


class TradesAnalyzer:
    """📊 Анализатор истории сделок"""
    
    def __init__(self):
        self.setup_logging()
        self.logger.info("📊 TradesAnalyzer инициализирован")
    
    def setup_logging(self):
        """📝 Настройка логирования"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def load_trades_from_json(self, filename: str) -> List[Dict[str, Any]]:
        """📂 Загрузка сделок из JSON файла"""
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'trades' in data:
                trades = data['trades']
            elif isinstance(data, list):
                trades = data
            else:
                self.logger.error(f"❌ Неожиданная структура файла: {filename}")
                return []
            
            self.logger.info(f"📂 Загружено {len(trades)} сделок из {filename}")
            return trades
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки {filename}: {e}")
            return []
    
    def find_latest_trades_file(self, directory: str = 'data') -> Optional[str]:
        """🔍 Поиск последнего файла с историей сделок"""
        
        pattern = os.path.join(directory, 'trades_history_*.json')
        files = glob.glob(pattern)
        
        if not files:
            self.logger.warning("⚠️ Файлы с историей сделок не найдены")
            return None
        
        # Сортируем по дате создания
        latest_file = max(files, key=os.path.getctime)
        self.logger.info(f"🔍 Найден последний файл: {latest_file}")
        
        return latest_file
    
    def analyze_profit_loss(self, trades: List[Dict[str, Any]]) -> TradeProfitAnalysis:
        """💰 Анализ прибыли и убытков"""
        
        if not trades:
            return TradeProfitAnalysis(0, 0, 0, 0, 0, 0, 0)
        
        # Группируем сделки по покупкам и продажам
        buys = [t for t in trades if t.get('type') == 'buy']
        sells = [t for t in trades if t.get('type') == 'sell']
        
        # Простой анализ - сравниваем средние цены
        if not buys or not sells:
            self.logger.warning("⚠️ Недостаточно данных для анализа P&L")
            return TradeProfitAnalysis(0, 0, 0, 0, 0, 0, 0)
        
        # Рассчитываем средние цены
        avg_buy_price = sum(float(t.get('price', 0)) for t in buys) / len(buys)
        avg_sell_price = sum(float(t.get('price', 0)) for t in sells) / len(sells)
        
        # Общие объемы
        total_buy_volume = sum(float(t.get('quantity', 0)) for t in buys)
        total_sell_volume = sum(float(t.get('quantity', 0)) for t in sells)
        
        # Упрощенный расчет прибыли
        min_volume = min(total_buy_volume, total_sell_volume)
        profit = min_volume * (avg_sell_price - avg_buy_price)
        
        # Анализ отдельных сделок (упрощенный)
        profitable = sum(1 for t in sells if float(t.get('price', 0)) > avg_buy_price)
        losing = len(sells) - profitable
        
        return TradeProfitAnalysis(
            total_profit=profit,
            profitable_trades=profitable,
            losing_trades=losing,
            success_rate=(profitable / len(sells) * 100) if sells else 0,
            avg_profit_per_trade=profit / len(sells) if sells else 0,
            best_trade=max(float(t.get('price', 0)) - avg_buy_price for t in sells) * max(float(t.get('quantity', 0)) for t in sells),
            worst_trade=min(float(t.get('price', 0)) - avg_buy_price for t in sells) * min(float(t.get('quantity', 0)) for t in sells)
        )
    
    def analyze_time_patterns(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """⏰ Анализ временных паттернов"""
        
        if not trades:
            return {}
        
        # Анализ по часам
        hourly_activity = {}
        daily_activity = {}
        monthly_activity = {}
        
        for trade in trades:
            try:
                # Парсим дату
                date_str = trade.get('date', '')
                date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00').replace(' ', 'T'))
                
                # По часам
                hour = date_obj.hour
                hourly_activity[hour] = hourly_activity.get(hour, 0) + 1
                
                # По дням недели
                weekday = date_obj.strftime('%A')
                daily_activity[weekday] = daily_activity.get(weekday, 0) + 1
                
                # По месяцам
                month = date_obj.strftime('%Y-%m')
                monthly_activity[month] = monthly_activity.get(month, 0) + 1
                
            except Exception as e:
                self.logger.debug(f"Ошибка парсинга даты {date_str}: {e}")
                continue
        
        return {
            'hourly_activity': hourly_activity,
            'daily_activity': daily_activity,
            'monthly_activity': monthly_activity,
            'most_active_hour': max(hourly_activity.items(), key=lambda x: x[1]) if hourly_activity else None,
            'most_active_day': max(daily_activity.items(), key=lambda x: x[1]) if daily_activity else None
        }
    
    def analyze_price_movements(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """📈 Анализ движения цен"""
        
        if not trades:
            return {}
        
        prices = [float(trade.get('price', 0)) for trade in trades if trade.get('price')]
        
        if not prices:
            return {}
        
        # Сортируем сделки по времени
        sorted_trades = sorted(trades, key=lambda t: t.get('timestamp', 0))
        sorted_prices = [float(t.get('price', 0)) for t in sorted_trades if t.get('price')]
        
        # Рассчитываем изменения цены
        price_changes = []
        for i in range(1, len(sorted_prices)):
            change = (sorted_prices[i] - sorted_prices[i-1]) / sorted_prices[i-1] * 100
            price_changes.append(change)
        
        return {
            'min_price': min(prices),
            'max_price': max(prices),
            'avg_price': sum(prices) / len(prices),
            'price_range': max(prices) - min(prices),
            'volatility': sum(abs(change) for change in price_changes) / len(price_changes) if price_changes else 0,
            'total_price_change': ((sorted_prices[-1] - sorted_prices[0]) / sorted_prices[0] * 100) if len(sorted_prices) > 1 else 0,
            'biggest_price_jump': max(price_changes) if price_changes else 0,
            'biggest_price_drop': min(price_changes) if price_changes else 0
        }
    
    def create_detailed_report(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """📋 Создание детального отчета"""
        
        if not trades:
            return {'error': 'Нет данных для анализа'}
        
        # Базовая статистика
        buys = [t for t in trades if t.get('type') == 'buy']
        sells = [t for t in trades if t.get('type') == 'sell']
        
        # Анализы
        profit_analysis = self.analyze_profit_loss(trades)
        time_patterns = self.analyze_time_patterns(trades)
        price_movements = self.analyze_price_movements(trades)
        
        # Комиссии
        total_commission = sum(float(t.get('commission', 0)) for t in trades)
        
        report = {
            'analysis_date': datetime.now().isoformat(),
            'data_summary': {
                'total_trades': len(trades),
                'buy_trades': len(buys),
                'sell_trades': len(sells),
                'date_range': {
                    'first_trade': min(trades, key=lambda t: t.get('timestamp', 0)).get('date') if trades else None,
                    'last_trade': max(trades, key=lambda t: t.get('timestamp', 0)).get('date') if trades else None
                }
            },
            'volume_analysis': {
                'total_crypto_volume': sum(float(t.get('quantity', 0)) for t in trades),
                'total_fiat_volume': sum(float(t.get('amount', 0)) for t in trades),
                'buy_volume': sum(float(t.get('quantity', 0)) for t in buys),
                'sell_volume': sum(float(t.get('quantity', 0)) for t in sells),
                'avg_trade_size': sum(float(t.get('quantity', 0)) for t in trades) / len(trades)
            },
            'profit_analysis': {
                'estimated_profit_eur': profit_analysis.total_profit,
                'profitable_trades': profit_analysis.profitable_trades,
                'losing_trades': profit_analysis.losing_trades,
                'success_rate_percent': profit_analysis.success_rate,
                'avg_profit_per_trade': profit_analysis.avg_profit_per_trade,
                'best_trade_profit': profit_analysis.best_trade,
                'worst_trade_loss': profit_analysis.worst_trade
            },
            'cost_analysis': {
                'total_commission': total_commission,
                'avg_commission_per_trade': total_commission / len(trades),
                'commission_as_percent_of_volume': (total_commission / sum(float(t.get('amount', 0)) for t in trades) * 100) if trades else 0
            },
            'price_analysis': price_movements,
            'time_patterns': time_patterns,
            'trading_frequency': {
                'avg_trades_per_day': len(trades) / max(1, len(time_patterns.get('daily_activity', {}))),
                'most_active_period': time_patterns.get('most_active_hour'),
                'most_active_day': time_patterns.get('most_active_day')
            }
        }
        
        return report
    
    def save_analysis_report(self, report: Dict[str, Any], filename: str = None) -> str:
        """💾 Сохранение отчета анализа"""
        
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"data/trades_analysis_{timestamp}.json"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"💾 Отчет анализа сохранен: {filename}")
            return filename
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения отчета: {e}")
            return None
    
    def print_summary_report(self, report: Dict[str, Any]):
        """📋 Вывод краткого отчета в консоль"""
        
        if 'error' in report:
            print(f"❌ {report['error']}")
            return
        
        print("\n📊 КРАТКИЙ ОТЧЕТ ПО СДЕЛКАМ")
        print("=" * 50)
        
        # Основные данные
        data = report['data_summary']
        print(f"📈 Всего сделок: {data['total_trades']}")
        print(f"🛒 Покупок: {data['buy_trades']}")
        print(f"💎 Продаж: {data['sell_trades']}")
        
        if data['date_range']['first_trade'] and data['date_range']['last_trade']:
            print(f"📅 Период: {data['date_range']['first_trade']} - {data['date_range']['last_trade']}")
        
        # Объемы
        volumes = report['volume_analysis']
        print(f"\n💰 ОБЪЕМЫ:")
        print(f"   Крипто: {volumes['total_crypto_volume']:.2f}")
        print(f"   Фиат: {volumes['total_fiat_volume']:.2f} EUR")
        print(f"   Средний размер сделки: {volumes['avg_trade_size']:.2f}")
        
        # Прибыльность
        profit = report['profit_analysis']
        print(f"\n📈 ПРИБЫЛЬНОСТЬ:")
        print(f"   Расчетная прибыль: {profit['estimated_profit_eur']:.2f} EUR")
        print(f"   Успешных сделок: {profit['profitable_trades']}")
        print(f"   Убыточных сделок: {profit['losing_trades']}")
        print(f"   Процент успешности: {profit['success_rate_percent']:.1f}%")
        
        # Затраты
        costs = report['cost_analysis']
        print(f"\n💸 ЗАТРАТЫ:")
        print(f"   Общие комиссии: {costs['total_commission']:.4f} EUR")
        print(f"   Средняя комиссия: {costs['avg_commission_per_trade']:.4f} EUR")
        print(f"   Комиссии от оборота: {costs['commission_as_percent_of_volume']:.3f}%")
        
        # Цены
        prices = report['price_analysis']
        if prices:
            print(f"\n📊 ЦЕНЫ:")
            print(f"   Диапазон: {prices['min_price']:.8f} - {prices['max_price']:.8f}")
            print(f"   Средняя цена: {prices['avg_price']:.8f}")
            print(f"   Волатильность: {prices['volatility']:.2f}%")
            print(f"   Общее изменение: {prices['total_price_change']:.2f}%")
        
        # Временные паттерны
        time_patterns = report['time_patterns']
        if time_patterns.get('most_active_hour'):
            hour, count = time_patterns['most_active_hour']
            print(f"\n⏰ АКТИВНОСТЬ:")
            print(f"   Самый активный час: {hour}:00 ({count} сделок)")
        
        if time_patterns.get('most_active_day'):
            day, count = time_patterns['most_active_day']
            print(f"   Самый активный день: {day} ({count} сделок)")
        
        # Частота торговли
        frequency = report['trading_frequency']
        print(f"   Среднее сделок в день: {frequency['avg_trades_per_day']:.1f}")


def main():
    """🚀 Основная функция анализа"""
    
    print("📊 АНАЛИЗАТОР ИСТОРИИ СДЕЛОК")
    print("=" * 40)
    
    try:
        analyzer = TradesAnalyzer()
        
        # Ищем файл для анализа
        print("🔍 Поиск файлов с историей сделок...")
        
        # Пользователь может указать файл или мы найдем последний
        custom_file = input("📁 Путь к JSON файлу (Enter для автопоиска): ").strip()
        
        if custom_file and os.path.exists(custom_file):
            json_file = custom_file
        else:
            json_file = analyzer.find_latest_trades_file()
            
            if not json_file:
                print("❌ Файлы с историей сделок не найдены")
                print("💡 Сначала запустите trades_history_fetcher.py")
                return
        
        print(f"📂 Анализируем файл: {json_file}")
        
        # Загружаем данные
        trades = analyzer.load_trades_from_json(json_file)
        
        if not trades:
            print("❌ Не удалось загрузить сделки")
            return
        
        print(f"✅ Загружено {len(trades)} сделок")
        
        # Проводим анализ
        print("🔄 Проведение анализа...")
        report = analyzer.create_detailed_report(trades)
        
        # Показываем краткий отчет
        analyzer.print_summary_report(report)
        
        # Сохраняем детальный отчет
        report_file = analyzer.save_analysis_report(report)
        
        if report_file:
            print(f"\n💾 Детальный отчет сохранен: {report_file}")
        
        # Дополнительные опции
        print(f"\n🎯 ДОПОЛНИТЕЛЬНЫЕ ОПЦИИ:")
        print(f"1. Экспорт в CSV для Excel")
        print(f"2. Анализ конкретного периода")
        print(f"3. Поиск лучших/худших сделок")
        
        choice = input("\nВыберите опцию (1-3, Enter для завершения): ").strip()
        
        if choice == "1":
            # Экспорт в CSV
            try:
                import csv
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                csv_filename = f"data/trades_analysis_summary_{timestamp}.csv"
                
                with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    
                    # Заголовки
                    writer.writerow(['Метрика', 'Значение'])
                    
                    # Основные данные
                    data = report['data_summary']
                    writer.writerow(['Всего сделок', data['total_trades']])
                    writer.writerow(['Покупок', data['buy_trades']])
                    writer.writerow(['Продаж', data['sell_trades']])
                    
                    # Объемы
                    volumes = report['volume_analysis']
                    writer.writerow(['Общий объем крипто', f"{volumes['total_crypto_volume']:.2f}"])
                    writer.writerow(['Общий объем фиат', f"{volumes['total_fiat_volume']:.2f} EUR"])
                    
                    # Прибыльность
                    profit = report['profit_analysis']
                    writer.writerow(['Расчетная прибыль', f"{profit['estimated_profit_eur']:.2f} EUR"])
                    writer.writerow(['Процент успешности', f"{profit['success_rate_percent']:.1f}%"])
                    
                    # Затраты
                    costs = report['cost_analysis']
                    writer.writerow(['Общие комиссии', f"{costs['total_commission']:.4f} EUR"])
                
                print(f"📊 CSV отчет сохранен: {csv_filename}")
                
            except ImportError:
                print("⚠️ CSV модуль недоступен")
            except Exception as e:
                print(f"❌ Ошибка создания CSV: {e}")
        
        elif choice == "2":
            # Анализ периода
            print("📅 Анализ конкретного периода:")
            try:
                days_back = int(input("Количество дней назад (например, 7): ") or "7")
                cutoff_date = datetime.now() - timedelta(days=days_back)
                
                recent_trades = [
                    t for t in trades 
                    if datetime.fromtimestamp(t.get('timestamp', 0)) >= cutoff_date
                ]
                
                if recent_trades:
                    print(f"\n📊 Анализ за последние {days_back} дней:")
                    period_report = analyzer.create_detailed_report(recent_trades)
                    analyzer.print_summary_report(period_report)
                else:
                    print(f"❌ Нет сделок за последние {days_back} дней")
                    
            except ValueError:
                print("❌ Некорректное число дней")
        
        elif choice == "3":
            # Лучшие/худшие сделки
            print("🎯 Поиск экстремальных сделок:")
            
            # Сортируем по цене
            sorted_by_price = sorted(trades, key=lambda t: float(t.get('price', 0)))
            
            print(f"\n💎 Самая дорогая сделка:")
            expensive = sorted_by_price[-1]
            print(f"   Цена: {expensive.get('price')} | Дата: {expensive.get('date')} | Тип: {expensive.get('type')}")
            
            print(f"\n🛒 Самая дешевая сделка:")
            cheap = sorted_by_price[0]
            print(f"   Цена: {cheap.get('price')} | Дата: {cheap.get('date')} | Тип: {cheap.get('type')}")
            
            # Сортируем по объему
            sorted_by_volume = sorted(trades, key=lambda t: float(t.get('quantity', 0)))
            
            print(f"\n📈 Самая крупная сделка:")
            largest = sorted_by_volume[-1]
            print(f"   Объем: {largest.get('quantity')} | Цена: {largest.get('price')} | Дата: {largest.get('date')}")
        
        print(f"\n✅ Анализ завершен!")
        
    except KeyboardInterrupt:
        print("\n⌨️ Анализ отменен пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        logging.exception("Детали ошибки:")


if __name__ == "__main__":
    main()