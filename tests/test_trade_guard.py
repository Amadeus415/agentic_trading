import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from edgecraft.autonomy import create_weekly_proposal, cycle_key
from edgecraft.autonomy_models import Mandate, WeeklyDecision
from edgecraft.execution_models import MarketQuote, PortfolioSnapshot, RiskPolicy
from edgecraft.ledger import AuditLedger

NOW = datetime.now(UTC)
SCRIPT = Path(__file__).parents[1] / "scripts" / "guard_robinhood_tool.py"
LIVE_POLICY = (
    Path(__file__).parents[1] / "state" / "mandates" / "aggressive-market-day-live.policy.json"
)


def test_tiny_live_policy_allows_one_two_dollar_position(tmp_path):
    mandate = Mandate(
        mandate_id="tiny_live_policy_test",
        goal="Invest one bounded daily amount in an approved symbol.",
        mode="live",
        cycle_frequency="market_day",
        daily_budget="2.00",
        max_rollover_weeks=0,
        universe=["NVDA"],
        strategic_weights={"NVDA": "1"},
        policy_path=str(LIVE_POLICY),
        external_context_path="test-context.json",
    )
    ledger = AuditLedger(tmp_path / "state.db")
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)
    decision = WeeklyDecision(
        mandate_id=mandate.mandate_id,
        run_id=run_id,
        as_of=NOW,
        action="invest",
        confidence="0.8",
        hypothesis="Place one tiny order while keeping the hard daily ceiling.",
        allocations=[
            {
                "symbol": "NVDA",
                "notional": "2.00",
                "conviction": "0.8",
                "rationale": "Exercise the owner-approved tiny-account policy.",
            }
        ],
    )
    snapshot = PortfolioSnapshot(
        account_id="agentic-test",
        agentic_allowed=True,
        buying_power=5,
        portfolio_value=5,
        as_of=NOW,
    )
    quote = MarketQuote(symbol="NVDA", last=200, as_of=NOW)
    policy = RiskPolicy.model_validate_json(LIVE_POLICY.read_text(encoding="utf-8"))

    proposal = create_weekly_proposal(
        mandate,
        decision,
        snapshot,
        [quote],
        policy,
        run_id=run_id,
        cycle_budget=Decimal("2.00"),
        ledger=ledger,
        now=NOW,
    )

    assert proposal.risk.approved_for_review
    assert proposal.risk.projected_weights["NVDA"] == 0.4
    assert policy.max_position_weight == 0.5
    assert policy.max_group_weight == 0.5
    assert policy.max_order_notional == 2
    assert policy.max_daily_notional == 2
    assert policy.max_orders_per_day == 1
    assert not policy.allow_sells


def _setup_live_permit(tmp_path):
    mandate = Mandate(
        mandate_id="guard_test",
        goal="Test a single guarded live placement without bypassing controls.",
        mode="live",
        weekly_budget="10.00",
        universe=["VTI"],
        strategic_weights={"VTI": "1"},
        max_tactical_tilt="0",
        policy_path="test-policy.json",
        external_context_path="test-context.json",
    )
    ledger = AuditLedger(tmp_path / "state.db")
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)
    decision = WeeklyDecision(
        mandate_id=mandate.mandate_id,
        run_id=run_id,
        as_of=NOW,
        action="invest",
        confidence="0.8",
        hypothesis="Place one bounded test order after deterministic validation.",
        allocations=[
            {
                "symbol": "VTI",
                "notional": "10",
                "conviction": "0.8",
                "rationale": "Use the approved index allocation.",
            }
        ],
    )
    snapshot = PortfolioSnapshot(
        account_id="agentic-test",
        agentic_allowed=True,
        buying_power=100,
        portfolio_value=100,
        as_of=NOW,
    )
    quote = MarketQuote(symbol="VTI", last=330, as_of=NOW)
    policy = RiskPolicy(
        policy_name="guard-live",
        trading_enabled=True,
        allowed_symbols=["VTI"],
        managed_capital_limit=1_000,
        max_order_notional=10,
        max_daily_notional=10,
        max_orders_per_day=1,
        max_position_weight=1,
        min_cash_reserve=0,
        require_research_evidence=False,
    )
    proposal = create_weekly_proposal(
        mandate,
        decision,
        snapshot,
        [quote],
        policy,
        run_id=run_id,
        cycle_budget=Decimal("10"),
        ledger=ledger,
        now=NOW,
    )
    order = proposal.orders[0]
    constraints = {
        "account_id": snapshot.account_id,
        "symbol": order.symbol,
        "side": order.side,
        "dollar_notional": order.notional,
        "order_type": order.order_type,
        "time_in_force": order.time_in_force,
    }
    token = ledger.issue_permit(
        run_id,
        proposal.proposal_id,
        order.order_key,
        constraints=constraints,
        now=NOW,
    )
    return ledger, token


def _invoke(ledger, token=None, *, symbol="VTI", omitted=None):
    event = {
        "session_id": "test-session",
        "hook_event_name": "PreToolUse",
        "tool_name": "mcp__robinhood_trading__place_equity_order",
        "tool_input": {
            "account_id": "agentic-test",
            "symbol": symbol,
            "side": "buy",
            "dollar_notional": 10,
            "order_type": "market",
            "time_in_force": "gfd",
        },
    }
    if omitted:
        event["tool_input"].pop(omitted)
    environment = os.environ.copy()
    environment["EDGECRAFT_LEDGER_PATH"] = str(ledger.path)
    if token:
        environment["EDGECRAFT_PERMIT_TOKEN"] = token
    else:
        environment.pop("EDGECRAFT_PERMIT_TOKEN", None)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=True,
        env=environment,
    )
    return json.loads(completed.stdout)["hookSpecificOutput"]


def test_trade_guard_denies_without_a_permit(tmp_path):
    ledger, _ = _setup_live_permit(tmp_path)
    connection = sqlite3.connect(ledger.path)
    stored_account, proposal_payload = connection.execute(
        "SELECT account_id, payload FROM proposals"
    ).fetchone()
    permit_constraints = connection.execute("SELECT constraints FROM permits").fetchone()[0]
    connection.close()
    assert stored_account.startswith("acct_")
    assert "agentic-test" not in proposal_payload
    assert "agentic-test" not in permit_constraints
    result = _invoke(ledger)
    assert result["permissionDecision"] == "deny"
    assert "single-use permit" in result["permissionDecisionReason"]


def test_trade_guard_rejects_mismatch_then_claims_exactly_once(tmp_path):
    ledger, token = _setup_live_permit(tmp_path)
    mismatch = _invoke(ledger, token, symbol="VXUS")
    assert mismatch["permissionDecision"] == "deny"
    assert "symbol" in mismatch["permissionDecisionReason"]

    first = _invoke(ledger, token)
    assert first["permissionDecision"] == "allow"
    duplicate = _invoke(ledger, token)
    assert duplicate["permissionDecision"] == "deny"
    assert "already been used" in duplicate["permissionDecisionReason"]


def test_trade_guard_rejects_missing_required_constraint(tmp_path):
    ledger, token = _setup_live_permit(tmp_path)
    result = _invoke(ledger, token, omitted="account_id")
    assert result["permissionDecision"] == "deny"
    assert "missing permitted account_id_hash" in result["permissionDecisionReason"]

    # A rejected attempt must not consume the single-use permit.
    assert _invoke(ledger, token)["permissionDecision"] == "allow"


def test_kill_switch_revokes_outstanding_permit(tmp_path):
    ledger, token = _setup_live_permit(tmp_path)
    ledger.set_trading_halt(True, reason="test emergency halt")
    result = _invoke(ledger, token)
    assert result["permissionDecision"] == "deny"
    assert "kill switch" in result["permissionDecisionReason"]
