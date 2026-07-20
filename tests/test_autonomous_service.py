import json
from datetime import UTC, datetime, time

from edgecraft.autonomous_service import AutonomousService, StaticObservationRuntime
from edgecraft.autonomy_models import AgentCyclePayload, Mandate
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
