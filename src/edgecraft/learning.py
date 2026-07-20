from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field

from edgecraft.autonomy import create_weekly_proposal
from edgecraft.autonomy_models import Mandate, WeeklyDecision
from edgecraft.execution_models import (
    MarketQuote,
    OpenOrderSnapshot,
    PortfolioSnapshot,
    RiskPolicy,
)
from edgecraft.orchestration import robinhood_protocol

SYMBOLS = ("VTI", "VXUS", "BND")
PRICES = {"VTI": 330.0, "VXUS": 75.0, "BND": 74.0}


class LearningScenarioRequest(BaseModel):
    """Safe, synthetic inputs for exercising the production proposal gate."""

    weekly_budget: Decimal = Field(Decimal("10.00"), gt=0, le=100, decimal_places=2)
    confidence: Decimal = Field(Decimal("0.70"), ge=0, le=1)
    vti_notional: Decimal = Field(Decimal("6.00"), ge=0, le=100, decimal_places=2)
    vxus_notional: Decimal = Field(Decimal("2.50"), ge=0, le=100, decimal_places=2)
    bnd_notional: Decimal = Field(Decimal("1.50"), ge=0, le=100, decimal_places=2)
    snapshot_age_seconds: int = Field(30, ge=0, le=3_600)
    quote_age_seconds: int = Field(30, ge=0, le=3_600)
    buying_power: Decimal = Field(Decimal("250.00"), ge=0, le=10_000, decimal_places=2)
    account_eligible: bool = True
    has_open_order: bool = False


def learning_guide() -> dict:
    protocol = robinhood_protocol()
    return {
        "schema_version": "edgecraft.learning-guide.v1",
        "principle": "Models propose. Typed policy authorizes. The broker executes.",
        "cycle": [
            {
                "id": "mandate",
                "label": "Mandate",
                "owner": "You",
                "source": "autonomy_models.py",
                "question": "What is the agent allowed to do?",
                "detail": (
                    "A versioned contract fixes the goal, weekly ceiling, universe, "
                    "strategic weights, schedule, mode, and confidence floor."
                ),
            },
            {
                "id": "observe",
                "label": "Observe",
                "owner": "Codex + Robinhood MCP",
                "source": "codex_runtime.py",
                "question": "What is true right now?",
                "detail": (
                    "A scoped reasoning turn refreshes the eligible account, positions, "
                    "open orders, buying power, quotes, and tradability."
                ),
            },
            {
                "id": "decide",
                "label": "Decide",
                "owner": "Reasoning model",
                "source": "autonomy_models.py",
                "question": "Invest this week, or hold?",
                "detail": (
                    "The model returns a typed hypothesis, confidence, evidence, risks, "
                    "alternatives, and dollar allocations. This is advice, not authority."
                ),
            },
            {
                "id": "gate",
                "label": "Gate",
                "owner": "Deterministic Python",
                "source": "autonomy.py + risk.py",
                "question": "Does every hard rule pass?",
                "detail": (
                    "Code checks budget, whitelist, tactical tilt, cash, concentration, "
                    "freshness, open orders, evidence, and execution mode."
                ),
            },
            {
                "id": "execute",
                "label": "Review + execute",
                "owner": "Permit hook + Robinhood MCP",
                "source": "autonomous_service.py",
                "question": "May this exact order reach the broker?",
                "detail": (
                    "Shadow mode stops before mutation. Live mode additionally requires an "
                    "explicit live mandate, broker review, and a single-use expiring permit."
                ),
            },
            {
                "id": "reconcile",
                "label": "Reconcile",
                "owner": "Edgecraft ledger",
                "source": "ledger.py",
                "question": "What actually happened?",
                "detail": (
                    "Order, fill, cash, and position state are refreshed and appended to the "
                    "audit trail. Ambiguity after live authority activates the kill switch."
                ),
            },
        ],
        "interfaces": [
            {
                "name": "Web app",
                "audience": "You",
                "job": "Learn, configure, compare, and inspect.",
                "path": "Browser → FastAPI",
            },
            {
                "name": "CLI",
                "audience": "Operators and scripts",
                "job": "Run and monitor durable workflows.",
                "path": "Terminal → shared Python modules",
            },
            {
                "name": "MCP",
                "audience": "Reasoning agent",
                "job": "Read broker truth and perform reviewed broker actions.",
                "path": "Codex → Robinhood tools",
            },
        ],
        "protocol": {
            "principle": protocol["principle"],
            "refresh_tools": protocol["refresh_tools"],
            "invariants": protocol["invariants"],
        },
    }


def run_learning_scenario(request: LearningScenarioRequest) -> dict:
    now = datetime.now(UTC)
    mandate = Mandate(
        mandate_id="learning_index_dca",
        goal="Learn how a bounded weekly contribution becomes a policy-gated shadow proposal.",
        mode="shadow",
        weekly_budget=request.weekly_budget,
        risk_level="balanced",
        universe=list(SYMBOLS),
        strategic_weights={"VTI": "0.60", "VXUS": "0.25", "BND": "0.15"},
        minimum_confidence="0.55",
        policy_path="examples/policy.autonomous-shadow.json",
    )
    allocations = [
        {
            "symbol": symbol,
            "notional": notional,
            "conviction": request.confidence,
            "rationale": f"Learning allocation for the {symbol} strategic sleeve.",
        }
        for symbol, notional in (
            ("VTI", request.vti_notional),
            ("VXUS", request.vxus_notional),
            ("BND", request.bnd_notional),
        )
        if notional > 0
    ]
    action = "invest" if allocations else "hold"
    decision = WeeklyDecision(
        mandate_id=mandate.mandate_id,
        run_id="learning-run",
        as_of=now,
        action=action,
        confidence=request.confidence,
        hypothesis=(
            "Preserve the strategic index allocation while testing whether this week's "
            "bounded contribution passes every deterministic control."
        ),
        evidence=["Synthetic learning scenario; no broker data or order placement is used."],
        alternatives_considered=["Hold the full weekly contribution as cash."],
        risks=["The proposed mix may violate a hard mandate or policy rule."],
        allocations=allocations,
        data_sources=["Edgecraft learning sandbox"],
    )
    snapshot_time = now - timedelta(seconds=request.snapshot_age_seconds)
    quote_time = now - timedelta(seconds=request.quote_age_seconds)
    snapshot = PortfolioSnapshot(
        account_id="synthetic-learning-account",
        nickname="Learning sandbox",
        agentic_allowed=request.account_eligible,
        buying_power=float(request.buying_power),
        portfolio_value=max(float(request.buying_power), 1.0),
        as_of=snapshot_time,
        open_orders=(
            [
                OpenOrderSnapshot(
                    order_id="existing-learning-order",
                    symbol="VTI",
                    side="buy",
                    notional=5,
                    status="open",
                )
            ]
            if request.has_open_order
            else []
        ),
        source="synthetic_learning_sandbox",
    )
    quotes = [
        MarketQuote(symbol=symbol, last=PRICES[symbol], as_of=quote_time) for symbol in SYMBOLS
    ]
    policy = RiskPolicy(
        policy_name="learning-shadow-v1",
        allowed_symbols=list(SYMBOLS),
        managed_capital_limit=10_000,
        max_order_notional=float(request.weekly_budget),
        max_daily_notional=float(request.weekly_budget),
        max_orders_per_day=3,
        max_position_weight=0.75,
        min_cash_reserve=0,
        max_quote_age_seconds=300,
        max_snapshot_age_seconds=300,
        allow_sells=False,
        require_research_evidence=False,
        require_review=True,
    )
    proposal = create_weekly_proposal(
        mandate,
        decision,
        snapshot,
        quotes,
        policy,
        run_id=decision.run_id,
        cycle_budget=request.weekly_budget,
        now=now,
    )
    approved = proposal.risk.approved_for_review
    decision_notional = sum(
        (allocation.notional for allocation in decision.allocations), Decimal("0")
    )
    freshness_ok = (
        request.snapshot_age_seconds <= policy.max_snapshot_age_seconds
        and request.quote_age_seconds <= policy.max_quote_age_seconds
        and request.account_eligible
        and not request.has_open_order
    )
    decision_ok = (
        decision.confidence >= mandate.minimum_confidence
        and decision_notional <= request.weekly_budget
    )
    return {
        "schema_version": "edgecraft.learning-scenario.v1",
        "safe_mode": "shadow",
        "approved": approved,
        "outcome": "shadow_complete" if approved else "risk_rejected",
        "headline": (
            "Every hard control passed. Edgecraft would record a shadow proposal."
            if approved
            else "No broker handoff. Deterministic controls blocked the proposal."
        ),
        "summary": (
            "Shadow mode proves the complete decision path without placing an order."
            if approved
            else "Change one input at a time and rerun to see which boundary protects the account."
        ),
        "trace": [
            {
                "id": "mandate",
                "status": "pass",
                "title": "Mandate loaded",
                "detail": (
                    f"Up to ${request.weekly_budget:.2f}; VTI/VXUS/BND only; "
                    f"{mandate.minimum_confidence:.0%} minimum confidence."
                ),
            },
            {
                "id": "observe",
                "status": "pass" if freshness_ok else "blocked",
                "title": "Synthetic broker truth refreshed",
                "detail": (
                    f"Snapshot {request.snapshot_age_seconds}s old; quotes "
                    f"{request.quote_age_seconds}s old; buying power ${request.buying_power:.2f}."
                ),
            },
            {
                "id": "decide",
                "status": "pass" if decision_ok else "blocked",
                "title": f"Model proposed ${decision_notional:.2f}",
                "detail": (
                    f"Confidence {decision.confidence:.0%}; the proposal still has no "
                    "execution authority."
                ),
            },
            {
                "id": "gate",
                "status": "pass" if approved else "blocked",
                "title": "Policy gate approved" if approved else "Policy gate rejected",
                "detail": (
                    "Budget, freshness, cash, whitelist, tactical tilt, and concentration passed."
                    if approved
                    else "; ".join(proposal.risk.violations)
                ),
            },
            {
                "id": "execute",
                "status": "shadow" if approved else "not_run",
                "title": "Stopped safely in shadow mode",
                "detail": (
                    "A live order would still need fresh broker review and a single-use permit."
                    if approved
                    else "Review and placement are unreachable after a rejected gate."
                ),
            },
            {
                "id": "reconcile",
                "status": "ready" if approved else "not_run",
                "title": "Audit-ready result",
                "detail": (
                    f"Proposal {proposal.proposal_id} content-addresses these inputs and timestamps."
                    if approved
                    else "The exact rejection reasons remain visible for audit and learning."
                ),
            },
        ],
        "risk": proposal.risk.model_dump(mode="json"),
        "orders": [
            {
                "symbol": order.symbol,
                "notional": order.notional,
                "expected_price": order.expected_price,
                "rationale": order.rationale,
            }
            for order in proposal.orders
        ],
        "proposal_id": proposal.proposal_id,
        "handoff_status": proposal.robinhood_handoff["status"],
    }
