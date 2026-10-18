from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from edgecraft.monitor import build_monitor_decision, latest_hypotheses
from edgecraft.paper_fund import (
    AssetClass,
    FundHypothesis,
    FundPosition,
    FundQuote,
    FundState,
    HypothesisStance,
    OrderSide,
)

NOW = datetime(2026, 10, 18, 15, tzinfo=UTC)
CONTRACT = "kalshi:KXFED-26OCT-T4.00:YES"


def test_code_only_monitor_emits_full_stop_exit() -> None:
    state = FundState(
        fund_id="fund",
        as_of=NOW - timedelta(hours=1),
        cash=Decimal("700"),
        positions=(
            FundPosition(
                instrument_id=CONTRACT,
                asset_class=AssetClass.PREDICTION,
                quantity="500",
                average_entry="0.60",
                mark_price="0.60",
                market_value="300",
                unrealized_pnl="0",
            ),
        ),
        nav="1000",
        peak_nav="1000",
        drawdown="0",
        gross_exposure="300",
        net_exposure="300",
        short_exposure="0",
    )
    hypothesis = FundHypothesis(
        instrument_id=CONTRACT,
        stance=HypothesisStance.LONG,
        statement="hold through the decision",
        mechanism="futures-implied path",
        catalysts=("FOMC statement",),
        falsifiers=("below 0.45",),
        expected_horizon_hours=24,
        confidence="0.7",
        p_win="0.7",
        target_price="0.95",
        invalidation_price="0.45",
        playbook_id="resolution_reading",
        driver="fomc",
        evidence_ids=("old",),
    )
    quote = FundQuote(
        quote_id="code-fed",
        instrument_id=CONTRACT,
        asset_class=AssetClass.PREDICTION,
        price="0.44",
        observed_at=NOW,
        source_timestamp=NOW,
        source_name="code feed",
        source_url="https://example.test/fed",
    )
    decision = build_monitor_decision(
        fund_id="fund",
        state=state,
        hypotheses=(hypothesis,),
        hypothesis_started_at={CONTRACT: NOW - timedelta(hours=1)},
        quotes=(quote,),
        as_of=NOW,
    )
    assert decision.orders[0].side is OrderSide.SELL
    assert decision.orders[0].quantity == Decimal("500")
    assert decision.orders[0].extra_slippage_bps == Decimal("20")
    assert decision.journal is not None
    assert decision.journal.hypotheses[0].stance is HypothesisStance.EXIT


def test_latest_hypotheses_track_when_current_inventory_opened() -> None:
    def cycle(at: datetime, side: str, quantity: str) -> dict:
        return {
            "as_of": at.isoformat(),
            "decision": {"journal": {"hypotheses": []}},
            "fills": [{"instrument_id": CONTRACT, "side": side, "quantity": quantity}],
        }

    first, second, third = NOW - timedelta(days=3), NOW - timedelta(days=2), NOW
    _, opened = latest_hypotheses(
        [cycle(first, "buy", "10"), cycle(second, "sell", "10"), cycle(third, "buy", "5")]
    )
    assert opened[CONTRACT] == third
