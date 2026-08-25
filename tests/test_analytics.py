from edgecraft.analytics import market_diagnostics
from edgecraft.data import synthetic_market_data


def test_market_diagnostics_are_finite():
    data = synthetic_market_data(["AAA", "SPY"], periods=400)
    market = market_diagnostics(data, benchmark="SPY")
    assert market["sessions"] == 400
    assert market["assets"]["AAA"]["realized_volatility_20d"] > 0
    assert -1 <= market["assets"]["AAA"]["correlation_to_benchmark_252d"] <= 1
