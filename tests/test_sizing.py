from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from edgecraft.paper_fund import (
    AssetClass,
    BookLevel,
    DecisionAction,
    DecisionJournal,
    FundDecision,
    FundEvidence,
    FundHypothesis,
    FundMandate,
    FundOrder,
    FundPosition,
    FundQuote,
    FundState,
    HypothesisStance,
    OrderSide,
    PaperFundValidationError,
    run_cycle_accounting,
)
from edgecraft.policy import TradingPolicy
from edgecraft.sizing import shrink_to_market, size_decision

NOW = datetime(2026, 10, 18, 15, tzinfo=UTC)
MANDATE = FundMandate.model_validate(
    json.loads(Path("examples/fund.mandate.predictions.json").read_text())["mandate"]
)


def _id(name: str) -> str:
    return f"polymarket:{name}:YES"


def _state() -> FundState:
    return FundState(
        fund_id="fund",
        as_of=NOW,
        cash=Decimal("1000"),
        nav=Decimal("1000"),
        peak_nav=Decimal("1000"),
        drawdown=Decimal("0"),
        gross_exposure=Decimal("0"),
        net_exposure=Decimal("0"),
        short_exposure=Decimal("0"),
    )


def _quote(
    name: str, bid: str = "0.38", ask: str = "0.40", size: str = "100000", fee_rate: str = "0"
) -> FundQuote:
    return FundQuote(
        quote_id=f"q-{name}",
        instrument_id=_id(name),
        asset_class=AssetClass.PREDICTION,
        price=(Decimal(bid) + Decimal(ask)) / 2,
        observed_at=NOW,
        source_timestamp=NOW,
        source_name="test",
        source_url="https://example.test",
        bids=(BookLevel(price=bid, size=size),),
        asks=(BookLevel(price=ask, size=size),),
        fee_rate=fee_rate,
        fee_exponent=1,
        fee_quantum="0.00001",
    )


def _decision(hypotheses: tuple[FundHypothesis, ...], orders: tuple[FundOrder, ...] = ()):
    return FundDecision(
        decision_id="d",
        fund_id="fund",
        cycle_key="c",
        as_of=NOW,
        action=DecisionAction.TRADE if orders else DecisionAction.HOLD,
        thesis="test",
        evidence=(
            FundEvidence(
                evidence_id="e",
                observed_at=NOW,
                source_timestamp=NOW,
                source_name="test",
                source_url="https://example.test",
                claim="test catalyst",
                instrument_ids=tuple(dict.fromkeys(h.instrument_id for h in hypotheses)),
            ),
        ),
        journal=DecisionJournal(
            market_regime="test",
            opportunity_set="test",
            portfolio_intent="test",
            what_changed="test",
            hypotheses=hypotheses,
        ),
        orders=orders,
    )


def _belief(
    name: str,
    p_win: str = "0.60",
    *,
    stance: HypothesisStance = HypothesisStance.LONG,
    driver: str | None = None,
    horizon: int = 48,
    playbook: str = "resolution_reading",
) -> FundHypothesis:
    return FundHypothesis(
        instrument_id=_id(name),
        stance=stance,
        statement="primary source settles it",
        mechanism="rule reading",
        catalysts=("release",),
        falsifiers=("rule surprise",),
        expected_horizon_hours=horizon,
        confidence=p_win,
        p_win=p_win,
        target_price="0.99",
        invalidation_price="0.05",
        playbook_id=playbook,
        driver=driver or name,
        evidence_ids=("e",),
    )


def _size(hypotheses, quotes, **kwargs):
    kwargs.setdefault("mandate", MANDATE)
    kwargs.setdefault("state", _state())
    return size_decision(decision=_decision(tuple(hypotheses)), quotes=tuple(quotes), **kwargs)


def test_belief_sizes_with_fractional_kelly_not_model_quantity() -> None:
    order = FundOrder(
        instrument_id=_id("A"),
        asset_class=AssetClass.PREDICTION,
        side=OrderSide.BUY,
        quantity="999",
        rationale="model quantity is advisory",
        evidence_ids=("e",),
    )
    decision = _decision((_belief("A"),), (order,))
    result = size_decision(
        decision=decision,
        quotes=(_quote("A"),),
        state=_state(),
        mandate=MANDATE,
        policy=TradingPolicy(kelly_fraction="0.25"),
    )
    # (0.60 - 0.40) / 0.60 * 0.25 = 8.33% of NAV at the 0.39 midpoint.
    assert result.decision.orders[0].quantity == 213
    assert result.decision.action is DecisionAction.TRADE


def test_unmeasured_playbook_bets_a_meaningful_share_of_nav() -> None:
    policy = TradingPolicy()
    result = _size([_belief("A")], [_quote("A")], trust={"*": policy.prior_trust}, policy=policy)
    # 0.39 + 0.60 x (0.60 - 0.39) = 0.516 believed; full Kelly (0.516 - 0.40) / 0.60 = 19% of NAV.
    # Half Kelly at 0.35 trust bet about 5%, which left most of the fund idle.
    assert Decimal(result.accepted[0]["notional"]) > Decimal("180")


def test_trust_shrinks_belief_toward_market_and_zero_trust_never_trades() -> None:
    assert shrink_to_market(Decimal("0.6"), Decimal("0.4"), Decimal("0.5")) == Decimal("0.50")
    none = _size([_belief("A")], [_quote("A")], trust={"*": Decimal("0")})
    assert none.decision.orders == ()
    assert none.dropped[0]["reason"] == "below_edge_threshold"
    half = _size([_belief("A")], [_quote("A")], trust={"resolution_reading": Decimal("0.5")})
    assert half.accepted[0]["believed_p_win"] == "0.495"
    assert half.accepted[0]["trust"] == "0.5"


def test_unmeasured_playbook_falls_back_to_prior_trust() -> None:
    result = _size(
        [_belief("A")], [_quote("A")], trust={"*": Decimal("0.5"), "other": Decimal("0")}
    )
    assert result.accepted[0]["trust"] == "0.5"


def test_velocity_drops_slow_edges_and_funds_fast_edges_first() -> None:
    slow = _size([_belief("A", "0.45", horizon=8000)], [_quote("A")])
    assert slow.dropped[0]["reason"] == "below_annualized_hurdle"
    beliefs = [_belief("SLOW", "0.95", horizon=2000), _belief("FAST", "0.95", horizon=24)]
    result = _size(beliefs, [_quote("SLOW"), _quote("FAST")])
    assert [item["instrument_id"] for item in result.accepted] == [_id("FAST"), _id("SLOW")]
    assert Decimal(result.accepted[0]["annualized_return"]) > Decimal(
        result.accepted[1]["annualized_return"]
    )


def test_shared_driver_cap_limits_correlated_contracts() -> None:
    beliefs = [_belief(name, "0.95", driver="election") for name in ("A", "B", "C")]
    result = _size(beliefs, [_quote(name) for name in ("A", "B", "C")])
    assert sum(Decimal(item["notional"]) for item in result.accepted) <= Decimal("500")


def test_flat_research_does_not_suppress_directional_candidate() -> None:
    beliefs = [_belief("A"), _belief("FLAT", stance=HypothesisStance.FLAT)]
    result = _size(beliefs, [_quote("A"), _quote("FLAT")])
    assert [order.instrument_id for order in result.decision.orders] == [_id("A")]


def _held(name: str, quantity: str = "100") -> FundState:
    return _state().model_copy(
        update={
            "cash": Decimal("960"),
            "positions": (
                FundPosition(
                    instrument_id=_id(name),
                    asset_class=AssetClass.PREDICTION,
                    quantity=quantity,
                    average_entry="0.40",
                    mark_price="0.39",
                    playbook_id="resolution_reading",
                    driver=name,
                ),
            ),
        }
    )


def test_directional_hypothesis_for_existing_position_is_maintained() -> None:
    result = _size([_belief("A")], [_quote("A")], state=_held("A"))
    assert result.decision.action is DecisionAction.HOLD


def test_opposite_belief_exits_the_held_outcome() -> None:
    result = _size([_belief("A", stance=HypothesisStance.SHORT)], [_quote("A")], state=_held("A"))
    assert [order.side for order in result.decision.orders] == [OrderSide.SELL]
    assert result.dropped[0]["reason"] == "buy_opposite_outcome"


def test_sleeve_budget_is_shared_across_orders_and_existing_inventory() -> None:
    result = _size(
        [_belief("B", "0.95"), _belief("C", "0.95")],
        [_quote("A"), _quote("B"), _quote("C")],
        state=_held("A"),
        sleeve_weights={"resolution_reading": Decimal("0.05")},
    )
    assert sum(Decimal(item["notional"]) for item in result.accepted) <= Decimal("12")


def test_unknown_playbook_cannot_bypass_allocator() -> None:
    result = _size([_belief("A")], [_quote("A")], sleeve_weights={})
    assert result.dropped[0]["reason"] == "unknown_playbook"


def test_fees_can_erase_a_positive_midprice_edge() -> None:
    result = _size([_belief("A", "0.41")], [_quote("A", fee_rate="0.25")])
    assert result.dropped[0]["reason"] == "below_edge_threshold"


def test_entries_fit_cash_instead_of_rejecting_the_whole_cycle() -> None:
    names = ("A", "B", "C", "D", "E")
    quotes = [_quote(name) for name in names]
    result = _size([_belief(name, "0.95") for name in names], quotes)
    outcome = run_cycle_accounting(
        mandate=MANDATE, prior_state=_state(), decision=result.decision, quotes=quotes
    )
    assert outcome.risk.approved
    assert Decimal("0") <= outcome.state.cash < Decimal("5")
    assert any(item["capacity_adjustment"] for item in result.accepted) or result.dropped


def test_invalid_quotes_remain_fatal_during_capacity_sizing() -> None:
    stale = _quote("A").model_copy(update={"observed_at": NOW.replace(year=2020)})
    with pytest.raises(PaperFundValidationError, match="stale"):
        _size([_belief("A")], [stale])


def test_kelly_fraction_scales_quantity() -> None:
    full = _size([_belief("A", "0.45")], [_quote("A")], policy=TradingPolicy(kelly_fraction="1"))
    half = _size([_belief("A", "0.45")], [_quote("A")], policy=TradingPolicy(kelly_fraction="0.5"))
    assert full.decision.orders[0].quantity == pytest.approx(
        2 * half.decision.orders[0].quantity, abs=1
    )


def test_walking_a_thin_book_can_erase_the_edge() -> None:
    quote = _quote("A").model_copy(
        update={"asks": (BookLevel(price="0.40", size="10"), BookLevel(price="0.80", size="5000"))}
    )
    result = _size([_belief("A", "0.60")], [quote])
    assert result.decision.orders == ()
    assert result.dropped[0]["reason"] == "execution_erases_edge"


def test_size_fits_displayed_depth_without_inventing_liquidity() -> None:
    result = _size([_belief("A", "0.95")], [_quote("A", size="7")])
    assert result.decision.orders[0].quantity == 7
    assert "depth" in result.accepted[0]["capacity_adjustment"]


def test_only_prediction_contracts_are_sized() -> None:
    order = FundOrder(
        instrument_id="AAPL",
        asset_class=AssetClass.STOCK,
        side=OrderSide.BUY,
        rationale="retired asset class",
        evidence_ids=("e",),
    )
    decision = _decision(()).model_copy(
        update={"orders": (order,), "action": DecisionAction.TRADE, "journal": None}
    )
    with pytest.raises(PaperFundValidationError, match="prediction contracts only"):
        size_decision(
            decision=decision,
            quotes=(),
            state=_state(),
            mandate=FundMandate(),
        )
