import sqlite3
from datetime import UTC, datetime, time
from decimal import Decimal

import pytest

from edgecraft.autonomy import (
    available_cycle_budget,
    create_weekly_proposal,
    cycle_due,
    cycle_key,
)
from edgecraft.autonomy_models import Mandate, WeeklyDecision
from edgecraft.execution_models import MarketQuote, PortfolioSnapshot, RiskPolicy
from edgecraft.ledger import AuditLedger, DuplicateProposalError

NOW = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)


def mandate(**updates) -> Mandate:
    payload = {
        "mandate_id": "index_dca",
        "goal": "Invest a bounded weekly contribution into diversified index funds.",
        "weekly_budget": "10.00",
        "risk_level": "balanced",
        "universe": ["VTI", "VXUS", "BND"],
        "strategic_weights": {"VTI": "0.60", "VXUS": "0.25", "BND": "0.15"},
        "schedule_weekday": 0,
        "schedule_time": time(10, 0),
        "timezone": "America/New_York",
        "policy_path": "examples/policy.autonomous-shadow.json",
    }
    payload.update(updates)
    return Mandate(**payload)


def snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="agentic-test",
        agentic_allowed=True,
        buying_power=100,
        portfolio_value=100,
        as_of=NOW,
    )


def quotes() -> list[MarketQuote]:
    return [
        MarketQuote(symbol=symbol, last=price, as_of=NOW)
        for symbol, price in [("VTI", 330), ("VXUS", 75), ("BND", 74)]
    ]


def decision(**updates) -> WeeklyDecision:
    payload = {
        "mandate_id": "index_dca",
        "run_id": "run-1",
        "as_of": NOW,
        "action": "invest",
        "confidence": "0.70",
        "hypothesis": "International equities are relatively attractive while preserving diversification.",
        "evidence": ["VXUS valuation is below the US allocation"],
        "alternatives_considered": ["plain strategic-weight DCA", "hold cash"],
        "risks": ["relative weakness may persist"],
        "allocations": [
            {
                "symbol": "VTI",
                "notional": "6.00",
                "conviction": "0.65",
                "rationale": "Maintain the core allocation.",
            },
            {
                "symbol": "VXUS",
                "notional": "2.50",
                "conviction": "0.75",
                "rationale": "Add at a relative valuation discount.",
            },
            {
                "symbol": "BND",
                "notional": "1.50",
                "conviction": "0.60",
                "rationale": "Preserve the stabilizing sleeve.",
            },
        ],
        "data_sources": ["Robinhood MCP quotes", "Robinhood MCP technical indicators"],
    }
    payload.update(updates)
    return WeeklyDecision(**payload)


def policy(**updates) -> RiskPolicy:
    payload = {
        "policy_name": "weekly-10-shadow",
        "allowed_symbols": ["VTI", "VXUS", "BND"],
        "managed_capital_limit": 10_000,
        "max_order_notional": 10,
        "max_daily_notional": 10,
        "max_orders_per_day": 3,
        "max_position_weight": 0.75,
        "min_cash_reserve": 0,
        "require_research_evidence": False,
    }
    payload.update(updates)
    return RiskPolicy(**payload)


def test_mandate_validates_weights_universe_and_timezone():
    assert mandate().tactical_tilt_limit == Decimal("0.15")
    assert mandate(risk_level="aggressive").tactical_tilt_limit == Decimal("0.30")
    with pytest.raises(ValueError, match="sum to one"):
        mandate(strategic_weights={"VTI": "0.9"})
    with pytest.raises(ValueError, match="outside universe"):
        mandate(strategic_weights={"VTI": "0.6", "VXUS": "0.2", "QQQ": "0.2"})
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        mandate(timezone="Mars/Olympus")


def test_mandate_accepts_large_stock_and_crypto_equity_universe():
    symbols = [f"S{index:03d}" for index in range(200)]
    symbols[0] = "IBIT"
    symbols[1] = "ETHA"
    symbols[2] = "MSTR"
    item = mandate(
        universe=symbols,
        strategic_weights={"IBIT": "0.40", "ETHA": "0.30", "MSTR": "0.30"},
    )
    assert len(item.universe) == 200
    assert {"IBIT", "ETHA", "MSTR"}.issubset(set(item.universe))


def test_cycle_due_and_key_use_mandate_timezone():
    before = datetime(2026, 7, 20, 13, 59, tzinfo=UTC)
    after = datetime(2026, 7, 20, 14, 1, tzinfo=UTC)
    assert not cycle_due(mandate(), before)
    assert cycle_due(mandate(), after)
    assert cycle_key(mandate(), after) == "index_dca:2026-W30"


def test_market_day_cycle_is_daily_weekday_only():
    item = mandate(
        cycle_frequency="market_day",
        weekly_budget=None,
        daily_budget="2.00",
        max_rollover_weeks=0,
        schedule_time=time(7, 15),
        timezone="America/Los_Angeles",
    )
    before = datetime(2026, 7, 20, 14, 14, tzinfo=UTC)
    due = datetime(2026, 7, 20, 14, 15, tzinfo=UTC)
    weekend = datetime(2026, 7, 25, 16, 0, tzinfo=UTC)
    assert not cycle_due(item, before)
    assert cycle_due(item, due)
    assert not cycle_due(item, weekend)
    assert cycle_key(item, due) == "index_dca:2026-07-20"


def test_weekly_proposal_respects_budget_and_tactical_tilt(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    proposal = create_weekly_proposal(
        mandate(),
        decision(),
        snapshot(),
        quotes(),
        policy(),
        run_id="run-1",
        cycle_budget=Decimal("10.00"),
        ledger=ledger,
        now=NOW,
    )
    assert proposal.risk.approved_for_review
    assert proposal.risk.gross_notional == 10
    assert proposal.mandate_id == "index_dca"
    assert proposal.robinhood_handoff["status"] == "shadow_only"
    connection = sqlite3.connect(ledger.path)
    stored_account, stored_payload = connection.execute(
        "SELECT account_id, payload FROM proposals WHERE proposal_id = ?",
        (proposal.proposal_id,),
    ).fetchone()
    connection.close()
    assert stored_account.startswith("acct_")
    assert "agentic-test" not in stored_payload

    over_budget = decision(
        allocations=[
            {
                "symbol": "VTI",
                "notional": "11.00",
                "conviction": "0.9",
                "rationale": "Spend beyond the bounded contribution.",
            }
        ]
    )
    blocked = create_weekly_proposal(
        mandate(max_tactical_tilt="0.50"),
        over_budget,
        snapshot(),
        quotes(),
        policy(max_order_notional=20, max_daily_notional=20),
        run_id="run-1",
        cycle_budget=Decimal("10.00"),
        now=NOW,
    )
    assert not blocked.risk.approved_for_review
    assert any("cycle budget" in item for item in blocked.risk.violations)


def test_low_confidence_and_excess_tilt_are_deterministically_blocked():
    tilted = decision(
        confidence="0.50",
        allocations=[
            {
                "symbol": "VXUS",
                "notional": "10.00",
                "conviction": "0.9",
                "rationale": "Concentrate the entire contribution.",
            }
        ],
    )
    proposal = create_weekly_proposal(
        mandate(),
        tilted,
        snapshot(),
        quotes(),
        policy(),
        run_id="run-1",
        cycle_budget=Decimal("10.00"),
        now=NOW,
    )
    assert not proposal.risk.approved_for_review
    assert any("confidence" in item for item in proposal.risk.violations)
    assert any("strategic+tactical" in item for item in proposal.risk.violations)


def test_subminimum_sleeve_is_dropped_with_an_audit_warning():
    small_sleeve = decision(
        allocations=[
            {
                "symbol": "VTI",
                "notional": "3.00",
                "conviction": "0.7",
                "rationale": "Maintain the core allocation.",
            },
            {
                "symbol": "VXUS",
                "notional": "1.25",
                "conviction": "0.7",
                "rationale": "Maintain international diversification.",
            },
            {
                "symbol": "BND",
                "notional": "0.75",
                "conviction": "0.6",
                "rationale": "Preserve the stabilizing sleeve.",
            },
        ]
    )
    proposal = create_weekly_proposal(
        mandate(),
        small_sleeve,
        snapshot(),
        quotes(),
        policy(),
        run_id="run-1",
        cycle_budget=Decimal("10.00"),
        now=NOW,
    )
    assert proposal.risk.approved_for_review
    assert [order.symbol for order in proposal.orders] == ["VTI", "VXUS"]
    assert any("dropped BND" in warning for warning in proposal.risk.warnings)


def test_run_idempotency_budget_and_kill_switch(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    item = mandate()
    key = cycle_key(item, NOW)
    run_id = ledger.start_run(item, key, now=NOW)
    assert run_id.startswith("run_")
    with pytest.raises(DuplicateProposalError):
        ledger.start_run(item, key, now=NOW)
    assert available_cycle_budget(item, ledger, now=NOW) == Decimal("10.00")
    ledger.set_trading_halt(True, reason="test halt", now=NOW)
    assert ledger.status()["trading_halted"]


def test_rollover_uses_only_prior_recorded_cycles(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    item = mandate(max_rollover_weeks=1)
    prior = datetime(2026, 7, 13, 15, 0, tzinfo=UTC)
    ledger.start_run(item, cycle_key(item, prior), now=prior)
    assert available_cycle_budget(item, ledger, now=NOW) == Decimal("20.00")

    no_rollover = item.model_copy(update={"max_rollover_weeks": 0})
    assert available_cycle_budget(no_rollover, ledger, now=NOW) == Decimal("10.00")
