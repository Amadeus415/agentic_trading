from datetime import UTC, datetime
from stat import S_IMODE

from edgecraft.autonomy import cycle_key
from edgecraft.autonomy_models import Mandate
from edgecraft.execution_models import (
    DecisionReasoning,
    ProposedOrder,
    RiskDecision,
    TradeProposal,
)
from edgecraft.ledger import AuditLedger
from edgecraft.observability import autonomy_health, control_plane_snapshot, prometheus_metrics

NOW = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)


def _mandate() -> Mandate:
    return Mandate(
        mandate_id="metrics_test",
        goal="Exercise sanitized operational metrics for an autonomous mandate.",
        weekly_budget="10",
        universe=["VTI"],
        strategic_weights={"VTI": "1"},
        policy_path="policy.json",
    )


def test_operational_health_and_prometheus_metrics_are_sanitized(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    assert S_IMODE(ledger.path.stat().st_mode) == 0o600
    mandate = _mandate()
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)
    ledger.update_run(run_id, "shadow_complete", detail="safe", now=NOW)

    health = autonomy_health(ledger)
    assert health["status"] == "ready"
    assert health["snapshot"]["runs_by_status"]["shadow_complete"] == 1

    text = prometheus_metrics(ledger)
    assert 'edgecraft_runs_total{status="shadow_complete"} 1' in text
    assert "edgecraft_trading_halted 0" in text
    assert "account" not in text.lower()


def test_health_degrades_on_failure_and_halts_on_kill_switch(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    mandate = _mandate()
    current_time = datetime.now(UTC)
    run_id = ledger.start_run(
        mandate,
        cycle_key(mandate, current_time),
        now=current_time,
    )
    ledger.update_run(run_id, "failed", detail="test failure", now=current_time)
    assert autonomy_health(ledger)["status"] == "degraded"

    ledger.set_trading_halt(True, reason="test halt", now=current_time)
    assert autonomy_health(ledger)["status"] == "halted"


def test_control_plane_snapshot_exposes_runs_without_sensitive_account_data(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    mandate = _mandate()
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)
    ledger.update_run(run_id, "shadow_complete", detail="safe", now=NOW)

    snapshot = control_plane_snapshot(ledger)
    assert snapshot["has_history"] is True
    assert snapshot["runs"][0]["run_id"] == run_id
    assert snapshot["events"][0]["event_type"] == "run_shadow_complete"
    assert snapshot["mandates"][0]["weekly_budget"] == 10
    assert "account_id" not in str(snapshot)


def test_trade_audit_joins_order_authority_broker_events_and_reconciliation(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    mandate = Mandate.model_validate(
        {
            **_mandate().model_dump(),
            "mode": "live",
            "external_context_path": "context.json",
        }
    )
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)
    proposal = TradeProposal(
        proposal_id="proposal-1",
        mandate_id=mandate.mandate_id,
        run_id=run_id,
        created_at=NOW,
        mode="live",
        account_id="private-account-id",
        strategy="test",
        rationale="Place a bounded order after the deterministic policy approves it.",
        decision_reasoning=DecisionReasoning(
            action="invest",
            confidence="0.8",
            hypothesis="Place a bounded order after the deterministic policy approves it.",
        ),
        policy_name="test-policy",
        policy_digest="abc123",
        snapshot_as_of=NOW,
        orders=[
            ProposedOrder(
                order_key="order-1",
                symbol="VTI",
                side="buy",
                notional=10,
                expected_price=100,
                rationale="Maintain the diversified core allocation.",
                quote_as_of=NOW,
            )
        ],
        risk=RiskDecision(
            approved_for_review=True,
            projected_cash=90,
            projected_weights={"VTI": 0.1},
            gross_notional=10,
        ),
        robinhood_handoff={},
    )
    ledger.add_proposal(proposal)
    ledger.issue_permit(
        run_id,
        proposal.proposal_id,
        "order-1",
        constraints={"account_id": "private-account-id", "symbol": "VTI"},
        now=NOW,
    )
    ledger.record_event(
        proposal.proposal_id,
        "placed",
        {
            "order_key": "order-1",
            "symbol": "VTI",
            "side": "buy",
            "notional": 10,
            "broker_order_id": "broker-1",
        },
        occurred_at=NOW,
    )
    ledger.record_event(
        proposal.proposal_id,
        "filled",
        {
            "order_key": "order-1",
            "symbol": "VTI",
            "side": "buy",
            "filled_notional": 10,
            "average_fill_price": 100.01,
            "fees": 0,
            "broker_order_id": "broker-1",
        },
        occurred_at=NOW,
    )
    ledger.update_run(run_id, "completed", detail="broker execution cycle reconciled", now=NOW)

    detail = ledger.trade_audit("order-1")
    assert detail["order"]["status"] == "filled"
    assert detail["reconciliation"]["confirmed_execution"] is True
    assert [item["event_type"] for item in detail["order_events"]] == ["placed", "filled"]
    assert detail["permits"][0]["constraints"]["account_id_hash"].startswith("acct_")
    assert "private-account-id" not in str(detail)
    assert any("No immutable decision packet" in item for item in detail["audit_gaps"])

    snapshot = control_plane_snapshot(ledger)
    assert len(snapshot["trades"]) == 1
    assert snapshot["trades"][0]["confirmed_execution"] is True
