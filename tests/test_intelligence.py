from datetime import UTC, datetime

import pandas as pd
import pytest

from edgecraft.data import MarketDataError, MarketDataProvider, synthetic_market_data
from edgecraft.intelligence import (
    INTELLIGENCE_DOWNLOAD_TIMEOUT_SECONDS,
    INTELLIGENCE_RETRY_DELAYS_SECONDS,
    YahooMarketIntelligenceCollector,
    build_market_intelligence,
)


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
    assert first.assets["SPY"].cross_sectional_rank == 3
    assert 0 <= first.regime.universe_breadth_above_sma_50 <= 1
    assert first.assets["SPY"].correlation_to_benchmark_252d == 1
    assert first.assets["AAA"].average_daily_dollar_volume_20d > 0
    assert first.warnings == []


def test_market_intelligence_drops_short_history_symbols_without_collapsing_universe():
    data = synthetic_market_data(["AAA", "BBB", "SPY"], periods=500, seed=11)
    # Recent IPO-style series: only the last 80 sessions exist.
    data["NEW"] = data["AAA"].iloc[-80:].copy()
    collected_at = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)

    snapshot = build_market_intelligence(data, benchmark="SPY", collected_at=collected_at)

    assert "NEW" not in snapshot.assets
    assert set(snapshot.assets) == {"AAA", "BBB", "SPY"}
    assert snapshot.history_sessions == 500
    assert any(warning.startswith("NEW:") for warning in snapshot.warnings)


def test_yahoo_collector_default_provider_is_fast_fail():
    collector = YahooMarketIntelligenceCollector()

    assert collector.data_provider.retry_delays_seconds == INTELLIGENCE_RETRY_DELAYS_SECONDS
    assert collector.data_provider.retry_delays_seconds == ()
    assert collector.data_provider.download_timeout == INTELLIGENCE_DOWNLOAD_TIMEOUT_SECONDS
    assert collector.data_provider.download_timeout == 8.0


def test_yahoo_collector_preserves_injected_provider():
    provider = MarketDataProvider(
        retry_delays_seconds=(0.5, 1.5, 3.0),
        download_timeout=20.0,
    )
    collector = YahooMarketIntelligenceCollector(data_provider=provider)

    assert collector.data_provider is provider
    assert collector.data_provider.retry_delays_seconds == (0.5, 1.5, 3.0)
    assert collector.data_provider.download_timeout == 20.0


def test_yahoo_collector_warns_on_missing_symbol_without_retrying(monkeypatch, tmp_path):
    data = synthetic_market_data(["AAA", "SPY"], periods=300, seed=11)
    load_calls: list[list[str]] = []

    class FakeProvider:
        def load(self, symbols, start, end, *, refresh=False):
            load_calls.append(list(symbols))
            symbol = symbols[0]
            if symbol == "MISSING":
                raise MarketDataError(f"{symbol}: no market data returned")
            return {symbol: data[symbol]}

    collector = YahooMarketIntelligenceCollector(data_provider=FakeProvider())
    snapshot = collector.collect(
        ["AAA", "MISSING"],
        benchmark="SPY",
        now=datetime(2026, 7, 20, 15, 0, tzinfo=UTC),
    )

    assert load_calls == [["AAA"], ["MISSING"], ["SPY"]]
    assert "MISSING" not in snapshot.assets
    assert set(snapshot.assets) == {"AAA", "SPY"}
    assert any(warning.startswith("MISSING:") for warning in snapshot.warnings)


def test_yahoo_collector_fail_closed_on_benchmark_load_error():
    data = synthetic_market_data(["AAA"], periods=300, seed=11)

    class FakeProvider:
        def load(self, symbols, start, end, *, refresh=False):
            symbol = symbols[0]
            if symbol == "SPY":
                raise MarketDataError("SPY: no market data returned")
            return {symbol: data[symbol]}

    collector = YahooMarketIntelligenceCollector(data_provider=FakeProvider())
    with pytest.raises(MarketDataError, match="SPY"):
        collector.collect(
            ["AAA"],
            benchmark="SPY",
            now=datetime(2026, 7, 20, 15, 0, tzinfo=UTC),
        )


def test_yahoo_collector_default_provider_single_attempt_on_empty(monkeypatch, tmp_path):
    calls = 0
    delays: list[float] = []
    timeouts: list[float] = []

    def fake_download(*args, **kwargs):
        nonlocal calls
        calls += 1
        timeouts.append(kwargs["timeout"])
        return pd.DataFrame()

    monkeypatch.setattr("edgecraft.data.yf.download", fake_download)
    monkeypatch.setattr("edgecraft.data.time.sleep", delays.append)
    monkeypatch.setattr(
        "edgecraft.intelligence.MarketDataProvider",
        lambda **kwargs: MarketDataProvider(cache_dir=tmp_path, **kwargs),
    )

    collector = YahooMarketIntelligenceCollector()
    with pytest.raises(MarketDataError, match="no market data returned"):
        collector.collect(
            ["MISSING"],
            benchmark="SPY",
            now=datetime(2026, 7, 20, 15, 0, tzinfo=UTC),
        )

    # One attempt per symbol: MISSING warns, then SPY fails closed.
    assert calls == 2
    assert timeouts == [8.0, 8.0]
    assert delays == []
