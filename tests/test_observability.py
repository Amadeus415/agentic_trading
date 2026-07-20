from datetime import UTC, datetime

from edgecraft.autonomy import cycle_key
from edgecraft.autonomy_models import Mandate
from edgecraft.ledger import AuditLedger
from edgecraft.observability import autonomy_health, prometheus_metrics

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
    run_id = ledger.start_run(mandate, cycle_key(mandate, NOW), now=NOW)
    ledger.update_run(run_id, "failed", detail="test failure", now=NOW)
    assert autonomy_health(ledger)["status"] == "degraded"

    ledger.set_trading_halt(True, reason="test halt", now=NOW)
    assert autonomy_health(ledger)["status"] == "halted"
