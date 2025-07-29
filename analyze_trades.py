from analytics_system import TradingAnalytics


def quick_analysis():
    analytics = TradingAnalytics()

    print("🔍 АНАЛИЗ СДЕЛОК:")
    print("=" * 40)

    # Анализ за последние дни
    summary = analytics.get_summary_stats(days_back=7)

    if summary.get('trades_performance'):
        metrics = summary['trades_performance']
        print(f"💰 Общая прибыль: {metrics.get('total_net_profit', 0):.4f} EUR")
        print(f"📊 Успешность: {metrics.get('win_rate', 0):.1f}%")
        print(f"📈 Коэф. Шарпа: {metrics.get('sharpe_ratio', 0):.2f}")
        print(f"⚡ Средн. прибыль: {metrics.get('average_profit_per_trade', 0):.4f} EUR")
        print(f"🏆 Лучшая сделка: {metrics.get('max_profit', 0):.4f} EUR")
        print(f"📉 Худшая сделка: {metrics.get('max_loss', 0):.4f} EUR")
        print(f"⏰ Среднее время удержания: {metrics.get('average_hold_time_hours', 0):.1f} часов")
    else:
        print("📝 Пока нет завершенных сделок для анализа")

    # Рекомендации
    if summary.get('recommendations'):
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        for rec in summary['recommendations']:
            print(f"   {rec}")

    # Время торговли
    if summary.get('time_analysis'):
        time_analysis = summary['time_analysis']
        print(f"\n⏰ АНАЛИЗ ВРЕМЕНИ:")
        print(f"   🕐 Активные часы: {time_analysis.get('most_active_hours', [])}")
        print(f"   💰 Прибыльные часы: {time_analysis.get('most_profitable_hours', [])}")


if __name__ == "__main__":
    quick_analysis()