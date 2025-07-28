import json
import pandas as pd
import os
from datetime import datetime
from analytics_system import TradingAnalytics


def export_analytics_to_csv(data_dir: str = 'data', output_file: str = None):
    """📤 Экспорт аналитики в CSV для Excel"""
    analytics = TradingAnalytics(data_dir)

    try:
        # Анализируем сделки
        analysis = analytics.analyze_trades_performance(30)  # За месяц

        if not analysis.get('detailed_trades'):
            print("📝 Нет данных для экспорта")
            return None

        # Создаем DataFrame
        df = pd.DataFrame(analysis['detailed_trades'])

        # Добавляем полезные колонки
        df['profitable'] = df['profit_percent'] > 0
        df['entry_date'] = pd.to_datetime(df['entry_time']).dt.date
        df['entry_hour'] = pd.to_datetime(df['entry_time']).dt.hour
        df['hold_days'] = df['hold_time_hours'] / 24

        # Сохраняем
        if output_file is None:
            output_file = f"data/analytics_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        df.to_csv(output_file, index=False, encoding='utf-8')
        print(f"📤 Данные экспортированы в {output_file}")

        # Краткая сводка
        print(f"📊 Экспортировано {len(df)} сделок")
        print(f"💰 Общая прибыль: {df['net_profit'].sum():.4f} EUR")
        print(f"✅ Успешных: {df['profitable'].sum()}/{len(df)} ({df['profitable'].mean() * 100:.1f}%)")

        return output_file

    except Exception as e:
        print(f"❌ Ошибка экспорта: {e}")
        return None


def export_all_data():
    print("📤 ЭКСПОРТ ДАННЫХ:")
    print("=" * 30)

    # 1. Экспорт сделок в CSV
    csv_file = export_analytics_to_csv()
    if csv_file:
        print(f"✅ Сделки экспортированы: {csv_file}")

    # 2. Экспорт статистики
    today = datetime.now().strftime('%Y%m%d')
    stats_file = f'data/analytics/runtime_stats_{today}.json'

    if os.path.exists(stats_file):
        # Читаем JSON и конвертируем в CSV
        stats_data = []
        with open(stats_file, 'r') as f:
            for line in f:
                try:
                    stats_data.append(json.loads(line.strip()))
                except:
                    continue

        if stats_data:
            df = pd.DataFrame(stats_data)
            stats_csv = f'data/stats_export_{today}.csv'
            df.to_csv(stats_csv, index=False)
            print(f"✅ Статистика экспортирована: {stats_csv}")
        else:
            print("📝 Нет данных статистики для экспорта")
    else:
        print("📝 Файл статистики не найден")


if __name__ == "__main__":
    export_all_data()
