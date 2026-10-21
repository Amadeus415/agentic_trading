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
    QuoteStatus,
)

NOW = datetime(2026, 10, 18, 15, tzinfo=UTC)
CONTRACT = "kalshi:KXFED-26OCT-T4.00:YES"


def _state() -> FundState:
    return FundState(
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


def _hypothesis(horizon_hours: int = 24) -> FundHypothesis:
    return FundHypothesis(
        instrument_id=CONTRACT,
        stance=HypothesisStance.LONG,
        statement="hold through the decision",
        mechanism="futures-implied path",
        catalysts=("FOMC statement",),
        falsifiers=("below 0.45",),
        expected_horizon_hours=horizon_hours,
        confidence="0.7",
        p_win="0.7",
        target_price="0.95",
        invalidation_price="0.45",
        playbook_id="resolution_reading",
        driver="fomc",
        evidence_ids=("old",),
    )


def _quote(price: str, status: QuoteStatus = QuoteStatus.OPEN) -> FundQuote:
    return FundQuote(
        quote_id="code-fed",
        instrument_id=CONTRACT,
        asset_class=AssetClass.PREDICTION,
        price=price,
        observed_at=NOW,
        source_timestamp=NOW,
        source_name="code feed",
        source_url="https://example.test/fed",
        status=status,
    )


def test_code_only_monitor_emits_full_stop_exit() -> None:
    decision = build_monitor_decision(
        fund_id="fund",
        state=_state(),
        hypotheses=(_hypothesis(),),
        hypothesis_started_at={CONTRACT: NOW - timedelta(hours=1)},
        quotes=(_quote("0.44"),),
        as_of=NOW,
    )
    assert decision.orders[0].side is OrderSide.SELL
    assert decision.orders[0].quantity == Decimal("500")
    assert decision.orders[0].extra_slippage_bps == Decimal("20")
    assert decision.journal is not None
    assert decision.journal.hypotheses[0].stance is HypothesisStance.EXIT


def test_pending_mark_holds_for_settlement_instead_of_exiting() -> None:
    # Past its stop and its horizon, but there is no two-sided market to exit into.
    decision = build_monitor_decision(
        fund_id="fund",
        state=_state(),
        hypotheses=(_hypothesis(horizon_hours=1),),
        hypothesis_started_at={CONTRACT: NOW - timedelta(hours=2)},
        quotes=(_quote("0.10", QuoteStatus.PENDING),),
        as_of=NOW,
    )
    assert decision.orders == ()
    assert decision.journal is not None
    assert decision.journal.what_changed == f"{CONTRACT}:pending"


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
