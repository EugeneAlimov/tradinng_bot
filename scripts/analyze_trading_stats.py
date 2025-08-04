#!/usr/bin/env python3
"""📊 Анализ торговой статистики"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
import argparse

def load_trading_data(days=30):
    """Загрузка данных торговли"""
    data_dir = Path("data")
    trades_file = data_dir / "trades.json"
    
    if not trades_file.exists():
        print("❌ Файл с данными торговли не найден")
        # Создаем пример данных для демонстрации
        sample_trades = generate_sample_trades(days)
        return sample_trades
    
    with open(trades_file, "r") as f:
        trades = json.load(f)
    
    # Фильтруем по дням
    cutoff_date = datetime.now() - timedelta(days=days)
    filtered_trades = [
        trade for trade in trades
        if datetime.fromisoformat(trade["timestamp"]) >= cutoff_date
    ]
    
    return filtered_trades

def generate_sample_trades(days):
    """Генерация примера данных"""
    import random
    trades = []
    
    for i in range(days * 2):  # 2 сделки в день в среднем
        trade_time = datetime.now() - timedelta(days=days-i//2, hours=random.randint(0, 23))
        trades.append({
            "trade_id": f"sample_{i}",
            "pair": "DOGE_EUR",
            "type": "buy" if i % 2 == 0 else "sell",
            "amount": float(Decimal(str(100 + random.randint(-20, 50)))),
            "price": float(Decimal("0.18") + Decimal(str(random.uniform(-0.02, 0.02)))),
            "pnl": random.uniform(-5, 8),
            "timestamp": trade_time.isoformat()
        })
    
    return trades

def calculate_statistics(trades):
    """Расчет статистики"""
    if not trades:
        return {}
    
    total_trades = len(trades)
    profitable_trades = len([t for t in trades if float(t.get("pnl", 0)) > 0])
    win_rate = profitable_trades / total_trades if total_trades > 0 else 0
    
    # PnL статистика
    pnls = [float(t.get("pnl", 0)) for t in trades]
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(pnls) if pnls else 0
    
    # Максимальные значения
    max_profit = max(pnls) if pnls else 0
    max_loss = min(pnls) if pnls else 0
    
    return {
        "total_trades": total_trades,
        "profitable_trades": profitable_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
        "max_profit": max_profit,
        "max_loss": max_loss
    }

def generate_report(stats, days):
    """Генерация текстового отчета"""
    report = f"""
📊 ОТЧЕТ ПО ТОРГОВЛЕ (за последние {days} дней)
{'='*50}

📈 Общая статистика:
  • Всего сделок: {stats['total_trades']}
  • Прибыльных сделок: {stats['profitable_trades']}
  • Винрейт: {stats['win_rate']:.1%}

💰 Финансовые показатели:
  • Общий PnL: {stats['total_pnl']:.2f} EUR
  • Средний PnL за сделку: {stats['avg_pnl']:.2f} EUR
  • Максимальная прибыль: {stats['max_profit']:.2f} EUR
  • Максимальный убыток: {stats['max_loss']:.2f} EUR

📊 Оценка производительности:
"""
    
    # Добавляем оценки
    if stats['win_rate'] >= 0.6:
        report += "  ✅ Отличный винрейт (>60%)\n"
    elif stats['win_rate'] >= 0.5:
        report += "  ⚠️ Приемлемый винрейт (50-60%)\n"
    else:
        report += "  ❌ Низкий винрейт (<50%)\n"
    
    if stats['total_pnl'] > 0:
        report += "  ✅ Положительная доходность\n"
    else:
        report += "  ❌ Отрицательная доходность\n"
    
    return report

def main():
    parser = argparse.ArgumentParser(description="Анализ торговой статистики")
    parser.add_argument("--days", type=int, default=30, help="Количество дней для анализа")
    parser.add_argument("--output", default="reports", help="Директория для сохранения")
    
    args = parser.parse_args()
    
    print(f"📊 Анализ торговли за последние {args.days} дней...")
    
    # Загружаем данные
    trades = load_trading_data(args.days)
    if not trades:
        print("❌ Нет данных для анализа")
        return 1
    
    # Рассчитываем статистику
    stats = calculate_statistics(trades)
    
    # Генерируем отчет
    report = generate_report(stats, args.days)
    print(report)
    
    # Сохраняем отчет
    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True)
    
    with open(output_dir / f"trading_report_{datetime.now().strftime('%Y%m%d')}.txt", "w") as f:
        f.write(report)
    
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
