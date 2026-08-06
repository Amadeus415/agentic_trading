"""Focused unit suite for AuditLedger authority surfaces."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from multiprocessing import Process, Queue

import pytest

from edgecraft.autonomy import cycle_key
from edgecraft.autonomy_models import Mandate
from edgecraft.execution_models import (
    DecisionReasoning,
    ProposedOrder,
    RiskDecision,
    TradeProposal,
)
from edgecraft.ledger import AuditLedger

NOW = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)


def _mandate(*, mode: str = "shadow") -> Mandate:
    payload = {
        "mandate_id": "ledger_unit",
        "goal": "Exercise ledger authority unit surfaces for autonomy.",
        "weekly_budget": "10",
        "universe": ["VTI"],
        "strategic_weights": {"VTI": "1"},
        "policy_path": "policy.json",
        "mode": mode,
    }
    if mode == "live":
        payload["external_context_path"] = "context.json"
    return Mandate.model_validate(payload)


def _live_proposal(run_id: str, order_key: str = "order-1") -> TradeProposal:
    return TradeProposal(
        proposal_id=f"prop-{order_key}",
        mandate_id="ledger_unit",
        run_id=run_id,
        created_at=NOW,
        mode="live",
        account_id="agentic-test",
        strategy="agentic_weekly_dca",
        rationale="Bounded unit-test proposal for ledger authority checks.",
        decision_reasoning=DecisionReasoning(
            action="invest",
            confidence="0.8",
            hypothesis="Place a bounded order after deterministic policy approval.",
        ),
        policy_name="test-policy",
        policy_digest="digest",
        snapshot_as_of=NOW,
        orders=[
            ProposedOrder(
                order_key=order_key,
                symbol="VTI",
                side="buy",
                notional=Decimal("10"),
                expected_price=Decimal("100"),
                rationale="Maintain the diversified core allocation.",
                quote_as_of=NOW,
            )
        ],
        risk=RiskDecision(
            approved_for_review=True,
            projected_cash=Decimal("90"),
            projected_weights={"VTI": Decimal("0.1")},
            gross_notional=Decimal("10"),
        ),
        robinhood_handoff={},
    )


def _hold_lock(path: str, mandate_id: str, key: str, ready: Queue, release: Queue) -> None:
    ledger = AuditLedger(path)
    with ledger.cycle_lock(mandate_id, key) as acquired:
        ready.put(acquired)
        release.get()


def test_runtime_event_once_is_idempotent_per_run_and_type(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    mandate = _mandate()
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)

    assert ledger.record_runtime_event_once(
        run_id, "paper_trade_recorded", {"proposal_id": "first"}, now=NOW
    )
    assert not ledger.record_runtime_event_once(
        run_id, "paper_trade_recorded", {"proposal_id": "retry"}, now=NOW + timedelta(seconds=1)
    )

    events = [
        event
        for event in ledger.observability_feed()["runtime_events"]
        if event["event_type"] == "paper_trade_recorded"
    ]
    assert len(events) == 1
    assert events[0]["payload"]["proposal_id"] == "first"


def test_cycle_lock_contention(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    mandate = _mandate()
    key = cycle_key(mandate, NOW)
    ready: Queue = Queue()
    release: Queue = Queue()
    holder = Process(
        target=_hold_lock,
        args=(str(ledger.path), mandate.mandate_id, key, ready, release),
    )
    holder.start()
    assert ready.get(timeout=5) is True
    with ledger.cycle_lock(mandate.mandate_id, key) as acquired:
        assert acquired is False
    release.put(True)
    holder.join(timeout=5)
    assert holder.exitcode == 0
    with ledger.cycle_lock(mandate.mandate_id, key) as acquired:
        assert acquired is True


def test_issue_claim_revoke_permit_lifecycle(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    mandate = _mandate(mode="live")
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)
    proposal = _live_proposal(run_id)
    ledger.add_proposal(proposal)

    token = ledger.issue_permit(
        run_id,
        proposal.proposal_id,
        "order-1",
        constraints={
            "account_id": "agentic-test",
            "symbol": "VTI",
            "side": "buy",
            "dollar_notional": "10",
            "order_type": "market",
            "time_in_force": "gfd",
            "market_hours": "regular_hours",
        },
        now=NOW,
    )
    assert ledger.permit_status(token) == "issued"
    assert ledger.claim_permit(token, now=NOW + timedelta(seconds=1))
    assert ledger.permit_status(token) == "claimed"
    assert not ledger.claim_permit(token, now=NOW + timedelta(seconds=2))

    token2 = ledger.issue_permit(
        run_id,
        proposal.proposal_id,
        "order-1",
        constraints={"account_id": "agentic-test", "symbol": "VTI"},
        now=NOW + timedelta(seconds=3),
    )
    assert ledger.revoke_permit(token2)
    assert ledger.permit_status(token2) == "revoked"
    assert not ledger.claim_permit(token2, now=NOW + timedelta(seconds=4))


def test_claim_permit_fails_when_halted_or_expired(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    mandate = _mandate(mode="live")
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)
    proposal = _live_proposal(run_id)
    ledger.add_proposal(proposal)
    token = ledger.issue_permit(
        run_id,
        proposal.proposal_id,
        "order-1",
        ttl_seconds=60,
        now=NOW,
    )
    ledger.set_trading_halt(True, reason="unit test halt", now=NOW)
    assert not ledger.claim_permit(token, now=NOW + timedelta(seconds=1))
    ledger.set_trading_halt(False, reason="unit test resume", now=NOW)
    # Halt revokes issued permits; re-issue after resume.
    token = ledger.issue_permit(
        run_id,
        proposal.proposal_id,
        "order-1",
        ttl_seconds=60,
        now=NOW,
    )
    assert not ledger.claim_permit(token, now=NOW + timedelta(seconds=120))
    assert ledger.permit_status(token) == "expired"


def test_unresolved_placed_lifecycle(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    mandate = _mandate(mode="live")
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)
    proposal = _live_proposal(run_id)
    ledger.add_proposal(proposal)
    ledger.record_event(
        proposal.proposal_id,
        "placed",
        {
            "order_key": "order-1",
            "notional": "10",
            "broker_order_id": "broker-1",
        },
        occurred_at=NOW,
    )
    assert ledger.unresolved_order_keys() == ["order-1"]
    contexts = ledger.unresolved_order_contexts()
    assert len(contexts) == 1
    assert contexts[0]["order_key"] == "order-1"
    assert contexts[0]["placed_event"]["broker_order_id"] == "broker-1"

    ledger.record_event(
        proposal.proposal_id,
        "filled",
        {
            "order_key": "order-1",
            "notional": "10",
            "filled_notional": "10",
            "broker_order_id": "broker-1",
        },
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert ledger.unresolved_order_keys() == []
    assert ledger.unresolved_order_contexts() == []


def test_run_is_safe_to_retry_side_effect_proof(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    mandate = _mandate(mode="live")
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)
    ledger.update_run(run_id, "failed", detail="transient", now=NOW)
    assert ledger.run_is_safe_to_retry(run_id)

    proposal = _live_proposal(run_id)
    ledger.add_proposal(proposal)
    ledger.issue_permit(run_id, proposal.proposal_id, "order-1", now=NOW)
    assert not ledger.run_is_safe_to_retry(run_id)

    # Confirmed pre-submission rejection with revoked never-claimed permit is retryable.
    ledger2 = AuditLedger(tmp_path / "state2.db")
    run_id2 = ledger2.start_run(mandate, "ledger_unit:other", now=NOW)
    proposal2 = _live_proposal(run_id2, order_key="order-retry")
    ledger2.add_proposal(proposal2)
    token = ledger2.issue_permit(run_id2, proposal2.proposal_id, "order-retry", now=NOW)
    assert ledger2.revoke_permit(token)
    ledger2.record_event(
        proposal2.proposal_id,
        "rejected",
        {
            "order_key": "order-retry",
            "filled_notional": 0,
            "broker_order_id": None,
        },
        occurred_at=NOW,
    )
    ledger2.update_run(run_id2, "failed", detail="rejected before submit", now=NOW)
    assert ledger2.run_is_safe_to_retry(run_id2)

    # Placed order is never retryable.
    ledger3 = AuditLedger(tmp_path / "state3.db")
    run_id3 = ledger3.start_run(mandate, "ledger_unit:placed", now=NOW)
    proposal3 = _live_proposal(run_id3, order_key="order-placed")
    ledger3.add_proposal(proposal3)
    ledger3.record_event(
        proposal3.proposal_id,
        "placed",
        {
            "order_key": "order-placed",
            "notional": "10",
            "broker_order_id": "broker-x",
        },
        occurred_at=NOW,
    )
    ledger3.update_run(run_id3, "failed", detail="left placed", now=NOW)
    assert not ledger3.run_is_safe_to_retry(run_id3)


def test_incident_reconcile_guards(tmp_path):
    ledger = AuditLedger(tmp_path / "state.db")
    mandate = _mandate(mode="live")
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)
    proposal = _live_proposal(run_id)
    ledger.add_proposal(proposal)
    ledger.update_run(run_id, "completed", detail="done", now=NOW)

    with pytest.raises(ValueError, match="only failed runs"):
        ledger.reconcile_failed_run(run_id, reason="broker order independently verified")

    ledger.update_run(run_id, "failed", detail="incident", now=NOW)
    with pytest.raises(ValueError, match="exactly one terminal"):
        ledger.reconcile_failed_run(run_id, reason="broker order independently verified")

    ledger.record_event(
        proposal.proposal_id,
        "placed",
        {
            "order_key": "order-1",
            "notional": "10",
            "broker_order_id": "broker-1",
        },
        occurred_at=NOW,
    )
    ledger.record_event(
        proposal.proposal_id,
        "filled",
        {
            "order_key": "order-1",
            "notional": "10",
            "filled_notional": "10",
            "broker_order_id": "broker-1",
        },
        occurred_at=NOW + timedelta(seconds=1),
    )
    reconciled = ledger.reconcile_failed_run(
        run_id,
        reason="broker order, position, and cash independently verified",
        now=NOW + timedelta(seconds=2),
    )
    assert reconciled["status"] == "completed"
    assert reconciled["payload"]["incident_reconciled"] is True
