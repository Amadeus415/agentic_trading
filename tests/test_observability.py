from datetime import UTC, datetime
from stat import S_IMODE

from edgecraft.autonomy import cycle_key
from edgecraft.autonomy_models import Mandate
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
