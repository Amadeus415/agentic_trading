from __future__ import annotations

from datetime import UTC, datetime, timedelta

from edgecraft.autonomy import policy_digest
from edgecraft.execution_models import (
    MarketQuote,
    PortfolioSnapshot,
    ResearchEvidence,
    RiskPolicy,
    TargetAllocation,
    TradeProposal,
)
from edgecraft.ledger import AuditLedger
from edgecraft.risk import build_rebalance_orders, evaluate_orders, proposal_id


def create_trade_proposal(
    snapshot: PortfolioSnapshot,
    quotes: list[MarketQuote],
    targets: TargetAllocation,
    policy: RiskPolicy,
    *,
    strategy: str,
    mode: str,
    ledger: AuditLedger | None = None,
    research: ResearchEvidence | None = None,
    now: datetime | None = None,
) -> TradeProposal:
    if mode not in {"shadow", "live"}:
        raise ValueError("mode must be shadow or live")
    created_at = now or datetime.now(UTC)
    orders = build_rebalance_orders(snapshot, quotes, targets, policy)
    daily_notional = ledger.daily_placed_notional(created_at.date()) if ledger else 0.0
    daily_order_count = ledger.daily_placed_order_count(created_at.date()) if ledger else 0
    rolling_notional = (
        ledger.rolling_placed_notional(
            since=created_at - timedelta(days=7),
            before=created_at,
        )
        if ledger
        else 0.0
    )
    unresolved = ledger.unresolved_order_keys() if ledger else []
    decision = evaluate_orders(
        snapshot,
        quotes,
        orders,
        policy,
        strategy=strategy,
        mode=mode,
        daily_placed_notional=daily_notional,
        daily_placed_order_count=daily_order_count,
        rolling_7d_placed_notional=rolling_notional,
        unresolved_order_keys=unresolved,
        research=research,
        now=created_at,
    )
    identifier = proposal_id(snapshot, strategy, mode, orders, policy)
    proposal = TradeProposal(
        proposal_id=identifier,
        created_at=created_at,
        mode=mode,
        account_id=snapshot.account_id,
        strategy=strategy,
        rationale=targets.rationale,
        policy_name=policy.policy_name,
        policy_digest=policy_digest(policy),
        snapshot_as_of=snapshot.as_of,
        orders=orders,
        risk=decision,
        research=research,
        robinhood_handoff=_robinhood_handoff(
            snapshot, orders, mode, decision.approved_for_review, policy.require_review
        ),
    )
    if ledger is not None:
        ledger.add_proposal(proposal)
    return proposal


def robinhood_protocol() -> dict:
    return {
        "schema_version": "edgecraft.robinhood-protocol.v1",
        "principle": "refresh -> recompute -> risk gate -> review -> authorize -> place -> reconcile",
        "official_mcp_endpoint": "https://agent.robinhood.com/mcp/trading",
        "refresh_tools": [
            "get_accounts",
            "get_portfolio",
            "get_equity_positions",
            "get_equity_quotes",
            "get_equity_tradability",
            "get_equity_orders",
        ],
        "research_tools": [
            "get_equity_historicals",
            "get_equity_fundamentals",
            "get_equity_technical_indicators",
            "get_earnings_results",
            "get_earnings_calendar",
            "get_realized_pnl",
            "get_pnl_trade_history",
            "get_scans",
            "run_scan",
        ],
        "execution_tools": [
            "review_equity_order",
            "place_equity_order",
            "get_equity_orders",
            "cancel_equity_order",
        ],
        "invariants": [
            "Only use an account returned with agentic_allowed=true.",
            "Never infer or reuse an account id from prose; refresh it from get_accounts.",
            "Never place an order that lacks an approved Edgecraft proposal and Robinhood review.",
            "Never place the same proposal/order_key twice.",
            "Re-run risk checks if account, quote, order, or policy data changes.",
            "Record placed, filled, partially filled, rejected, and canceled outcomes in the ledger.",
            "A shadow proposal must never call place_equity_order.",
        ],
    }


def _robinhood_handoff(
    snapshot: PortfolioSnapshot,
    orders,
    mode: str,
    approved: bool,
    require_review: bool,
) -> dict:
    review_calls = [
        {
            "tool": "review_equity_order",
            "semantic_arguments": {
                "account_id": snapshot.account_id,
                "symbol": order.symbol,
                "side": order.side,
                "dollar_notional": order.notional,
                "order_type": order.order_type,
                "time_in_force": order.time_in_force,
                "limit_price": order.limit_price,
            },
            "order_key": order.order_key,
            "note": "Map semantic fields to the live MCP tool schema exposed by the host.",
        }
        for order in orders
    ]
    return {
        "status": (
            "blocked"
            if not approved
            else "shadow_only"
            if mode == "shadow"
            else "approved_for_robinhood_review"
        ),
        "required_account_refresh": ["get_accounts", "get_portfolio", "get_equity_positions"],
        "required_market_refresh": ["get_equity_quotes", "get_equity_tradability"],
        "review_calls": review_calls if approved else [],
        "placement_authorized": bool(approved and mode == "live" and not require_review),
        "placement_rule": (
            "After successful review, place only when the orchestrator's governing instruction "
            "explicitly authorizes live placement. Use the MCP-returned review/order payload; "
            "never construct undocumented placement arguments."
        ),
        "reconcile_with": ["get_equity_orders", "get_portfolio", "get_equity_positions"],
    }
