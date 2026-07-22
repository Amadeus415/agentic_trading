from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from zoneinfo import ZoneInfo

from edgecraft.autonomy_models import DecisionAllocation, Mandate, WeeklyDecision
from edgecraft.execution_models import (
    DecisionReasoning,
    MarketQuote,
    PortfolioSnapshot,
    ProposedOrder,
    ResearchEvidence,
    RiskDecision,
    RiskPolicy,
    TradeProposal,
)
from edgecraft.ledger import AuditLedger
from edgecraft.risk import evaluate_orders

CENT = Decimal("0.01")


def cycle_key(mandate: Mandate, now: datetime | None = None) -> str:
    current = _aware(now or datetime.now(UTC)).astimezone(ZoneInfo(mandate.timezone))
    if mandate.cycle_frequency == "market_day":
        return f"{mandate.mandate_id}:{current.date().isoformat()}"
    year, week, _ = current.isocalendar()
    return f"{mandate.mandate_id}:{year:04d}-W{week:02d}"


def cycle_due(mandate: Mandate, now: datetime | None = None) -> bool:
    if not mandate.enabled:
        return False
    current = _aware(now or datetime.now(UTC)).astimezone(ZoneInfo(mandate.timezone))
    if mandate.cycle_frequency == "market_day":
        if current.weekday() >= 5:
            return False
        scheduled = datetime.combine(
            current.date(), mandate.schedule_time, tzinfo=ZoneInfo(mandate.timezone)
        )
        return current >= scheduled
    week_start = current.date() - timedelta(days=current.weekday())
    scheduled_date = week_start + timedelta(days=mandate.schedule_weekday)
    scheduled = datetime.combine(
        scheduled_date, mandate.schedule_time, tzinfo=ZoneInfo(mandate.timezone)
    )
    return current >= scheduled


def available_cycle_budget(
    mandate: Mandate,
    ledger: AuditLedger,
    *,
    now: datetime | None = None,
) -> Decimal:
    current_key = cycle_key(mandate, now)
    already_placed = Decimal(str(ledger.cycle_placed_notional(mandate.mandate_id, current_key)))
    current_remaining = max(Decimal("0"), mandate.cycle_budget - already_placed)
    rollover = Decimal("0")
    if mandate.cycle_frequency == "weekly" and mandate.max_rollover_weeks:
        prior_placed = ledger.recent_cycle_placed_notionals(
            mandate.mandate_id,
            before_cycle_key=current_key,
            limit=mandate.max_rollover_weeks,
        )
        rollover = sum(
            (
                max(Decimal("0"), mandate.cycle_budget - Decimal(str(placed)))
                for placed in prior_placed
            ),
            Decimal("0"),
        )
    return (current_remaining + rollover).quantize(CENT)


def create_weekly_proposal(
    mandate: Mandate,
    decision: WeeklyDecision,
    snapshot: PortfolioSnapshot,
    quotes: list[MarketQuote],
    policy: RiskPolicy,
    *,
    run_id: str,
    cycle_budget: Decimal,
    ledger: AuditLedger | None = None,
    research: ResearchEvidence | None = None,
    attempt: int = 1,
    now: datetime | None = None,
) -> TradeProposal:
    current_time = _aware(now or datetime.now(UTC))
    if decision.mandate_id != mandate.mandate_id:
        raise ValueError("decision mandate_id does not match mandate")
    if decision.run_id != run_id:
        raise ValueError("decision run_id does not match the active run")

    orders, decision_violations, decision_warnings = _decision_orders(
        mandate,
        decision,
        quotes,
        cycle_budget=cycle_budget,
        min_order_notional=Decimal(str(policy.min_order_notional)),
        attempt=attempt,
    )
    daily_notional = ledger.daily_placed_notional(current_time.date()) if ledger else 0.0
    daily_order_count = ledger.daily_placed_order_count(current_time.date()) if ledger else 0
    rolling_notional = (
        ledger.rolling_placed_notional(
            since=current_time - timedelta(days=7),
            before=current_time,
        )
        if ledger
        else 0.0
    )
    high_watermark = ledger.portfolio_high_watermark(mandate.mandate_id) if ledger else None
    shadow_history_id = mandate.promotion_source_mandate_id or mandate.mandate_id
    shadow_cycles = ledger.successful_shadow_cycle_count(shadow_history_id) if ledger else 0
    unresolved = ledger.unresolved_order_keys() if ledger else []
    risk = evaluate_orders(
        snapshot,
        quotes,
        orders,
        policy,
        strategy=_strategy_name(mandate),
        mode=mandate.mode,
        daily_placed_notional=daily_notional,
        daily_placed_order_count=daily_order_count,
        rolling_7d_placed_notional=rolling_notional,
        portfolio_high_watermark=high_watermark,
        successful_shadow_cycles=shadow_cycles,
        unresolved_order_keys=unresolved,
        research=research,
        now=current_time,
    )
    if decision_violations or decision_warnings:
        violations = sorted(set([*risk.violations, *decision_violations]))
        warnings = sorted(set([*risk.warnings, *decision_warnings]))
        risk = risk.model_copy(
            update={
                "approved_for_review": not violations,
                "violations": violations,
                "warnings": warnings,
            }
        )

    identifier = _weekly_proposal_id(
        mandate, run_id, snapshot, orders, policy, decision, attempt=attempt
    )
    proposal = TradeProposal(
        proposal_id=identifier,
        mandate_id=mandate.mandate_id,
        run_id=run_id,
        created_at=current_time,
        mode=mandate.mode,
        account_id=snapshot.account_id,
        strategy=_strategy_name(mandate),
        rationale=decision.hypothesis,
        decision_reasoning=DecisionReasoning(
            action=decision.action,
            confidence=decision.confidence,
            hypothesis=decision.hypothesis,
            evidence=decision.evidence,
            alternatives_considered=decision.alternatives_considered,
            risks=decision.risks,
            data_sources=decision.data_sources,
            context_source_ids=decision.context_source_ids,
            evidence_items=decision.evidence_items,
            allocation_rationales={
                allocation.symbol: allocation.rationale for allocation in decision.allocations
            },
            allocation_evidence_ids={
                allocation.symbol: allocation.evidence_ids for allocation in decision.allocations
            },
        ),
        policy_name=policy.policy_name,
        policy_digest=policy_digest(policy),
        snapshot_as_of=snapshot.as_of,
        orders=orders,
        risk=risk,
        research=research,
        robinhood_handoff=_handoff(snapshot, orders, mandate.mode, risk),
    )
    if ledger is not None:
        ledger.add_proposal(proposal)
    return proposal


def _decision_orders(
    mandate: Mandate,
    decision: WeeklyDecision,
    quotes: list[MarketQuote],
    *,
    cycle_budget: Decimal,
    min_order_notional: Decimal,
    attempt: int,
) -> tuple[list[ProposedOrder], list[str], list[str]]:
    if decision.action == "hold":
        return [], ["reasoning agent elected to hold this cycle"], []

    total = sum((allocation.notional for allocation in decision.allocations), Decimal("0"))
    violations = _decision_level_violations(mandate, decision, total, cycle_budget)
    warnings: list[str] = []
    quote_map = {quote.symbol: quote for quote in quotes}
    orders: list[ProposedOrder] = []
    for allocation in decision.allocations:
        order, allocation_violations, allocation_warnings = _allocation_order(
            mandate,
            decision.run_id,
            allocation,
            quote_map.get(allocation.symbol),
            total=total,
            min_order_notional=min_order_notional,
            attempt=attempt,
        )
        violations.extend(allocation_violations)
        warnings.extend(allocation_warnings)
        if order is not None:
            orders.append(order)
    return orders, violations, warnings


def _decision_level_violations(
    mandate: Mandate,
    decision: WeeklyDecision,
    total: Decimal,
    cycle_budget: Decimal,
) -> list[str]:
    violations: list[str] = []
    if decision.confidence < mandate.minimum_confidence:
        violations.append(
            "decision confidence "
            f"{decision.confidence} is below minimum {mandate.minimum_confidence}"
        )
    if total > cycle_budget:
        violations.append(
            f"decision notional {total:.2f} exceeds remaining cycle budget {cycle_budget:.2f}"
        )
    if total <= 0:
        violations.append("decision contains no positive investment notional")
    return violations


def _allocation_order(
    mandate: Mandate,
    run_id: str,
    allocation: DecisionAllocation,
    quote: MarketQuote | None,
    *,
    total: Decimal,
    min_order_notional: Decimal,
    attempt: int,
) -> tuple[ProposedOrder | None, list[str], list[str]]:
    if allocation.symbol not in mandate.universe:
        return None, [f"{allocation.symbol} is outside the mandate universe"], []
    if quote is None:
        return None, [f"missing quote for {allocation.symbol}"], []

    violations = _allocation_share_violations(mandate, allocation, total)
    notional = allocation.notional.quantize(CENT, rounding=ROUND_DOWN)
    if notional < min_order_notional:
        return (
            None,
            violations,
            [
                f"dropped {allocation.symbol} allocation {notional:.2f} below "
                f"min_order_notional={min_order_notional:.2f}"
            ],
        )

    identity = (
        f"{mandate.mandate_id}:{run_id}:{allocation.symbol}:{notional}:"
        f"{quote.as_of.isoformat()}:attempt={attempt}"
    )
    return (
        ProposedOrder(
            order_key=hashlib.sha256(identity.encode()).hexdigest()[:20],
            symbol=allocation.symbol,
            side="buy",
            notional=float(notional),
            expected_price=quote.last,
            rationale=allocation.rationale,
            quote_as_of=quote.as_of,
        ),
        violations,
        [],
    )


def _allocation_share_violations(
    mandate: Mandate,
    allocation: DecisionAllocation,
    total: Decimal,
) -> list[str]:
    if mandate.cycle_frequency != "weekly":
        return []
    allocation_share = allocation.notional / total if total > 0 else Decimal("0")
    strategic = mandate.strategic_weights.get(allocation.symbol, Decimal("0"))
    max_share = min(Decimal("1"), strategic + mandate.tactical_tilt_limit)
    if allocation_share <= max_share + Decimal("0.000001"):
        return []
    return [
        f"{allocation.symbol} decision share {allocation_share:.1%} exceeds "
        f"strategic+tactical limit {max_share:.1%}"
    ]


def _weekly_proposal_id(
    mandate: Mandate,
    run_id: str,
    snapshot: PortfolioSnapshot,
    orders: list[ProposedOrder],
    policy: RiskPolicy,
    decision: WeeklyDecision,
    *,
    attempt: int,
) -> str:
    content = "|".join(
        [
            mandate.mandate_id,
            run_id,
            snapshot.as_of.isoformat(),
            policy.policy_name,
            decision.as_of.isoformat(),
            f"attempt={attempt}",
            *(f"{order.order_key}:{order.notional:.2f}" for order in orders),
        ]
    )
    return "prop_" + hashlib.sha256(content.encode()).hexdigest()[:24]


def _strategy_name(mandate: Mandate) -> str:
    return (
        "agentic_market_day_buy"
        if mandate.cycle_frequency == "market_day"
        else "agentic_weekly_dca"
    )


def policy_digest(policy: RiskPolicy) -> str:
    payload = json.dumps(
        policy.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _handoff(
    snapshot: PortfolioSnapshot,
    orders: list[ProposedOrder],
    mode: str,
    risk: RiskDecision,
) -> dict:
    return {
        "status": (
            "blocked"
            if not risk.approved_for_review
            else "shadow_only"
            if mode == "shadow"
            else "permit_required"
        ),
        "account_refresh_required": True,
        "placement_authorized": False,
        "review_calls": [
            {
                "tool": "review_equity_order",
                "order_key": order.order_key,
                "semantic_arguments": {
                    "account_id": snapshot.account_id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "dollar_notional": order.notional,
                    "order_type": order.order_type,
                    "time_in_force": order.time_in_force,
                    "limit_price": order.limit_price,
                },
            }
            for order in orders
        ]
        if risk.approved_for_review
        else [],
        "invariant": "A single-use Edgecraft permit is required for each placement tool call.",
    }


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
