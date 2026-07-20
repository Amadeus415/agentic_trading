from edgecraft.analytics import market_diagnostics, portfolio_market_risk
from edgecraft.data import synthetic_market_data
from edgecraft.execution_models import PortfolioSnapshot, PositionSnapshot


def test_market_and_portfolio_risk_diagnostics_are_finite():
    data = synthetic_market_data(["AAA", "SPY"], periods=400)
    market = market_diagnostics(data, benchmark="SPY")
    assert market["sessions"] == 400
    assert market["assets"]["AAA"]["realized_volatility_20d"] > 0
    assert -1 <= market["assets"]["AAA"]["correlation_to_benchmark_252d"] <= 1

    snapshot = PortfolioSnapshot(
        account_id="agentic-test",
        agentic_allowed=True,
        buying_power=200,
        portfolio_value=500,
        as_of="2026-07-19T18:00:00Z",
        positions=[PositionSnapshot(symbol="AAA", quantity=3, market_price=100, average_cost=90)],
    )
    risk = portfolio_market_risk(snapshot, data, benchmark="SPY")
    assert risk["annualized_volatility"] > 0
    assert risk["historical_var_95_one_day"] > 0
    assert risk["component_variance_share"]["AAA"] == 1
