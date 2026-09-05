from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from edgecraft.paper_fund import (
    AssetClass,
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
)
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
        action=DecisionAction.TRADE,
        thesis="test",
        evidence=(
            FundEvidence(
                evidence_id="e",
                observed_at=NOW,
                source_timestamp=NOW,
                source_name="test",
                source_url="https://example.test",
                claim="test catalyst",
                instrument_ids=tuple(order.instrument_id for order in orders),
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
        mandate=FundMandate(),
    )
    assert len(result.decision.orders) == 2
    assert all(order.quantity != Decimal("999") for order in result.decision.orders)
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
    assert sum(Decimal(item["notional"]) for item in result.accepted) <= Decimal("400")


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
    assert notional < Decimal("160")
    assert notional <= Decimal("100")


def test_calibration_haircut_can_drop_an_overconfident_trade() -> None:
    hypothesis = _belief("LONG", HypothesisStance.LONG, "110", "95", "growth")
    result = size_decision(
        decision=_decision((_order("LONG", AssetClass.STOCK, OrderSide.BUY),), (hypothesis,)),
        quotes=(_quote("LONG", "100", AssetClass.STOCK),),
        state=_state(),
        mandate=FundMandate(),
        calibration=({"bucket": "60-70%", "count": 5, "realized_win_rate": "0.20"},),
    )
    assert result.decision.action is DecisionAction.HOLD
    assert result.dropped[0]["reason"] == "below_edge_threshold"


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
        quotes=tuple(_quote(symbol, "100", AssetClass.STOCK) for symbol in ("A", "B")),
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
