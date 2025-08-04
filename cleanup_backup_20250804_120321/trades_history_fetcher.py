#!/usr/bin/env python3
"""📊 Скрипт получения истории сделок с биржи EXMO"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Импорты из существующих модулей
try:
    from config import TradingConfig
    from api_client import ExmoAPIClient
    from rate_limiter import RateLimitedAPIClient, RateLimiter
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("💡 Убедитесь что файлы config.py, api_client.py и rate_limiter.py доступны")
    exit(1)


@dataclass
class TradeRecord:
    """📊 Запись о сделке"""
    trade_id: int
    order_id: int
    pair: str
    type: str  # 'buy' или 'sell'
    quantity: float
    price: float
    amount: float  # quantity * price
    commission: float
    commission_currency: str
    date: datetime
    date_string: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для JSON"""
        return {
            'trade_id': self.trade_id,
            'order_id': self.order_id,
            'pair': self.pair,
            'type': self.type,
            'quantity': self.quantity,
            'price': self.price,
            'amount': self.amount,
            'commission': self.commission,
            'commission_currency': self.commission_currency,
            'date': self.date_string,
            'timestamp': int(self.date.timestamp())
        }


class TradesHistoryFetcher:
    """📊 Получение истории сделок"""
    
    def __init__(self, config: TradingConfig = None):
        self.config = config or TradingConfig()
        self.setup_logging()
        
        # Инициализация API клиента с rate limiting
        api_client = ExmoAPIClient(self.config.API_KEY, self.config.API_SECRET)
        
        if getattr(self.config, 'RATE_LIMITER_ENABLED', True):
            rate_limiter = RateLimiter(30, 300)  # 30 вызовов/мин, 300/час
            self.api = RateLimitedAPIClient(api_client, rate_limiter)
            self.logger.info("⚡ Rate limiter активирован")
        else:
            self.api = api_client
        
        # Создаем директории
        os.makedirs('data', exist_ok=True)
        os.makedirs('logs', exist_ok=True)
        
        self.logger.info("📊 TradesHistoryFetcher инициализирован")
    
    def setup_logging(self):
        """📝 Настройка логирования"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/trades_fetcher.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def get_user_trades(self, pair: str = None, limit: int = 1000) -> List[TradeRecord]:
        """📊 Получение истории сделок пользователя"""
        
        if pair is None:
            pair = self.config.get_pair()
        
        self.logger.info(f"📊 Получение истории сделок для {pair} (лимит: {limit})")
        
        try:
            # Получаем данные через API
            if hasattr(self.api, 'get_user_trades'):
                response = self.api.get_user_trades(pair, limit)
            else:
                # Для простого API клиента
                response = self.api.get_trades(pair, limit)
            
            if not response:
                self.logger.warning("⚠️ Пустой ответ от API")
                return []
            
            trades = []
            
            # Парсим ответ в зависимости от структуры
            if isinstance(response, dict):
                if pair in response:
                    # Формат: {pair: [trades]}
                    raw_trades = response[pair]
                elif 'result' in response and response['result']:
                    # Формат: {result: True, data: [trades]}
                    raw_trades = response.get('data', response.get(pair, []))
                else:
                    # Прямой список сделок
                    raw_trades = response
            elif isinstance(response, list):
                raw_trades = response
            else:
                self.logger.error(f"❌ Неожиданный формат ответа: {type(response)}")
                return []
            
            if not raw_trades:
                self.logger.warning("⚠️ Нет сделок в ответе API")
                return []
            
            # Конвертируем каждую сделку
            for trade_data in raw_trades:
                try:
                    trade = self._parse_trade_data(trade_data, pair)
                    if trade:
                        trades.append(trade)
                except Exception as e:
                    self.logger.error(f"❌ Ошибка парсинга сделки: {e}")
                    self.logger.debug(f"Данные сделки: {trade_data}")
            
            self.logger.info(f"✅ Получено {len(trades)} сделок")
            return sorted(trades, key=lambda t: t.date, reverse=True)
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения истории сделок: {e}")
            return []
    
    def _parse_trade_data(self, trade_data: Dict[str, Any], pair: str) -> Optional[TradeRecord]:
        """🔍 Парсинг данных одной сделки"""
        
        try:
            # Разные возможные форматы времени
            date_value = trade_data.get('date', trade_data.get('timestamp', trade_data.get('time')))
            
            if isinstance(date_value, str):
                # Попробуем разные форматы даты
                for date_format in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f']:
                    try:
                        date = datetime.strptime(date_value, date_format)
                        break
                    except ValueError:
                        continue
                else:
                    # Если ни один формат не подошел
                    self.logger.warning(f"⚠️ Неизвестный формат даты: {date_value}")
                    date = datetime.now()
            elif isinstance(date_value, (int, float)):
                # Unix timestamp
                date = datetime.fromtimestamp(date_value)
            else:
                date = datetime.now()
            
            # Создаем запись о сделке
            trade = TradeRecord(
                trade_id=int(trade_data.get('trade_id', trade_data.get('id', 0))),
                order_id=int(trade_data.get('order_id', 0)),
                pair=pair,
                type=trade_data.get('type', 'unknown'),
                quantity=float(trade_data.get('quantity', trade_data.get('amount', 0))),
                price=float(trade_data.get('price', 0)),
                amount=float(trade_data.get('amount', trade_data.get('sum', 0))),
                commission=float(trade_data.get('commission', trade_data.get('fee', 0))),
                commission_currency=trade_data.get('commission_currency', 
                                                 trade_data.get('fee_currency', 'EUR')),
                date=date,
                date_string=date.strftime('%Y-%m-%d %H:%M:%S')
            )
            
            return trade
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка парсинга сделки: {e}")
            self.logger.debug(f"Проблемные данные: {trade_data}")
            return None
    
    def save_trades_to_json(self, trades: List[TradeRecord], filename: str = None) -> str:
        """💾 Сохранение сделок в JSON файл"""
        
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"data/trades_history_{timestamp}.json"
        
        try:
            # Подготавливаем данные для сохранения
            data = {
                'export_info': {
                    'timestamp': datetime.now().isoformat(),
                    'pair': self.config.get_pair(),
                    'total_trades': len(trades),
                    'date_range': {
                        'from': trades[-1].date_string if trades else None,
                        'to': trades[0].date_string if trades else None
                    },
                    'export_source': 'EXMO API',
                    'bot_version': 'DOGE Trading Bot v4.1'
                },
                'trades': [trade.to_dict() for trade in trades]
            }
            
            # Сохраняем в файл
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            file_size = os.path.getsize(filename) / 1024  # в KB
            self.logger.info(f"💾 История сделок сохранена в {filename}")
            self.logger.info(f"📊 Сделок: {len(trades)}, размер файла: {file_size:.1f} KB")
            
            return filename
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения в файл: {e}")
            return None
    
    def get_trades_statistics(self, trades: List[TradeRecord]) -> Dict[str, Any]:
        """📊 Статистика по сделкам"""
        
        if not trades:
            return {'error': 'Нет сделок для анализа'}
        
        # Разделяем покупки и продажи
        buys = [t for t in trades if t.type == 'buy']
        sells = [t for t in trades if t.type == 'sell']
        
        # Базовая статистика
        stats = {
            'summary': {
                'total_trades': len(trades),
                'buy_trades': len(buys),
                'sell_trades': len(sells),
                'date_range': {
                    'from': trades[-1].date_string if trades else None,
                    'to': trades[0].date_string if trades else None
                }
            },
            'volumes': {
                'total_volume_crypto': sum(t.quantity for t in trades),
                'total_volume_fiat': sum(t.amount for t in trades),
                'buy_volume_crypto': sum(t.quantity for t in buys),
                'sell_volume_crypto': sum(t.quantity for t in sells),
                'buy_volume_fiat': sum(t.amount for t in buys),
                'sell_volume_fiat': sum(t.amount for t in sells)
            },
            'prices': {
                'min_price': min(t.price for t in trades) if trades else 0,
                'max_price': max(t.price for t in trades) if trades else 0,
                'avg_price': sum(t.price for t in trades) / len(trades) if trades else 0,
                'avg_buy_price': sum(t.price for t in buys) / len(buys) if buys else 0,
                'avg_sell_price': sum(t.price for t in sells) / len(sells) if sells else 0
            },
            'commissions': {
                'total_commission': sum(t.commission for t in trades),
                'avg_commission': sum(t.commission for t in trades) / len(trades) if trades else 0
            }
        }
        
        return stats
    
    def export_trades_csv(self, trades: List[TradeRecord], filename: str = None) -> str:
        """📊 Экспорт в CSV для анализа"""
        
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"data/trades_export_{timestamp}.csv"
        
        try:
            import csv
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'Date', 'Type', 'Quantity', 'Price', 'Amount', 
                    'Commission', 'Trade_ID', 'Order_ID'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for trade in trades:
                    writer.writerow({
                        'Date': trade.date_string,
                        'Type': trade.type,
                        'Quantity': trade.quantity,
                        'Price': trade.price,
                        'Amount': trade.amount,
                        'Commission': trade.commission,
                        'Trade_ID': trade.trade_id,
                        'Order_ID': trade.order_id
                    })
            
            self.logger.info(f"📊 CSV экспорт сохранен: {filename}")
            return filename
            
        except ImportError:
            self.logger.warning("⚠️ CSV модуль недоступен, экспорт пропущен")
            return None
        except Exception as e:
            self.logger.error(f"❌ Ошибка CSV экспорта: {e}")
            return None

def main():
    """🚀 Основная функция"""
    
    print("📊 ПОЛУЧЕНИЕ ИСТОРИИ СДЕЛОК С EXMO")
    print("=" * 50)
    
    try:
        # Инициализация
        fetcher = TradesHistoryFetcher()
        
        # Проверяем настройки
        print(f"📍 Торговая пара: {fetcher.config.get_pair()}")
        print(f"🔑 API ключ: {fetcher.config.API_KEY[:8]}...")
        
        # Запрашиваем параметры
        try:
            limit = int(input("📊 Количество сделок для получения (по умолчанию 1000): ") or "1000")
        except ValueError:
            limit = 1000
        
        pair = input(f"💱 Торговая пара (по умолчанию {fetcher.config.get_pair()}): ") or fetcher.config.get_pair()
        
        print(f"\n🔄 Получение истории сделок...")
        print(f"   Пара: {pair}")
        print(f"   Лимит: {limit}")
        
        # Получаем сделки
        trades = fetcher.get_user_trades(pair, limit)
        
        if not trades:
            print("❌ Сделки не найдены или произошла ошибка")
            return
        
        print(f"✅ Получено {len(trades)} сделок")
        
        # Сохраняем в JSON
        json_file = fetcher.save_trades_to_json(trades)
        if json_file:
            print(f"💾 JSON файл: {json_file}")
        
        # Экспортируем в CSV
        csv_file = fetcher.export_trades_csv(trades)
        if csv_file:
            print(f"📊 CSV файл: {csv_file}")
        
        # Показываем статистику
        print(f"\n📊 СТАТИСТИКА:")
        stats = fetcher.get_trades_statistics(trades)
        
        if 'error' not in stats:
            print(f"   📈 Всего сделок: {stats['summary']['total_trades']}")
            print(f"   🛒 Покупок: {stats['summary']['buy_trades']}")
            print(f"   💎 Продаж: {stats['summary']['sell_trades']}")
            print(f"   💰 Общий объем: {stats['volumes']['total_volume_fiat']:.2f} EUR")
            print(f"   📊 Средняя цена: {stats['prices']['avg_price']:.8f}")
            print(f"   💸 Комиссии: {stats['commissions']['total_commission']:.4f}")
            
            if stats['summary']['buy_trades'] > 0:
                print(f"   🛒 Средняя цена покупки: {stats['prices']['avg_buy_price']:.8f}")
            
            if stats['summary']['sell_trades'] > 0:
                print(f"   💎 Средняя цена продажи: {stats['prices']['avg_sell_price']:.8f}")
        
        print(f"\n✅ Экспорт завершен успешно!")
        
    except KeyboardInterrupt:
        print("\n⌨️ Отменено пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        logging.exception("Детали ошибки:")

if __name__ == "__main__":
    main()