# tests/test_risk_service.py
from src.domain.risk.risk_service import RiskService, RiskCfg, PositionSnapshot

def test_pre_trade_max_position_pct():
    rs = RiskService(RiskCfg(max_position_pct=0.1))
    ok, _ = rs.pre_trade_check(desired_qty=1.0, mark_price=90.0, equity=1000.0)  # 90 <= 100
    assert ok
    ok, _ = rs.pre_trade_check(desired_qty=2.0, mark_price=600.0, equity=1000.0)  # 1200 > 100
    assert not ok

def test_stop_price_long():
    rs = RiskService(RiskCfg(stop_loss_bps=500))  # 5%
    pos = PositionSnapshot(qty=10, avg_price=100.0, side="LONG", updated_at=None)
    assert rs.stop_price(pos) == 95.0
    assert rs.should_stop_out(pos, mark_price=94.9)

def test_daily_pnl_bps_accum():
    rs = RiskService(RiskCfg())
    rs.update_daily_pnl(pnl_abs=-30.0, equity_start_of_day=1000.0)
    assert rs.daily_pnl_bps == -300  # -3%
