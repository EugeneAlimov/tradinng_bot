# tools/optimize_sma.py
import itertools
import json
from datetime import datetime
from typing import Dict, Any, Tuple

# Импорты под ваш проект:
# from src.application.engine.trade_engine import Backtester
# from src.domain.strategy.sma_crossover import run_backtest_sma
# Замените на реальные вызовы вашего бэктеста

def run_sma_backtest(fast:int, slow:int, fee_bps:int, slip_bps:int, candles:Any) -> Dict[str,Any]:
    """
    Должен вернуть метрики: end, total_pnl, trades, win_rate, profit_factor, max_drawdown, sharpe
    Адаптируйте тело под ваши функции.
    """
    # примерная схема:
    # report = run_backtest_sma(candles, fast=fast, slow=slow, fee_bps=fee_bps, slip_bps=slip_bps)
    # return report["metrics"]
    raise NotImplementedError

def grid_search(candles, fee_bps:int, slip_bps:int):
    grid = [(f,s) for f in range(5,21,1) for s in range(20,81,5) if f < s]
    best = []
    for fast, slow in grid:
        m = run_sma_backtest(fast, slow, fee_bps, slip_bps, candles)
        best.append({
            "fast": fast, "slow": slow,
            "sharpe": m.get("sharpe", 0.0),
            "pf": m.get("profit_factor", 0.0),
            "trades": m.get("trades", 0),
            "dd": m.get("max_drawdown", 0.0),
            "end": m.get("end", 0.0),
        })
    # Сортируем по качеству (сначала Sharpe, потом PF, затем меньший DD)
    best.sort(key=lambda r: (r["sharpe"], r["pf"], -r["dd"]), reverse=True)
    return best[:20]

def main():
    # 1) Загрузите свечи так же, как вы это делаете в main.py
    # candles = load_exmo_candles(...); resample(...)
    candles = None  # TODO: заменить
    fee_bps = 10
    slip_bps = 2

    top = grid_search(candles, fee_bps, slip_bps)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out = f"data/sma_grid_{ts}.json"
    with open(out, "w") as f:
        json.dump(top, f, indent=2)
    print(f"→ saved: {out}")

if __name__ == "__main__":
    main()
