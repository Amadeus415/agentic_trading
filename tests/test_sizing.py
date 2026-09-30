from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

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
from edgecraft.sizing import size_decision

NOW = datetime(2026, 9, 1, 15, tzinfo=UTC)


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


def _quote(symbol: str, price: str, asset: AssetClass) -> FundQuote:
    return FundQuote(
        quote_id=f"q-{symbol}",
        instrument_id=symbol,
        asset_class=asset,
        price=price,
        observed_at=NOW,
        source_timestamp=NOW,
        source_name="test",
        source_url="https://example.test",
    )


def _decision(
    orders: tuple[FundOrder, ...], hypotheses: tuple[FundHypothesis, ...]
) -> FundDecision:
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
                instrument_ids=tuple(
                    dict.fromkeys(
                        [order.instrument_id for order in orders]
                        + [hypothesis.instrument_id for hypothesis in hypotheses]
                    )
                ),
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
    symbol: str, stance: HypothesisStance, target: str, stop: str, driver: str
) -> FundHypothesis:
    return FundHypothesis(
        instrument_id=symbol,
        stance=stance,
        statement="repeatable setup",
        mechanism="public catalyst",
        catalysts=("catalyst",),
        falsifiers=("stop",),
        expected_horizon_hours=24,
        confidence="0.60",
        p_win="0.60",
        target_price=target,
        invalidation_price=stop,
        playbook_id="momentum",
        driver=driver,
        evidence_ids=("e",),
    )


def _order(symbol: str, asset: AssetClass, side: OrderSide) -> FundOrder:
    return FundOrder(
        instrument_id=symbol,
        asset_class=asset,
        side=side,
        quantity="999",
        rationale="model belief",
        evidence_ids=("e",),
    )


def test_sizes_long_and_short_from_beliefs_not_model_quantity() -> None:
    hypotheses = (
        _belief("LONG", HypothesisStance.LONG, "110", "95", "growth"),
        _belief("SHORT", HypothesisStance.SHORT, "90", "105", "rates"),
    )
    result = size_decision(
        decision=_decision(
            (
                _order("LONG", AssetClass.STOCK, OrderSide.BUY),
                _order("SHORT", AssetClass.STOCK, OrderSide.SHORT),
            ),
            hypotheses,
        ),
        quotes=(
            _quote("LONG", "100", AssetClass.STOCK),
            _quote("SHORT", "100", AssetClass.STOCK),
        ),
        state=_state(),
        mandate=FundMandate(max_single_position_weight="0.60"),
    )
    assert len(result.decision.orders) == 2
    assert all(order.quantity != Decimal("999") for order in result.decision.orders)
    assert {order.quantity for order in result.decision.orders} == {Decimal("4")}
    assert {item["driver"] for item in result.accepted} == {"growth", "rates"}


def test_binary_rounding_and_shared_driver_cap() -> None:
    hypotheses = (
        _belief("PRED", HypothesisStance.LONG, "1", "0.2", "event"),
        _belief("ALT", HypothesisStance.LONG, "2", "0.5", "event"),
    )
    result = size_decision(
        decision=_decision(
            (
                _order("PRED", AssetClass.PREDICTION, OrderSide.BUY),
                _order("ALT", AssetClass.CRYPTO, OrderSide.BUY),
            ),
            hypotheses,
        ),
        quotes=(
            _quote("PRED", "0.4", AssetClass.PREDICTION),
            _quote("ALT", "1", AssetClass.CRYPTO),
        ),
        state=_state(),
        mandate=FundMandate(),
    )
    prediction = result.decision.orders[0]
    assert prediction.quantity == prediction.quantity.to_integral_value()
    assert sum(Decimal(item["notional"]) for item in result.accepted) <= Decimal("600")


def test_binary_uses_probability_versus_market_price() -> None:
    hypothesis = _belief("PRED", HypothesisStance.LONG, "0.35", "0.01", "event")
    hypothesis = hypothesis.model_copy(
        update={"p_win": Decimal("0.34"), "confidence": Decimal("0.34")}
    )
    result = size_decision(
        decision=_decision((_order("PRED", AssetClass.PREDICTION, OrderSide.BUY),), (hypothesis,)),
        quotes=(_quote("PRED", "0.16", AssetClass.PREDICTION),),
        state=_state(),
        mandate=FundMandate(),
    )
    assert len(result.decision.orders) == 1
    notional = Decimal(result.accepted[0]["notional"])
    assert Decimal("210") < notional <= Decimal("215")


def test_calibration_haircut_can_drop_an_overconfident_trade() -> None:
    hypothesis = _belief("LONG", HypothesisStance.LONG, "110", "95", "growth")
    result = size_decision(
        decision=_decision((_order("LONG", AssetClass.STOCK, OrderSide.BUY),), (hypothesis,)),
        quotes=(_quote("LONG", "100", AssetClass.STOCK),),
        state=_state(),
        mandate=FundMandate(),
        calibration=({"bucket": "60-70%", "count": 20, "realized_win_rate": "0"},),
    )
    assert result.decision.action is DecisionAction.HOLD
    assert result.dropped[0]["reason"] == "below_edge_threshold"


def test_directional_research_becomes_candidate_order_and_trade() -> None:
    hypothesis = _belief("LONG", HypothesisStance.LONG, "110", "95", "growth")
    advisory_hold = _decision(
        (_order("LONG", AssetClass.STOCK, OrderSide.BUY),),
        (hypothesis,),
    ).model_copy(update={"action": DecisionAction.HOLD, "orders": ()})

    result = size_decision(
        decision=advisory_hold,
        quotes=(_quote("LONG", "100", AssetClass.STOCK),),
        state=_state(),
        mandate=FundMandate(),
    )

    assert result.decision.action is DecisionAction.TRADE
    assert len(result.decision.orders) == 1
    assert result.decision.orders[0].side is OrderSide.BUY
    assert result.accepted[0]["instrument_id"] == "LONG"


def test_flat_research_does_not_suppress_directional_candidate() -> None:
    directional = _belief("LONG", HypothesisStance.LONG, "110", "95", "growth")
    rejected = _belief("FLAT", HypothesisStance.FLAT, "110", "95", "weak-signal")
    advisory_hold = _decision(
        (_order("LONG", AssetClass.STOCK, OrderSide.BUY),),
        (directional, rejected),
    ).model_copy(update={"action": DecisionAction.HOLD, "orders": ()})

    result = size_decision(
        decision=advisory_hold,
        quotes=(
            _quote("LONG", "100", AssetClass.STOCK),
            _quote("FLAT", "100", AssetClass.STOCK),
        ),
        state=_state(),
        mandate=FundMandate(),
    )

    assert [order.instrument_id for order in result.decision.orders] == ["LONG"]
    assert result.decision.action is DecisionAction.TRADE


def test_directional_hypothesis_for_existing_position_is_maintained() -> None:
    state = _state().model_copy(
        update={
            "positions": (
                FundPosition(
                    instrument_id="HELD",
                    asset_class=AssetClass.STOCK,
                    quantity="1",
                    average_entry="100",
                    mark_price="100",
                    playbook_id="momentum",
                    driver="growth",
                ),
            )
        }
    )
    hypothesis = _belief("HELD", HypothesisStance.LONG, "110", "95", "growth")
    advisory_hold = _decision(
        (_order("HELD", AssetClass.STOCK, OrderSide.BUY),),
        (hypothesis,),
    ).model_copy(update={"action": DecisionAction.HOLD, "orders": ()})

    result = size_decision(
        decision=advisory_hold,
        quotes=(_quote("HELD", "100", AssetClass.STOCK),),
        state=state,
        mandate=FundMandate(),
    )

    assert result.decision.action is DecisionAction.HOLD
    assert result.decision.orders == ()


def test_sleeve_budget_is_shared_across_orders_and_existing_inventory() -> None:
    state = _state().model_copy(
        update={
            "positions": (
                FundPosition(
                    instrument_id="HELD",
                    asset_class=AssetClass.STOCK,
                    quantity="0.3",
                    average_entry="100",
                    mark_price="100",
                    playbook_id="momentum",
                    driver="growth",
                ),
            )
        }
    )
    hypotheses = tuple(
        _belief(symbol, HypothesisStance.LONG, "110", "95", "growth") for symbol in ("A", "B")
    )
    result = size_decision(
        decision=_decision(
            tuple(_order(symbol, AssetClass.STOCK, OrderSide.BUY) for symbol in ("A", "B")),
            hypotheses,
        ),
        quotes=tuple(_quote(symbol, "100", AssetClass.STOCK) for symbol in ("HELD", "A", "B")),
        state=state,
        mandate=FundMandate(),
        sleeve_weights={"momentum": Decimal("0.05")},
    )
    assert sum(Decimal(item["notional"]) for item in result.accepted) <= Decimal("20")
    assert len(result.decision.orders) == 1


def test_unknown_playbook_cannot_bypass_allocator() -> None:
    result = size_decision(
        decision=_decision(
            (_order("A", AssetClass.STOCK, OrderSide.BUY),),
            (_belief("A", HypothesisStance.LONG, "110", "95", "growth"),),
        ),
        quotes=(_quote("A", "100", AssetClass.STOCK),),
        state=_state(),
        mandate=FundMandate(),
        sleeve_weights={},
    )
    assert result.dropped[0]["reason"] == "unknown_playbook"


def test_round_trip_charges_both_entry_and_exit_fees() -> None:
    belief = _belief("A", HypothesisStance.LONG, "101", "99", "growth").model_copy(
        update={"p_win": Decimal("0.66")}
    )
    result = size_decision(
        decision=_decision((_order("A", AssetClass.STOCK, OrderSide.BUY),), (belief,)),
        quotes=(_quote("A", "100", AssetClass.STOCK),),
        state=_state(),
        mandate=FundMandate(fee_bps="10", slippage_bps="10"),
    )
    assert result.dropped[0]["reason"] == "below_edge_threshold"


def test_entries_fit_cash_instead_of_rejecting_the_whole_cycle() -> None:
    beliefs = tuple(
        _belief(symbol, HypothesisStance.LONG, "120", "95", symbol).model_copy(
            update={"p_win": Decimal("0.9")}
        )
        for symbol in ("A", "B", "C")
    )
    quotes = tuple(_quote(symbol, "100", AssetClass.STOCK) for symbol in ("A", "B", "C"))
    mandate = FundMandate(max_single_position_weight="0.60", max_cycle_turnover="4000")
    result = size_decision(
        decision=_decision((), beliefs), quotes=quotes, state=_state(), mandate=mandate
    )
    outcome = run_cycle_accounting(
        mandate=mandate, prior_state=_state(), decision=result.decision, quotes=quotes
    )
    assert outcome.risk.approved
    assert Decimal("0") <= outcome.state.cash < Decimal("0.02")
    assert len(outcome.fills) == 2
    assert result.accepted[1]["capacity_adjustment"]
    assert result.dropped[0]["reason"] == "portfolio_capacity"


def test_invalid_quotes_remain_fatal_during_capacity_sizing() -> None:
    import pytest

    quotes = (
        _quote("A", "100", AssetClass.STOCK).model_copy(
            update={"observed_at": NOW.replace(year=2020)}
        ),
    )
    with pytest.raises(PaperFundValidationError, match="stale"):
        size_decision(
            decision=_decision((), (_belief("A", HypothesisStance.LONG, "110", "95", "growth"),)),
            quotes=quotes,
            state=_state(),
            mandate=FundMandate(),
        )


def test_opposite_belief_exits_and_reverses_in_one_cycle() -> None:
    state = _state().model_copy(
        update={
            "cash": Decimal("800"),
            "gross_exposure": Decimal("200"),
            "net_exposure": Decimal("200"),
            "positions": (
                FundPosition(
                    instrument_id="A",
                    asset_class=AssetClass.STOCK,
                    quantity="2",
                    average_entry="100",
                    mark_price="100",
                    playbook_id="momentum",
                    driver="growth",
                ),
            ),
        }
    )
    quotes = (_quote("A", "100", AssetClass.STOCK),)
    mandate = FundMandate(max_single_position_weight="0.60", max_cycle_turnover="4000")
    result = size_decision(
        decision=_decision((), (_belief("A", HypothesisStance.SHORT, "90", "105", "growth"),)),
        quotes=quotes,
        state=state,
        mandate=mandate,
        sleeve_weights={"momentum": Decimal("0.60")},
    )
    assert [order.side for order in result.decision.orders] == [OrderSide.SELL, OrderSide.SHORT]
    outcome = run_cycle_accounting(
        mandate=mandate, prior_state=state, decision=result.decision, quotes=quotes
    )
    assert outcome.state.positions[0].quantity < 0
    assert outcome.risk.approved


def test_policy_and_version_calibration_control_sizing() -> None:
    belief = _belief("A", HypothesisStance.LONG, "110", "95", "growth")
    common = dict(
        decision=_decision((), (belief,)),
        quotes=(_quote("A", "100", AssetClass.STOCK),),
        state=_state(),
        mandate=FundMandate(max_single_position_weight="0.60"),
        calibration=(
            {
                "playbook_id": "old_version",
                "bucket": "60-70%",
                "count": 20,
                "realized_win_rate": "0",
            },
        ),
    )
    aggressive = size_decision(**common)
    fractional = size_decision(**common, policy=TradingPolicy(kelly_fraction="0.5"))
    assert aggressive.decision.orders[0].quantity == 2 * fractional.decision.orders[0].quantity


def test_displayed_spread_can_erase_a_positive_midprice_edge() -> None:
    quote = _quote("A", "100", AssetClass.STOCK).model_copy(
        update={
            "asks": (BookLevel(price="109", size="100"),),
        }
    )
    result = size_decision(
        decision=_decision((), (_belief("A", HypothesisStance.LONG, "110", "95", "growth"),)),
        quotes=(quote,),
        state=_state(),
        mandate=FundMandate(max_single_position_weight="0.60"),
    )
    assert result.decision.orders == ()
    assert result.dropped[0]["reason"] == "execution_erases_edge"


def test_size_fits_displayed_depth_without_inventing_liquidity() -> None:
    quote = _quote("A", "100", AssetClass.STOCK).model_copy(
        update={
            "asks": (BookLevel(price="100", size="1"),),
        }
    )
    result = size_decision(
        decision=_decision((), (_belief("A", HypothesisStance.LONG, "110", "95", "growth"),)),
        quotes=(quote,),
        state=_state(),
        mandate=FundMandate(max_single_position_weight="0.60"),
    )
    assert result.decision.orders[0].quantity == 1
    assert "depth" in result.accepted[0]["capacity_adjustment"]
