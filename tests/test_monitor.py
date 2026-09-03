from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from edgecraft.monitor import build_monitor_decision
from edgecraft.paper_fund import (
    AssetClass,
    FundHypothesis,
    FundPosition,
    FundQuote,
    FundState,
    HypothesisStance,
    OrderSide,
)

NOW = datetime(2026, 9, 1, 15, tzinfo=UTC)  # 11:00 ET, market open


def test_code_only_monitor_emits_full_stop_exit() -> None:
    state = FundState(
        fund_id="fund",
        as_of=NOW - timedelta(hours=1),
        cash=Decimal("500"),
        positions=(
            FundPosition(
                instrument_id="AAPL",
                asset_class=AssetClass.STOCK,
                quantity="5",
                average_entry="100",
                mark_price="100",
                market_value="500",
                unrealized_pnl="0",
            ),
        ),
        nav="1000",
        peak_nav="1000",
        drawdown="0",
        gross_exposure="500",
        net_exposure="500",
        short_exposure="0",
    )
    hypothesis = FundHypothesis(
        instrument_id="AAPL",
        stance=HypothesisStance.LONG,
        statement="drift",
        mechanism="earnings surprise",
        catalysts=("follow-through",),
        falsifiers=("below 95",),
        expected_horizon_hours=24,
        confidence="0.6",
        p_win="0.6",
        target_price="110",
        invalidation_price="95",
        playbook_id="post_earnings_drift",
        driver="earnings",
        evidence_ids=("old",),
    )
    quote = FundQuote(
        quote_id="code-aapl",
        instrument_id="AAPL",
        asset_class=AssetClass.STOCK,
        price="94",
        observed_at=NOW,
        source_timestamp=NOW,
        source_name="code feed",
        source_url="https://example.test/aapl",
    )
    decision, queued = build_monitor_decision(
        fund_id="fund",
        state=state,
        hypotheses=(hypothesis,),
        hypothesis_started_at={"AAPL": NOW - timedelta(hours=1)},
        quotes=(quote,),
        as_of=NOW,
    )
    assert queued == []
    assert decision.orders[0].side is OrderSide.SELL
    assert decision.orders[0].quantity == Decimal("5")
    assert decision.orders[0].extra_slippage_bps == Decimal("20")
    assert decision.journal is not None
    assert decision.journal.hypotheses[0].stance is HypothesisStance.EXIT
