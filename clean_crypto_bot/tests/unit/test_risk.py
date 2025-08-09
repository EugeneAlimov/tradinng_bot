
from decimal import Decimal
from src.domain.risk.risk_service import RiskService
from src.config.settings import RiskCfg

def test_risk_sizing():
    r = RiskService(RiskCfg(position_size_usd=Decimal("50"), max_daily_loss=0.03))
    out = r.size({"last_price": Decimal("0.1")})
    assert out["allow"] is True
    assert out["qty"] == Decimal("500.000000")
