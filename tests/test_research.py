from edgecraft.data import synthetic_market_data
from edgecraft.models import BacktestRequest, StrategySpec, ValidationConfig
from edgecraft.research import run_research


def test_research_matrix_serializes_metrics_and_validation():
    request = BacktestRequest(
        symbols=["AAA", "BBB"],
        strategies=[StrategySpec(name="plain_dca"), StrategySpec(name="mean_reversion")],
        validation=ValidationConfig(bootstrap_samples=20, bootstrap_block_size=10, cscv_slices=4),
    )
    payload = run_research(synthetic_market_data(request.symbols, periods=450), request)
    assert payload["meta"]["strategies_tested"] == 2
    assert len(payload["results"]) == 2
    assert payload["results"][0]["series"][-1]["equity"] > 0
    assert "probability_backtest_overfitting" in payload["validation"]
    assert "deflated_sharpe_probability" in payload["results"][0]["metrics"]
