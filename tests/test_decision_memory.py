from datetime import UTC, datetime, timedelta
from decimal import Decimal

from edgecraft.decision_memory import build_decision_memory
from edgecraft.evaluation import EvaluationObservation, EvaluationState

NOW = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)


class MemorySource:
    def __init__(self):
        self.state = EvaluationState(
            mandate_id="memory_test",
            benchmark="SPY",
            updated_at=NOW,
        )
        self.records = [
            {
                "run_id": "run-prior",
                "recorded_at": (NOW - timedelta(days=2)).isoformat(),
                "payload": {
                    "observation": {
                        "decision": {
                            "action": "invest",
                            "confidence": "0.70",
                            "hypothesis": "Profitable growth can persist longer than consensus expects.",
                            "thesis_mechanism": "Earnings revisions can cause a gradual repricing.",
                            "expected_horizon_days": 126,
                            "falsifiers": ["Two consecutive material guidance cuts."],
                            "allocations": [{"symbol": "AAA", "notional": "2.00"}],
                        }
                    }
                },
            }
        ]
        complete = {
            "agent": Decimal("100"),
            "benchmark": Decimal("100"),
            "strategic": Decimal("100"),
        }
        self.observations = [
            EvaluationObservation(
                run_id="run-prior",
                mandate_id="memory_test",
                cycle_key="first",
                observed_at=NOW - timedelta(days=2),
                benchmark="SPY",
                contribution="2",
                cost_bps="0",
                agent_action="invest",
                prices={"AAA": "10", "SPY": "20"},
                pre_contribution_values=complete,
                post_trade_values=complete,
                period_costs={name: Decimal("0") for name in complete},
            ),
            EvaluationObservation(
                run_id="run-next",
                mandate_id="memory_test",
                cycle_key="second",
                observed_at=NOW - timedelta(days=1),
                benchmark="SPY",
                contribution="2",
                cost_bps="0",
                agent_action="hold",
                prices={"AAA": "10.2", "SPY": "20.2"},
                pre_contribution_values={
                    "agent": Decimal("102"),
                    "benchmark": Decimal("101"),
                    "strategic": Decimal("101"),
                },
                post_trade_values={
                    "agent": Decimal("104"),
                    "benchmark": Decimal("103"),
                    "strategic": Decimal("103"),
                },
                period_costs={name: Decimal("0") for name in complete},
            ),
        ]

    def recent_decision_records(self, mandate_id, *, limit):
        assert mandate_id == "memory_test"
        return self.records[:limit]

    def evaluation_state(self, mandate_id):
        assert mandate_id == "memory_test"
        return self.state

    def evaluation_observations(self, mandate_id, *, limit=10_000):
        assert mandate_id == "memory_test"
        return self.observations[:limit]


def test_decision_memory_is_compact_hashed_and_links_forward_outcomes():
    source = MemorySource()

    first = build_decision_memory(source, "memory_test", generated_at=NOW)
    second = build_decision_memory(source, "memory_test", generated_at=NOW)

    assert first == second
    assert len(first.input_sha256) == 64
    assert first.prior_decisions[0].run_id == "run-prior"
    assert first.prior_decisions[0].thesis_mechanism.startswith("Earnings revisions")
    assert first.prior_decisions[0].next_period_excess_return == 0.01
    assert first.performance.observation_count == 2

    excluded = build_decision_memory(
        source,
        "memory_test",
        generated_at=NOW,
        exclude_run_id="run-prior",
    )
    assert excluded.prior_decisions == []
