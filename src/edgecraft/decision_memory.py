from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator

from edgecraft.evaluation import EvaluationObservation, EvaluationState, evaluation_report


class PriorDecisionSummary(BaseModel):
    run_id: str
    recorded_at: datetime
    action: str
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    hypothesis: str
    thesis_mechanism: str
    expected_horizon_days: int = Field(ge=1, le=1_825)
    falsifiers: list[str]
    allocations: dict[str, Decimal]
    next_period_excess_return: float | None = None

    @field_validator("recorded_at")
    @classmethod
    def aware_recorded_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("prior decision recorded_at must include a timezone")
        return value.astimezone(UTC)


class PerformanceMemory(BaseModel):
    status: str
    observation_count: int = Field(ge=0)
    invest_decisions: int = Field(ge=0)
    hold_decisions: int = Field(ge=0)
    agent_excess_return_on_contributions: float | None = None
    information_ratio: float | None = None
    interpretation: str


class DecisionMemorySnapshot(BaseModel):
    """Small, point-in-time feedback packet supplied to the next decision."""

    schema_version: str = "edgecraft.decision-memory.v1"
    generated_at: datetime
    mandate_id: str
    input_sha256: str = Field(min_length=64, max_length=64)
    prior_decisions: list[PriorDecisionSummary] = Field(default_factory=list, max_length=12)
    performance: PerformanceMemory

    @field_validator("generated_at")
    @classmethod
    def aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("decision memory generated_at must include a timezone")
        return value.astimezone(UTC)


class DecisionMemorySource(Protocol):
    def recent_decision_records(self, mandate_id: str, *, limit: int) -> list[dict[str, Any]]: ...

    def evaluation_state(self, mandate_id: str) -> EvaluationState | None: ...

    def evaluation_observations(
        self, mandate_id: str, *, limit: int = 10_000
    ) -> list[EvaluationObservation]: ...


def build_decision_memory(
    source: DecisionMemorySource,
    mandate_id: str,
    *,
    generated_at: datetime,
    limit: int = 8,
    exclude_run_id: str | None = None,
) -> DecisionMemorySnapshot:
    """Build replayable feedback without asking the model to inspect raw private history."""

    observations = source.evaluation_observations(mandate_id)
    outcomes = _next_period_excess_returns(observations)
    records = source.recent_decision_records(mandate_id, limit=max(limit * 3, limit))
    decisions: list[PriorDecisionSummary] = []
    seen_runs: set[str] = set()
    for record in records:
        run_id = str(record["run_id"])
        if run_id == exclude_run_id:
            continue
        if run_id in seen_runs:
            continue
        seen_runs.add(run_id)
        decision = record["payload"]["observation"]["decision"]
        decisions.append(
            PriorDecisionSummary(
                run_id=run_id,
                recorded_at=datetime.fromisoformat(str(record["recorded_at"])),
                action=str(decision["action"]),
                confidence=Decimal(str(decision["confidence"])),
                hypothesis=str(decision["hypothesis"]),
                thesis_mechanism=str(
                    decision.get("thesis_mechanism")
                    or "Historical packet predates the structured thesis mechanism."
                ),
                expected_horizon_days=int(decision.get("expected_horizon_days", 63)),
                falsifiers=list(
                    decision.get("falsifiers")
                    or ["Historical packet predates structured falsifiers."]
                ),
                allocations={
                    str(item["symbol"]): Decimal(str(item["notional"]))
                    for item in decision.get("allocations", [])
                },
                next_period_excess_return=outcomes.get(run_id),
            )
        )
        if len(decisions) >= limit:
            break

    report = evaluation_report(
        source.evaluation_state(mandate_id),
        observations,
    )
    performance = PerformanceMemory(
        status=str(report["status"]),
        observation_count=int(report.get("observation_count", 0)),
        invest_decisions=int(report.get("invest_decisions", 0)),
        hold_decisions=int(report.get("hold_decisions", 0)),
        agent_excess_return_on_contributions=report.get("agent_excess_return_on_contributions"),
        information_ratio=report.get("information_ratio"),
        interpretation=str(
            report.get(
                "minimum_interpretation",
                "No cash-flow-matched performance history exists yet.",
            )
        ),
    )
    digest_payload = {
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "mandate_id": mandate_id,
        "prior_decisions": [item.model_dump(mode="json") for item in decisions],
        "performance": performance.model_dump(mode="json"),
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return DecisionMemorySnapshot(
        generated_at=generated_at,
        mandate_id=mandate_id,
        input_sha256=digest,
        prior_decisions=decisions,
        performance=performance,
    )


def _next_period_excess_returns(
    observations: list[EvaluationObservation],
) -> dict[str, float]:
    ordered = sorted(observations, key=lambda item: item.observed_at)
    outcomes: dict[str, float] = {}
    for current, following in zip(ordered, ordered[1:], strict=False):
        agent_base = current.post_trade_values["agent"]
        benchmark_base = current.post_trade_values["benchmark"]
        if agent_base <= 0 or benchmark_base <= 0:
            continue
        agent_return = float(following.pre_contribution_values["agent"] / agent_base - 1)
        benchmark_return = float(
            following.pre_contribution_values["benchmark"] / benchmark_base - 1
        )
        outcomes[current.run_id] = agent_return - benchmark_return
    return outcomes
