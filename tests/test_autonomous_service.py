import hashlib
import json
import sqlite3
from datetime import UTC, datetime, time
from decimal import Decimal

import pytest

from edgecraft.autonomous_service import AutonomousService, StaticObservationRuntime
from edgecraft.autonomy_models import AgentCyclePayload, ExecutionResult, Mandate
from edgecraft.execution_models import TradeProposal
from edgecraft.ledger import AuditLedger

NOW = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)


def _mandate(policy_path: str) -> Mandate:
    return Mandate(
        mandate_id="service_test",
        goal="Invest a small weekly amount into a diversified index portfolio.",
        weekly_budget="10",
        universe=["VTI", "VXUS"],
        strategic_weights={"VTI": "0.60", "VXUS": "0.40"},
        max_tactical_tilt="0.15",
        schedule_weekday=0,
        schedule_time=time(10),
        timezone="America/New_York",
        policy_path=policy_path,
    )


def _payload(run_id: str = "placeholder", *, action: str = "invest") -> AgentCyclePayload:
    allocations = (
        [
            {
                "symbol": "VTI",
                "notional": "6",
                "conviction": "0.7",
                "rationale": "Maintain the diversified US core.",
            },
            {
                "symbol": "VXUS",
                "notional": "4",
                "conviction": "0.7",
                "rationale": "Maintain international diversification.",
            },
        ]
        if action == "invest"
        else []
    )
    return AgentCyclePayload.model_validate(
        {
            "observed_at": NOW,
            "account": {
                "account_id": "agentic-test",
                "agentic_allowed": True,
                "buying_power": 100,
                "portfolio_value": 100,
                "as_of": NOW,
                "positions": [],
                "open_orders": [],
            },
            "quotes": [
                {"symbol": "VTI", "last": 330, "as_of": NOW},
                {"symbol": "VXUS", "last": 75, "as_of": NOW},
            ],
            "recent_order_summary": [],
            "realized_pnl_summary": "No realized P&L.",
            "decision": {
                "mandate_id": "service_test",
                "run_id": run_id,
                "as_of": NOW,
                "action": action,
                "confidence": "0.7",
                "hypothesis": "Follow the diversified strategic DCA allocation this week.",
                "evidence": ["Quotes and account state are fresh."],
                "alternatives_considered": ["hold cash"],
                "risks": ["market prices can fall"],
                "allocations": allocations,
                "data_sources": ["captured Robinhood MCP fixture"],
            },
        }
    )


def _write_policy(tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "policy_name": "service-shadow",
                "allowed_symbols": ["VTI", "VXUS"],
                "managed_capital_limit": 1000,
                "max_order_notional": 10,
                "max_daily_notional": 10,
                "max_orders_per_day": 2,
                "max_position_weight": 0.75,
                "min_cash_reserve": 0,
                "require_research_evidence": False,
            }
        )
    )
    return policy


def test_shadow_cycle_is_idempotent_and_audited(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy))
    ledger = AuditLedger(tmp_path / "state.db")
    service = AutonomousService(tmp_path, ledger, StaticObservationRuntime(_payload()))

    first = service.run_cycle(mandate, now=NOW)
    assert first["ok"]
    assert first["run"]["status"] == "shadow_complete"
    assert first["run"]["payload"]["gross_notional"] == 10
    assert ledger.status()["proposals"] == 1

    replay = service.run_cycle(mandate, now=NOW)
    assert replay["idempotent_replay"]
    assert replay["run"]["run_id"] == first["run"]["run_id"]
    assert ledger.status()["proposals"] == 1


def test_hold_is_a_successful_terminal_decision(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy))
    ledger = AuditLedger(tmp_path / "state.db")
    service = AutonomousService(tmp_path, ledger, StaticObservationRuntime(_payload(action="hold")))

    result = service.run_cycle(mandate, now=NOW)
    assert result["ok"]
    assert result["run"]["status"] == "held"
    assert result["run"]["payload"]["approved_for_review"] is False


def test_before_schedule_returns_not_due_without_starting_run(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy))
    ledger = AuditLedger(tmp_path / "state.db")
    before = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)
    service = AutonomousService(tmp_path, ledger, StaticObservationRuntime(_payload()))

    result = service.run_cycle(mandate, now=before)
    assert result["status"] == "not_due"
    assert ledger.status()["runs"] == 0


class FailsOnceRuntime(StaticObservationRuntime):
    def __init__(self, payload):
        super().__init__(payload)
        self.calls = 0

    def observe(self, mandate, *, run_id, remaining_budget, ledger_path):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient MCP failure")
        return super().observe(
            mandate,
            run_id=run_id,
            remaining_budget=remaining_budget,
            ledger_path=ledger_path,
        )


def test_side_effect_free_failure_retries_same_cycle_safely(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy))
    ledger = AuditLedger(tmp_path / "state.db")
    runtime = FailsOnceRuntime(_payload())
    service = AutonomousService(tmp_path, ledger, runtime)

    with pytest.raises(RuntimeError, match="transient MCP failure"):
        service.run_cycle(mandate, now=NOW)
    retry = service.run_cycle(mandate, now=NOW)
    assert retry["ok"]
    assert retry["run"]["status"] == "shadow_complete"
    assert ledger.run_attempt_count(retry["run"]["run_id"]) == 2


def test_permit_makes_failed_run_non_retryable(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy)).model_copy(update={"mode": "live"})
    ledger = AuditLedger(tmp_path / "state.db")
    run_id = ledger.start_run(mandate, "service_test:2026-W30", now=NOW)
    proposal = TradeProposal.model_validate(
        {
            "proposal_id": "prop-permit-test",
            "mandate_id": mandate.mandate_id,
            "run_id": run_id,
            "created_at": NOW,
            "mode": "live",
            "account_id": "agentic-test",
            "strategy": "agentic_weekly_dca",
            "rationale": "Test non-retry after authority issuance.",
            "policy_name": "test",
            "snapshot_as_of": NOW,
            "orders": [
                {
                    "order_key": "order-test",
                    "symbol": "VTI",
                    "side": "buy",
                    "notional": 10,
                    "expected_price": 330,
                    "rationale": "Test order.",
                    "quote_as_of": NOW,
                }
            ],
            "risk": {
                "approved_for_review": True,
                "projected_cash": 90,
                "projected_weights": {"VTI": 0.1},
                "gross_notional": 10,
            },
            "robinhood_handoff": {},
        }
    )
    ledger.add_proposal(proposal)
    ledger.issue_permit(run_id, proposal.proposal_id, "order-test", now=NOW)
    ledger.update_run(run_id, "failed", detail="execution uncertainty", now=NOW)
    assert not ledger.run_is_safe_to_retry(run_id)


class FilledLiveRuntime(StaticObservationRuntime):
    def execute_order(
        self,
        mandate,
        proposal,
        order,
        *,
        permit_token,
        ledger_path,
    ):
        del mandate
        token_hash = hashlib.sha256(permit_token.encode()).hexdigest()
        connection = sqlite3.connect(ledger_path)
        connection.execute(
            """
            UPDATE permits SET status = 'claimed', claimed_at = ?
            WHERE token_hash = ? AND status = 'issued'
            """,
            (NOW.isoformat(), token_hash),
        )
        connection.commit()
        connection.close()
        return ExecutionResult(
            run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            order_key=order.order_key,
            status="filled",
            broker_order_id="broker-test-order",
            symbol=order.symbol,
            side=order.side,
            requested_notional=Decimal(str(order.notional)),
            filled_notional=Decimal(str(order.notional)),
            average_fill_price=Decimal("330"),
            observed_at=NOW,
        )


def test_live_cycle_records_guarded_fill_and_spend(tmp_path):
    policy_path = tmp_path / "live-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "policy_name": "service-live",
                "trading_enabled": True,
                "allowed_symbols": ["VTI", "VXUS"],
                "managed_capital_limit": 1000,
                "max_order_notional": 10,
                "max_daily_notional": 10,
                "max_orders_per_day": 2,
                "max_position_weight": 0.75,
                "min_cash_reserve": 0,
                "require_research_evidence": False,
            }
        )
    )
    mandate = _mandate(str(policy_path)).model_copy(update={"mode": "live"})
    ledger = AuditLedger(tmp_path / "state.db")
    service = AutonomousService(tmp_path, ledger, FilledLiveRuntime(_payload()))

    result = service.run_cycle(mandate, now=NOW)
    assert result["ok"]
    assert result["run"]["status"] == "completed"
    assert ledger.daily_placed_notional(NOW.date()) == 10
    assert not ledger.unresolved_order_keys()
    assert ledger.operational_snapshot()["permits_by_status"]["claimed"] == 2
