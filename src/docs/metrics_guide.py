# -*- coding: utf-8 -*-
"""
Mini guide on metrics that appear in sweep/rank/optimize artifacts.
Importable and printable (no external files).
"""
GUIDE = """
METRICS GUIDE
=============

bars                      : количество баров в тестируемом периоде
trades                    : всего сделок
winrate_pct               : процент прибыльных сделок (0..100)
total_return_pct          : совокупная доходность портфеля, %
max_drawdown_pct          : максимальная просадка по equity, %
final_equity_eur          : конечный капитал (в EUR)
start_equity_eur          : стартовый капитал (в EUR)
profit_factor             : отношение суммарной прибыли к суммарным убыткам (>1 лучше)
avg_trade_eur             : средняя PnL сделки в EUR
exposure_pct              : средняя доля времени в позиции (%)
sharpe                    : условный Sharpe (зависит от реализации в vectorized_bt)
cagr_pct                  : годовая доходность, % (условная для intraday)
calmar                    : Calmar ratio (CAGR / |MaxDD|)
bars_per_year             : нормировочный коэффициент частоты баров
fast/slow                 : параметры "быстрой" и "медленной" компонент стратегии
hysteresis_bps            : гистерезис входа/выхода, б.п.
cooldown_bars             : количество баров "кулдауна" между сделками
qty_eur                   : размер сделки в EUR
fee_bps / slip_bps        : комиссия / проскальзывание, б.п.
max_daily_loss_bps        : дневной риск-лимит, б.п. (0 — выключено)

Примечание:
- интерпретация Sharpe/Calmar зависит от реализации модуля backtest,
  guide описывает смысл, а не точную формулу.
- sweep/optimize нормализуют метрики в примитивы (int/float/str) перед записью.
""".strip()


def print_guide():
    print(GUIDE)


if __name__ == "__main__":
    print_guide()
