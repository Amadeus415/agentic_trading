import pandas as pd

from edgecraft.data import synthetic_market_data
from edgecraft.engine import BacktestEngine
from edgecraft.models import CostModel
from edgecraft.strategies import PlainDCA, TrendVolTarget, ValueTiltedDCA


def test_plain_dca_adds_contributions_and_generates_fills():
    data = synthetic_market_data(["AAA"], periods=180)
    result = BacktestEngine(CostModel(slippage_bps=0, spread_bps=0)).run(
        data,
        PlainDCA(),
        initial_capital=1_000,
        contribution_amount=100,
        contribution_frequency="monthly",
    )
    assert result.metrics["fills"] >= 8
    assert result.daily["contribution"].sum() >= 700
    assert result.daily["equity"].iloc[-1] > 0
    assert result.fills[0].date > result.daily.index[0]


def test_future_mutation_cannot_change_prior_results():
    original = synthetic_market_data(["AAA"], periods=500)
    altered = {"AAA": original["AAA"].copy()}
    cutoff = altered["AAA"].index[350]
    altered["AAA"].loc[altered["AAA"].index > cutoff, ["open", "high", "low", "close"]] *= 4
    engine = BacktestEngine(CostModel(slippage_bps=0, spread_bps=0))
    first = engine.run(
        original,
        TrendVolTarget(fast_window=20, slow_window=60),
        initial_capital=10_000,
        contribution_amount=0,
        contribution_frequency="monthly",
    )
    second = engine.run(
        altered,
        TrendVolTarget(fast_window=20, slow_window=60),
        initial_capital=10_000,
        contribution_amount=0,
        contribution_frequency="monthly",
    )
    pd.testing.assert_series_equal(
        first.daily.loc[:cutoff, "equity"], second.daily.loc[:cutoff, "equity"]
    )


def test_value_tilted_dca_forced_deadline_counts_sessions():
    data = synthetic_market_data(["AAA"], periods=80)
    result = BacktestEngine(CostModel(slippage_bps=0, spread_bps=0)).run(
        data,
        ValueTiltedDCA(drawdown_threshold=1, rsi_threshold=0, max_wait_sessions=5),
        initial_capital=1_000,
        contribution_amount=100,
        contribution_frequency="weekly",
    )
    fill_dates = [fill.date for fill in result.fills]
    assert len(fill_dates) >= 10
    gaps = [
        data["AAA"].index.get_loc(right) - data["AAA"].index.get_loc(left)
        for left, right in zip(fill_dates, fill_dates[1:], strict=False)
    ]
    # Five waiting sessions plus the next-open execution; the first calendar alignment can add two.
    assert max(gaps) <= 8
