from datetime import UTC, datetime

from edgecraft.data import synthetic_market_data
from edgecraft.intelligence import build_market_intelligence


def test_market_intelligence_is_complete_ranked_and_content_addressed():
    data = synthetic_market_data(["AAA", "BBB", "SPY"], periods=500, seed=11)
    collected_at = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)

    first = build_market_intelligence(data, benchmark="SPY", collected_at=collected_at)
    second = build_market_intelligence(data, benchmark="SPY", collected_at=collected_at)

    assert first.history_sessions == 500
    assert set(first.assets) == {"AAA", "BBB", "SPY"}
    assert first.last_completed_session == data["SPY"].index[-1].date()
    assert first.input_sha256 == second.input_sha256
    assert len(first.input_sha256) == 64
    assert {first.assets["AAA"].cross_sectional_rank, first.assets["BBB"].cross_sectional_rank} == {
        1,
        2,
    }
    assert 0 <= first.regime.universe_breadth_above_sma_50 <= 1
    assert first.assets["SPY"].correlation_to_benchmark_252d == 1
    assert first.assets["AAA"].average_daily_dollar_volume_20d > 0
