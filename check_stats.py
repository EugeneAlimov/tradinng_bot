import json
import os
from datetime import datetime


def check_current_stats():
    today = datetime.now().strftime('%Y%m%d')
    stats_file = f'data/analytics/runtime_stats_{today}.json'

    if not os.path.exists(stats_file):
        print("📊 Статистика еще не собрана")
        return

    print("📊 ТЕКУЩАЯ СТАТИСТИКА:")
    print("=" * 40)

    with open(stats_file, 'r') as f:
        lines = f.readlines()

    if lines:
        # Берем последнюю запись
        latest = json.loads(lines[-1])

        print(f"⏱️ Время работы: {latest.get('uptime_hours', 0):.1f} часов")
        print(f"🔄 Циклов: {latest.get('cycles_completed', 0)}")
        print(f"📈 Сделок: {latest.get('total_trades', 0)}")
        print(f"💰 Прибыльных: {latest.get('profitable_trades', 0)}")
        print(f"💸 Дневной P&L: {latest.get('daily_pnl', 0):+.4f} EUR")
        print(f"❌ Ошибок: {latest.get('error_count', 0)}")
        print(f"⚡ Среднее время цикла: {latest.get('avg_cycle_time', 0):.2f}с")

        if latest.get('total_trades', 0) > 0:
            win_rate = (latest.get('profitable_trades', 0) / latest.get('total_trades', 1)) * 100
            print(f"✅ Успешность: {win_rate:.1f}%")

        # Позиции
        positions = latest.get('positions', {})
        if positions:
            print(f"\n💎 ПОЗИЦИИ:")
            for currency, pos_data in positions.items():
                print(f"   {currency}: {pos_data.get('quantity', 0):.6f} по {pos_data.get('avg_price', 0):.6f}")

    print(f"\n📝 Всего записей статистики: {len(lines)}")


if __name__ == "__main__":
    check_current_stats()