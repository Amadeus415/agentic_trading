"""Code-only position monitoring and deterministic paper exits."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from edgecraft.paper_fund import (
    DecisionAction,
    DecisionJournal,
    FundDecision,
    FundEvidence,
    FundHypothesis,
    FundOrder,
    FundQuote,
    FundState,
    HypothesisStance,
    OrderSide,
    QuoteStatus,
)

EASTERN = ZoneInfo("America/New_York")
GAP_PENALTY_BPS = Decimal("20")


def stock_market_is_open(at: datetime) -> bool:
    local = at.astimezone(EASTERN)
    minute = local.hour * 60 + local.minute
    return local.weekday() < 5 and (9 * 60 + 30) <= minute < 16 * 60


def build_monitor_decision(
    *,
    fund_id: str,
    state: FundState,
    hypotheses: Sequence[FundHypothesis],
    hypothesis_started_at: dict[str, datetime],
    quotes: Sequence[FundQuote],
    as_of: datetime,
) -> tuple[FundDecision, list[dict[str, str]]]:
    """Create a model-free decision that exits hit stops, targets, and time stops."""
    quote_by_id = {quote.instrument_id: quote for quote in quotes}
    hypothesis_by_id = {item.instrument_id: item for item in hypotheses}
    evidence: list[FundEvidence] = []
    orders: list[FundOrder] = []
    reasons: list[dict[str, str]] = []
    queued: list[dict[str, str]] = []

    for position in state.positions:
        quote = quote_by_id[position.instrument_id]
        hypothesis = hypothesis_by_id[position.instrument_id]
        evidence_id = f"monitor-{quote.quote_id}"
        evidence.append(
            FundEvidence(
                evidence_id=evidence_id,
                observed_at=quote.observed_at,
                source_timestamp=quote.source_timestamp,
                source_name=quote.source_name,
                source_url=quote.source_url,
                claim=f"Code-owned monitor mark is {quote.price} for {position.instrument_id}.",
                summary="Public mark fetched and cached by deterministic monitor code.",
                instrument_ids=(position.instrument_id,),
                content="",
            )
        )
        if quote.status is QuoteStatus.SETTLED:
            reasons.append({"instrument_id": position.instrument_id, "reason": "settled"})
            continue
        is_long = position.quantity > 0
        reason: str | None = None
        gapped = False
        if hypothesis.invalidation_price is not None:
            breached = (
                quote.price <= hypothesis.invalidation_price
                if is_long
                else quote.price >= hypothesis.invalidation_price
            )
            if breached:
                reason = "stop_hit"
                gapped = (
                    quote.price < hypothesis.invalidation_price
                    if is_long
                    else quote.price > hypothesis.invalidation_price
                )
        if reason is None and hypothesis.target_price is not None:
            reached = (
                quote.price >= hypothesis.target_price
                if is_long
                else quote.price <= hypothesis.target_price
            )
            if reached:
                reason = "target_hit"
        started = hypothesis_started_at.get(position.instrument_id, state.as_of)
        elapsed_hours = Decimal(str((as_of - started).total_seconds() / 3600))
        if reason is None and elapsed_hours >= hypothesis.expected_horizon_hours:
            reason = "horizon_expired"
        if reason is None:
            continue
        if position.asset_class.value == "stock" and not stock_market_is_open(as_of):
            queued.append({"instrument_id": position.instrument_id, "reason": reason})
            continue
        orders.append(
            FundOrder(
                instrument_id=position.instrument_id,
                asset_class=position.asset_class,
                side=OrderSide.SELL if is_long else OrderSide.COVER,
                quantity=abs(position.quantity),
                rationale=f"Code-only monitor exit: {reason}.",
                evidence_ids=(evidence_id,),
                p_win=Decimal("1"),
                target_price=hypothesis.target_price,
                invalidation_price=hypothesis.invalidation_price,
                horizon_hours=hypothesis.expected_horizon_hours,
                playbook_id=hypothesis.playbook_id,
                driver=hypothesis.driver,
                extra_slippage_bps=GAP_PENALTY_BPS if gapped else None,
            )
        )
        reasons.append({"instrument_id": position.instrument_id, "reason": reason})

    refreshed = tuple(
        item.model_copy(
            update={
                "stance": (
                    HypothesisStance.EXIT
                    if any(order.instrument_id == item.instrument_id for order in orders)
                    else item.stance
                ),
                "evidence_ids": (f"monitor-{quote_by_id[item.instrument_id].quote_id}",),
            }
        )
        for item in hypotheses
    )
    action = DecisionAction.TRADE if orders else DecisionAction.HOLD
    cycle_key = as_of.strftime("monitor-%Y-%m-%dT%H%M%SZ")
    decision = FundDecision(
        decision_id=f"decision-{cycle_key}",
        fund_id=fund_id,
        cycle_key=cycle_key,
        as_of=as_of,
        action=action,
        thesis="Code-only monitor applied mechanical target, stop, settlement, and horizon rules.",
        alternatives="No discretionary alternatives; this path does not call a model.",
        risks="Public feeds may fail or gap beyond a stop; execution includes configured slippage.",
        journal=DecisionJournal(
            market_regime="Not assessed by the code-only monitor.",
            opportunity_set="Existing positions only.",
            portfolio_intent="Enforce the exits already specified by each hypothesis.",
            what_changed=(
                "; ".join(f"{item['instrument_id']}:{item['reason']}" for item in reasons)
                or "No mechanical exit fired."
            ),
            lessons_applied=("Do not move target, stop, or horizon goalposts.",),
            hypotheses=refreshed,
        ),
        evidence=tuple(evidence),
        orders=tuple(orders),
    )
    return decision, queued
