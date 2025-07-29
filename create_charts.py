from analytics_system import TradingAnalytics


def create_charts_now():
    analytics = TradingAnalytics()

    print("📊 Создание графиков...")

    try:
        analytics.create_performance_charts(days_back=7)
        print("✅ Графики созданы в data/charts/")

        # Показываем что создалось
        import os
        charts_dir = 'data/charts'
        if os.path.exists(charts_dir):
            files = [f for f in os.listdir(charts_dir) if f.endswith('.png')]
            print(f"📊 Файлы графиков: {files}")
    except Exception as e:
        print(f"❌ Ошибка создания графиков: {e}")


if __name__ == "__main__":
    create_charts_now()