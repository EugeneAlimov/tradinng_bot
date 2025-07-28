# check_position_accuracy.py - Диагностика точности данных

from config import TradingConfig
from api_client import ExmoAPIClient
from position_manager import PositionManager
import json

def diagnose_position_issues():
    """🔍 Диагностика проблем с позициями"""
    print("🔍 ДИАГНОСТИКА ПОЗИЦИЙ")
    print("=" * 50)

    config = TradingConfig()
    api = ExmoAPIClient(config)
    position_manager = PositionManager(config, api)

    try:
        # 1. Проверяем API данные
        print("📊 1. ДАННЫЕ ИЗ API:")
        user_info = api.get_user_info()
        api_balance = float(user_info['balances'].get(config.CURRENCY_1, 0))
        print(f"   API баланс DOGE: {api_balance:.6f}")

        # 2. Проверяем расчетную позицию
        print("\n🧮 2. РАСЧЕТНАЯ ПОЗИЦИЯ:")
        position = position_manager.get_position(config.CURRENCY_1)
        if position:
            print(f"   Количество: {position.quantity:.6f}")
            print(f"   Средняя цена: {position.avg_price:.8f}")
            print(f"   Общая стоимость: {position.total_cost:.4f} EUR")
            print(f"   Последнее обновление: {position.last_updated}")
            print(f"   Количество сделок: {len(position.trades)}")
        else:
            print("   Позиция не найдена")

        # 3. Анализируем расхождение
        print("\n⚖️  3. АНАЛИЗ РАСХОЖДЕНИЯ:")
        if position:
            discrepancy = abs(api_balance - position.quantity)
            discrepancy_percent = (discrepancy / api_balance * 100) if api_balance > 0 else 0

            print(f"   Абсолютное расхождение: {discrepancy:.6f} DOGE")
            print(f"   Процентное расхождение: {discrepancy_percent:.2f}%")

            if discrepancy_percent < 1:
                print("   ✅ Расхождение в норме")
            elif discrepancy_percent < 5:
                print("   ⚠️  Умеренное расхождение")
            else:
                print("   🚨 Критическое расхождение")

        # 4. Проверяем последние сделки
        print("\n📋 4. ПОСЛЕДНИЕ СДЕЛКИ:")
        try:
            pair = f"{config.CURRENCY_1}_{config.CURRENCY_2}"
            trades = api.get_user_trades(pair=pair, limit=10)

            if trades and pair in trades:
                trade_list = trades[pair]
                print(f"   Найдено {len(trade_list)} последних сделок:")

                for i, trade in enumerate(trade_list[:5], 1):
                    trade_time = trade.get('date', 'N/A')
                    trade_type = trade.get('type', 'N/A')
                    trade_qty = trade.get('quantity', 'N/A')
                    trade_price = trade.get('price', 'N/A')
                    commission = trade.get('commission_amount', 'N/A')

                    print(f"   {i}. {trade_time}: {trade_type} {trade_qty} по {trade_price} (комиссия: {commission})")
            else:
                print("   Сделки не найдены")

        except Exception as e:
            print(f"   ❌ Ошибка получения сделок: {e}")

        # 5. Рекомендации
        print("\n💡 5. РЕКОМЕНДАЦИИ:")

        if position and api_balance > 0:
            discrepancy_percent = abs(api_balance - position.quantity) / api_balance * 100

            if discrepancy_percent > 5:
                print("   🔧 Рекомендуется принудительная синхронизация")
                print("   📝 Добавьте в код: position_manager.force_sync_with_real_balance()")

            if discrepancy_percent > 1:
                print("   📊 Рекомендуется использовать гибкий порог валидации")
                print("   ⚙️  Увеличьте MAX_POSITION_DISCREPANCY в config.py")

            if position.avg_price == 0:
                print("   💰 Средняя цена равна нулю - проблема в расчете FIFO")
                print("   🔧 Проверьте метод _calculate_position_fifo()")

        print("\n" + "=" * 50)
        print("✅ Диагностика завершена")

    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")

def fix_position_data():
    """🔧 Автоматическое исправление данных позиции"""
    print("\n🔧 АВТОМАТИЧЕСКОЕ ИСПРАВЛЕНИЕ")
    print("=" * 50)

    config = TradingConfig()
    api = ExmoAPIClient(config)
    position_manager = PositionManager(config, api)

    try:
        # Получаем реальный баланс
        user_info = api.get_user_info()
        real_balance = float(user_info['balances'].get(config.CURRENCY_1, 0))

        if real_balance > 0:
            print(f"📊 Реальный баланс: {real_balance:.6f} DOGE")

            # Принудительная синхронизация
            position_manager.force_sync_with_real_balance(real_balance)
            print("✅ Синхронизация выполнена")

            # Проверяем результат
            updated_position = position_manager.get_position(config.CURRENCY_1)
            if updated_position:
                print(f"📊 Обновленная позиция:")
                print(f"   Количество: {updated_position.quantity:.6f}")
                print(f"   Средняя цена: {updated_position.avg_price:.8f}")

                new_discrepancy = abs(real_balance - updated_position.quantity)
                print(f"   Новое расхождение: {new_discrepancy:.6f} DOGE")

                if new_discrepancy < 0.001:
                    print("   ✅ Данные синхронизированы успешно")
                else:
                    print("   ⚠️ Остается небольшое расхождение")
        else:
            print("📝 Нет позиции для исправления")

    except Exception as e:
        print(f"❌ Ошибка исправления: {e}")

if __name__ == "__main__":
    # Сначала диагностируем
    diagnose_position_issues()

    # Спрашиваем нужно ли исправлять
    response = input("\n🤔 Выполнить автоматическое исправление? (y/n): ")
    if response.lower() in ['y', 'yes', 'да', 'д']:
        fix_position_data()
    else:
        print("💭 Исправление пропущено")
