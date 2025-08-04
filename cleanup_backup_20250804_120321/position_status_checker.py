#!/usr/bin/env python3
"""📊 Скрипт проверки текущего состояния позиции"""

import os
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional

def load_position_data() -> Dict[str, Any]:
    """📂 Загрузка данных позиции из файла"""
    
    positions_file = 'data/positions.json'
    
    if not os.path.exists(positions_file):
        print("❌ Файл позиций не найден!")
        return {}
    
    try:
        with open(positions_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('positions', {})
    except Exception as e:
        print(f"❌ Ошибка загрузки позиций: {e}")
        return {}

def get_current_market_price() -> float:
    """💱 Получение текущей рыночной цены (упрощенная версия)"""
    
    try:
        # Импортируем API клиент
        from api_client import ExmoAPIClient
        from config import TradingConfig
        
        config = TradingConfig()
        api = ExmoAPIClient(config.API_KEY, config.API_SECRET)
        
        ticker_data = api.get_ticker()
        pair = f"{config.CURRENCY_1}_{config.CURRENCY_2}"
        
        if ticker_data and pair in ticker_data:
            return float(ticker_data[pair]['last_trade'])
        
        print("⚠️ Не удалось получить цену через API")
        return 0.0
        
    except Exception as e:
        print(f"⚠️ Ошибка получения цены: {e}")
        return 0.0

def get_current_balance() -> Dict[str, float]:
    """💰 Получение текущих балансов"""
    
    try:
        from api_client import ExmoAPIClient
        from config import TradingConfig
        
        config = TradingConfig()
        api = ExmoAPIClient(config.API_KEY, config.API_SECRET)
        
        user_info = api.get_user_info()
        
        if user_info and 'balances' in user_info:
            balances = user_info['balances']
            return {
                'DOGE': float(balances.get('DOGE', 0)),
                'EUR': float(balances.get('EUR', 0))
            }
        
        print("⚠️ Не удалось получить балансы")
        return {'DOGE': 0.0, 'EUR': 0.0}
        
    except Exception as e:
        print(f"⚠️ Ошибка получения балансов: {e}")
        return {'DOGE': 0.0, 'EUR': 0.0}

def analyze_position_status():
    """📊 Основной анализ состояния позиции"""
    
    print("📊 АНАЛИЗ ТЕКУЩЕГО СОСТОЯНИЯ ПОЗИЦИИ")
    print("=" * 60)
    
    # 1. Загружаем данные позиции из файла
    print("📂 Загрузка данных позиции...")
    positions = load_position_data()
    
    if not positions:
        print("❌ Данные позиций отсутствуют")
        return
    
    doge_position = positions.get('DOGE', {})
    
    if not doge_position or doge_position.get('quantity', 0) == 0:
        print("📊 Позиция по DOGE отсутствует")
        return
    
    # 2. Получаем текущую рыночную цену
    print("💱 Получение текущей цены...")
    current_price = get_current_market_price()
    
    # 3. Получаем реальные балансы
    print("💰 Получение текущих балансов...")
    balances = get_current_balance()
    
    # 4. Анализируем позицию
    print("\n📊 ДЕТАЛЬНЫЙ АНАЛИЗ ПОЗИЦИИ:")
    print("-" * 50)
    
    # Данные из файла позиций
    calculated_quantity = doge_position.get('quantity', 0)
    avg_price = doge_position.get('avg_price', 0)
    total_cost = doge_position.get('total_cost', 0)
    
    # Реальные данные
    real_doge_balance = balances['DOGE']
    real_eur_balance = balances['EUR']
    
    print(f"💼 РАССЧИТАННАЯ ПОЗИЦИЯ:")
    print(f"   Количество DOGE: {calculated_quantity:.6f}")
    print(f"   Средняя цена: {avg_price:.8f} EUR")
    print(f"   Общая стоимость: {total_cost:.4f} EUR")
    
    print(f"\n💰 РЕАЛЬНЫЕ БАЛАНСЫ:")
    print(f"   DOGE баланс: {real_doge_balance:.6f}")
    print(f"   EUR баланс: {real_eur_balance:.4f}")
    
    print(f"\n💱 РЫНОЧНЫЕ ДАННЫЕ:")
    if current_price > 0:
        print(f"   Текущая цена: {current_price:.8f} EUR")
    else:
        print(f"   Текущая цена: Не удалось получить")
        current_price = avg_price  # Fallback
    
    # 5. Расчет прибыли/убытка
    if avg_price > 0 and current_price > 0:
        print(f"\n📈 АНАЛИЗ ПРИБЫЛИ/УБЫТКА:")
        print("-" * 40)
        
        # По рассчитанной позиции
        calculated_value = calculated_quantity * current_price
        calculated_pnl = calculated_value - total_cost
        calculated_pnl_percent = (calculated_pnl / total_cost) * 100 if total_cost > 0 else 0
        
        print(f"📊 По рассчитанной позиции:")
        print(f"   Текущая стоимость: {calculated_value:.4f} EUR")
        print(f"   P&L: {calculated_pnl:+.4f} EUR ({calculated_pnl_percent:+.2f}%)")
        
        # По реальному балансу
        real_value = real_doge_balance * current_price
        
        print(f"\n💰 По реальному балансу:")
        print(f"   Стоимость DOGE: {real_value:.4f} EUR")
        print(f"   Общий баланс: {real_eur_balance + real_value:.4f} EUR")
        
        # Расхождение
        balance_diff = abs(calculated_quantity - real_doge_balance)
        if balance_diff > 0.001:  # Если расхождение больше 0.001 DOGE
            print(f"\n⚠️ РАСХОЖДЕНИЕ ДАННЫХ:")
            print(f"   Разница в количестве: {balance_diff:.6f} DOGE")
            print(f"   Разница в EUR: {balance_diff * current_price:.4f} EUR")
        else:
            print(f"\n✅ Данные синхронизированы (расхождение < 0.001 DOGE)")
    
    # 6. Анализ истории сделок
    trades_history = doge_position.get('trades', [])
    if trades_history:
        print(f"\n📋 ИСТОРИЯ СДЕЛОК:")
        print("-" * 40)
        print(f"   Всего сделок: {len(trades_history)}")
        
        # Последние 5 сделок
        recent_trades = trades_history[-5:]
        print(f"   Последние сделки:")
        
        for i, trade in enumerate(recent_trades[-3:], 1):  # Показываем последние 3
            trade_type = trade.get('type', 'unknown')
            quantity = trade.get('quantity', 0)
            price = trade.get('price', 0)
            timestamp = trade.get('timestamp', 0)
            
            if timestamp:
                date_str = datetime.fromtimestamp(timestamp).strftime('%d.%m %H:%M')
            else:
                date_str = 'N/A'
            
            emoji = '🛒' if trade_type == 'buy' else '💎'
            print(f"   {emoji} {date_str}: {trade_type.upper()} {quantity:.6f} по {price:.8f}")
    
    # 7. Рекомендации
    print(f"\n🎯 РЕКОМЕНДАЦИИ:")
    print("-" * 40)
    
    if current_price > 0 and avg_price > 0:
        profit_percent = (current_price - avg_price) / avg_price * 100
        
        if profit_percent > 2:
            print(f"🎯 Хорошая прибыль {profit_percent:+.1f}% - можно частично продавать")
        elif profit_percent > 0:
            print(f"📊 Небольшая прибыль {profit_percent:+.1f}% - ждать лучших уровней")
        elif profit_percent > -5:
            print(f"⚖️ Небольшой убыток {profit_percent:+.1f}% - ждать восстановления")
        else:
            print(f"⚠️ Значительный убыток {profit_percent:+.1f}% - следить за стоп-лоссом")
    
    if balance_diff > 0.001:
        print(f"🔧 Рекомендуется синхронизация данных позиций")
    
    print(f"📊 Проверьте логи бота на предмет ошибок ценообразования")

def create_position_summary_json():
    """💾 Создание JSON файла с сводкой позиции"""
    
    try:
        positions = load_position_data()
        balances = get_current_balance()
        current_price = get_current_market_price()
        
        doge_position = positions.get('DOGE', {})
        
        summary = {
            'timestamp': datetime.now().isoformat(),
            'position_data': {
                'calculated_quantity': doge_position.get('quantity', 0),
                'avg_price': doge_position.get('avg_price', 0),
                'total_cost': doge_position.get('total_cost', 0)
            },
            'real_balances': balances,
            'market_data': {
                'current_price': current_price,
                'last_updated': datetime.now().isoformat()
            },
            'analysis': {
                'balance_discrepancy': abs(doge_position.get('quantity', 0) - balances['DOGE']),
                'current_value': balances['DOGE'] * current_price if current_price > 0 else 0,
                'total_portfolio_value': balances['EUR'] + (balances['DOGE'] * current_price) if current_price > 0 else balances['EUR']
            }
        }
        
        # Рассчитываем P&L если возможно
        if current_price > 0 and doge_position.get('total_cost', 0) > 0:
            current_value = doge_position.get('quantity', 0) * current_price
            pnl = current_value - doge_position.get('total_cost', 0)
            pnl_percent = (pnl / doge_position.get('total_cost', 0)) * 100
            
            summary['analysis']['pnl_eur'] = pnl
            summary['analysis']['pnl_percent'] = pnl_percent
        
        # Сохраняем сводку
        summary_file = f"position_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Сводка сохранена в: {summary_file}")
        
    except Exception as e:
        print(f"❌ Ошибка создания сводки: {e}")

if __name__ == "__main__":
    print("📊 ПРОВЕРКА СОСТОЯНИЯ ПОЗИЦИИ ТОРГОВОГО БОТА")
    print("=" * 60)
    print("🔍 Анализируем текущую ситуацию...")
    print()
    
    try:
        analyze_position_status()
        
        print("\n💾 Создать детальную JSON сводку? (y/n): ", end="")
        response = input().lower().strip()
        
        if response in ['y', 'yes', 'да']:
            create_position_summary_json()
        
        print("\n✅ Анализ завершен!")
        
    except KeyboardInterrupt:
        print("\n⌨️ Анализ прерван пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка анализа: {e}")
        print("💡 Убедитесь что файлы конфигурации и API ключи настроены корректно")
