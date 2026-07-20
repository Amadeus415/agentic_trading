from datetime import UTC, datetime

import pytest

from edgecraft.execution_models import (
    MarketQuote,
    OpenOrderSnapshot,
    PortfolioSnapshot,
    ResearchEvidence,
    RiskPolicy,
    TargetAllocation,
)
from edgecraft.ledger import AuditLedger, DuplicateProposalError
from edgecraft.orchestration import create_trade_proposal, robinhood_protocol

NOW = datetime(2026, 7, 19, 18, 0, tzinfo=UTC)


def snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="agentic-test",
        nickname="Agentic",
        agentic_allowed=True,
        buying_power=500,
        portfolio_value=500,
        as_of=NOW,
        positions=[],
    )


def quotes(as_of: datetime = NOW) -> list[MarketQuote]:
    return [
        MarketQuote(
            symbol="SPY",
            last=600,
            bid=599.9,
            ask=600.1,
            as_of=as_of,
            tradable=True,
            fractionally_tradable=True,
        )
    ]


def evidence() -> ResearchEvidence:
    return ResearchEvidence(
        experiment_id="wf-001",
        strategy="value_tilted_dca",
        data_end=NOW,
        walk_forward_passed=True,
        benchmark_beaten=True,
        cost_stress_passed=True,
        multiple_testing_passed=True,
    )


def test_shadow_proposal_is_approved_but_cannot_place(tmp_path):
    ledger = AuditLedger(tmp_path / "audit.db")
    proposal = create_trade_proposal(
        snapshot(),
        quotes(),
        TargetAllocation(weights={"SPY": 0.1}, rationale="bounded test allocation"),
        RiskPolicy(allowed_symbols=["SPY"]),
        strategy="value_tilted_dca",
        mode="shadow",
        ledger=ledger,
        now=NOW,
    )

    assert proposal.risk.approved_for_review
    assert proposal.orders[0].notional == 50
    assert proposal.robinhood_handoff["status"] == "shadow_only"
    assert not proposal.robinhood_handoff["placement_authorized"]
    assert "research evidence" in proposal.risk.warnings[0]


def test_live_proposal_requires_enabled_policy_and_passing_research(tmp_path):
    blocked = create_trade_proposal(
        snapshot(),
        quotes(),
        TargetAllocation(weights={"SPY": 0.1}, rationale="bounded live allocation"),
        RiskPolicy(allowed_symbols=["SPY"]),
        strategy="value_tilted_dca",
        mode="live",
        now=NOW,
    )
    assert not blocked.risk.approved_for_review
    assert "live trading is disabled by policy" in blocked.risk.violations

    approved = create_trade_proposal(
        snapshot(),
        quotes(),
        TargetAllocation(weights={"SPY": 0.1}, rationale="bounded live allocation"),
        RiskPolicy(allowed_symbols=["SPY"], trading_enabled=True),
        strategy="value_tilted_dca",
        mode="live",
        research=evidence(),
        ledger=AuditLedger(tmp_path / "approved.db"),
        now=NOW,
    )
    assert approved.risk.approved_for_review
    assert approved.robinhood_handoff["status"] == "approved_for_robinhood_review"
    assert not approved.robinhood_handoff["placement_authorized"]


def test_stale_quote_and_duplicate_proposal_are_blocked(tmp_path):
    stale = datetime(2026, 7, 19, 17, 0, tzinfo=UTC)
    proposal = create_trade_proposal(
        snapshot(),
        quotes(stale),
        TargetAllocation(weights={"SPY": 0.1}, rationale="stale test"),
        RiskPolicy(allowed_symbols=["SPY"]),
        strategy="plain_dca",
        mode="shadow",
        now=NOW,
    )
    assert not proposal.risk.approved_for_review
    assert any("quote is stale" in violation for violation in proposal.risk.violations)

    ledger = AuditLedger(tmp_path / "duplicate.db")
    first = create_trade_proposal(
        snapshot(),
        quotes(),
        TargetAllocation(weights={"SPY": 0.1}, rationale="duplicate test"),
        RiskPolicy(allowed_symbols=["SPY"]),
        strategy="plain_dca",
        mode="shadow",
        ledger=ledger,
        now=NOW,
    )
    with pytest.raises(DuplicateProposalError):
        ledger.add_proposal(first)


def test_stale_snapshot_open_order_and_unresolved_ledger_block_review(tmp_path):
    stale_snapshot = snapshot().model_copy(
        update={
            "as_of": datetime(2026, 7, 19, 17, 0, tzinfo=UTC),
            "open_orders": [
                OpenOrderSnapshot(
                    order_id="existing-order",
                    symbol="SPY",
                    side="buy",
                    notional=10,
                    status="queued",
                )
            ],
        }
    )
    blocked = create_trade_proposal(
        stale_snapshot,
        quotes(),
        TargetAllocation(weights={"SPY": 0.1}, rationale="state safety test"),
        RiskPolicy(allowed_symbols=["SPY"]),
        strategy="plain_dca",
        mode="shadow",
        now=NOW,
    )
    assert any("snapshot is stale" in item for item in blocked.risk.violations)
    assert any("open broker order" in item for item in blocked.risk.violations)

    ledger = AuditLedger(tmp_path / "unresolved.db")
    first = create_trade_proposal(
        snapshot(),
        quotes(),
        TargetAllocation(weights={"SPY": 0.1}, rationale="first order"),
        RiskPolicy(allowed_symbols=["SPY"]),
        strategy="plain_dca",
        mode="shadow",
        ledger=ledger,
        now=NOW,
    )
    ledger.record_event(
        first.proposal_id,
        "placed",
        {"order_key": first.orders[0].order_key, "notional": 50},
        occurred_at=NOW,
    )
    later_snapshot = snapshot().model_copy(
        update={"as_of": datetime(2026, 7, 19, 18, 1, tzinfo=UTC)}
    )
    later_quotes = quotes(datetime(2026, 7, 19, 18, 1, tzinfo=UTC))
    second = create_trade_proposal(
        later_snapshot,
        later_quotes,
        TargetAllocation(weights={"SPY": 0.1}, rationale="second order"),
        RiskPolicy(allowed_symbols=["SPY"]),
        strategy="plain_dca",
        mode="shadow",
        ledger=ledger,
        now=datetime(2026, 7, 19, 18, 1, tzinfo=UTC),
    )
    assert any("unresolved placed order" in item for item in second.risk.violations)


def test_ledger_counts_placed_notional_idempotently(tmp_path):
    ledger = AuditLedger(tmp_path / "events.db")
    proposal = create_trade_proposal(
        snapshot(),
        quotes(),
        TargetAllocation(weights={"SPY": 0.1}, rationale="event test"),
        RiskPolicy(allowed_symbols=["SPY"]),
        strategy="plain_dca",
        mode="shadow",
        ledger=ledger,
        now=NOW,
    )
    key = ledger.record_event(
        proposal.proposal_id,
        "placed",
        {"order_key": proposal.orders[0].order_key, "notional": 50},
        occurred_at=NOW,
    )
    assert key.startswith("evt_")
    assert ledger.daily_placed_notional(NOW.date()) == 50
    with pytest.raises(DuplicateProposalError):
        ledger.record_event(
            proposal.proposal_id,
            "placed",
            {"order_key": proposal.orders[0].order_key, "notional": 50},
            occurred_at=NOW,
        )


def test_protocol_names_official_two_phase_tools():
    protocol = robinhood_protocol()
    assert "review_equity_order" in protocol["execution_tools"]
    assert "place_equity_order" in protocol["execution_tools"]
    assert any("same proposal" in item for item in protocol["invariants"])
