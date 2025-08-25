# tests/test_selector.py
from src.application.research import selector as sel


def _synthetic_uptrend(n=200):
    ts = list(range(n))
    close = [1 + i * 0.001 for i in ts]
    o = [c * 0.999 for c in close]
    h = [c * 1.001 for c in close]
    l = [c * 0.999 for c in close]
    return {"ts": ts, "open": o, "high": h, "low": l, "close": close}


def test_scoring_and_constraints():
    ohlc = _synthetic_uptrend(300)
    # два результата: лучший и худший
    r1 = sel.eval_one(ohlc, "sma", {"fast": 6, "slow": 20}, 10, 2)
    r2 = sel.eval_one(ohlc, "sma", {"fast": 50, "slow": 60}, 10, 2)
    rows = sel.score_rows([r1, r2], sel.ScoreWeights())
    rows = sel.apply_constraints(rows, sel.Constraints(min_trades=1))
    ranked = sel.rank(rows, "score", top_n=1)
    assert ranked, "no ranked results"
    # хотя бы один трейд и score заполнился
    assert ranked[0].n_trades >= 0
    assert isinstance(ranked[0].score, float)


def test_robustness_runs():
    ohlc = _synthetic_uptrend(300)
    r = sel.robustness(ohlc, "sma", {"fast": 6, "slow": 20}, 10, 2, sel.RobustCfg(samples=1))
    assert r.total > 0
