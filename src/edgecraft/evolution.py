"""Typed postmortems and evidence-gated playbook lifecycle transitions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edgecraft.allocator import SleeveAllocation
from edgecraft.paper_fund import PaperFundLedger


class ChangeKind(StrEnum):
    NEW_PLAYBOOK = "new_playbook"
    PLAYBOOK_PARAM = "playbook_param"
    RETIRE_PLAYBOOK = "retire_playbook"
    RESEARCH_PROMPT_EDIT = "research_prompt_edit"
    UNIVERSE_EDIT = "universe_edit"


class ChangeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=128)
    kind: ChangeKind
    playbook_id: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=1, max_length=4000)
    patch: dict[str, Any] = Field(default_factory=dict)
    backtestable: bool
    validation_artifacts: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _protect_human_owned_boundary(self) -> ChangeProposal:
        forbidden = {
            "mandate",
            "accounting",
            "fee_bps",
            "slippage_bps",
            "paper_only",
            "risk_envelope",
            "broker",
        }
        touched = {str(key).lower() for key in self.patch}
        if touched & forbidden:
            raise ValueError("proposal touches the human-owned accounting or safety boundary")
        if (
            self.kind in {ChangeKind.PLAYBOOK_PARAM, ChangeKind.UNIVERSE_EDIT}
            and not self.backtestable
        ):
            raise ValueError(f"{self.kind.value} changes must be backtestable")
        return self


class Postmortem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "edgecraft.postmortem.v1"
    generated_at: datetime
    fund_id: str
    what_worked: tuple[str, ...]
    what_failed: tuple[str, ...]
    calibration_gaps: tuple[str, ...]
    suspected_mechanism_failures: tuple[str, ...]
    proposals: tuple[ChangeProposal, ...] = ()


class ValidationResult(BaseModel):
    passed: bool
    reason: str
    out_of_sample_positive: bool = False
    deflated_sharpe_probability: float | None = None
    artifacts: tuple[str, ...] = ()


def latest_playbook_statuses(ledger: PaperFundLedger, fund_id: str) -> dict[str, str]:
    """Return the latest persisted lifecycle status for each playbook."""
    latest: dict[str, str] = {}
    for event in ledger.list_events(fund_id):
        if event.event_type == "playbook_transition":
            latest[str(event.payload["playbook_id"])] = str(event.payload["to_status"])
    return latest


def build_postmortem(report: dict[str, Any]) -> Postmortem:
    summary = report["summary"]
    calibration = report["calibration"]
    gaps = tuple(
        f"{item['bucket']} error={item['calibration_error']} n={item['count']}"
        for item in calibration
        if float(item["calibration_error"]) >= 0.10
    )
    cuts = report["cuts"]["playbook_id"]
    worked = tuple(
        f"{name}: expectancy {metrics['expectancy_after_cost']}"
        for name, metrics in cuts.items()
        if metrics["expectancy_after_cost"] is not None
        and float(metrics["expectancy_after_cost"]) > 0
    ) or ("No playbook has enough positive attributed evidence yet.",)
    failed = tuple(
        f"{name}: expectancy {metrics['expectancy_after_cost']}"
        for name, metrics in cuts.items()
        if metrics["expectancy_after_cost"] is not None
        and float(metrics["expectancy_after_cost"]) <= 0
    ) or ("No measured negative playbook expectancy.",)
    return Postmortem(
        generated_at=datetime.now(UTC),
        fund_id=report["fund_id"],
        what_worked=worked,
        what_failed=failed,
        calibration_gaps=gaps,
        suspected_mechanism_failures=(
            "Repeated beliefs are scored separately from round-trip P&L.",
            f"Closed trade sample remains {summary['closed_trades']}; do not overfit.",
        ),
        proposals=(),
    )


def validate_proposal(proposal: ChangeProposal) -> ValidationResult:
    if proposal.kind is ChangeKind.RETIRE_PLAYBOOK:
        return ValidationResult(
            passed=True, reason="Retirement reduces risk and needs no backtest."
        )
    if not proposal.backtestable:
        return ValidationResult(
            passed=True,
            reason="Non-backtestable change is eligible only for a shadow sleeve.",
        )
    if not proposal.validation_artifacts:
        return ValidationResult(passed=False, reason="Backtestable proposal has no lab artifacts.")
    oos_positive = False
    dsr: float | None = None
    paths: list[str] = []
    for raw_path in proposal.validation_artifacts:
        path = Path(raw_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        paths.append(str(path.resolve()))
        if payload.get("schema_version") == "edgecraft.walk-forward.v1":
            summary = payload.get("summary", {})
            oos_positive = bool(summary.get("passed")) and float(summary.get("oos_return", 0)) > 0
        for result in payload.get("results", []):
            probability = result.get("metrics", {}).get("deflated_sharpe_probability")
            if probability is not None:
                dsr = max(dsr or 0, float(probability))
    passed = oos_positive and dsr is not None and dsr >= 0.95
    return ValidationResult(
        passed=passed,
        reason=(
            "Positive walk-forward OOS and deflated Sharpe probability >= 0.95."
            if passed
            else "Requires positive walk-forward OOS and deflated Sharpe probability >= 0.95."
        ),
        out_of_sample_positive=oos_positive,
        deflated_sharpe_probability=dsr,
        artifacts=tuple(paths),
    )


def apply_postmortem(
    ledger: PaperFundLedger,
    postmortem: Postmortem,
) -> list[dict[str, Any]]:
    """Record proposals and permitted lifecycle transitions; never edit policy."""
    transitions: list[dict[str, Any]] = []
    ledger.record_operational_event(
        postmortem.fund_id,
        "postmortem_completed",
        postmortem.model_dump(mode="json"),
        occurred_at=postmortem.generated_at,
    )
    for proposal in postmortem.proposals:
        validation = validate_proposal(proposal)
        if proposal.kind is ChangeKind.RETIRE_PLAYBOOK:
            targets = ["retired"]
        elif not validation.passed:
            targets = ["proposed"]
        elif proposal.backtestable:
            targets = ["validated", "incubating"]
        else:
            targets = ["shadow"]
        for target in targets:
            transition = {
                "proposal_id": proposal.proposal_id,
                "playbook_id": proposal.playbook_id,
                "kind": proposal.kind.value,
                "to_status": target,
                "validation": validation.model_dump(mode="json"),
            }
            ledger.record_operational_event(
                postmortem.fund_id,
                "playbook_transition",
                transition,
                occurred_at=postmortem.generated_at,
            )
            transitions.append(transition)
    return transitions


def reconcile_allocator_lifecycle(
    ledger: PaperFundLedger,
    fund_id: str,
    allocations: tuple[SleeveAllocation, ...],
) -> list[dict[str, Any]]:
    """Persist allocator promotions/freezes/retirements when evidence changes status."""
    latest = latest_playbook_statuses(ledger, fund_id)
    transitions: list[dict[str, Any]] = []
    for allocation in allocations:
        prior = latest.get(allocation.playbook_id, "incubating")
        if allocation.status == prior:
            continue
        if allocation.status not in {"active", "frozen", "retired"}:
            continue
        transition = {
            "playbook_id": allocation.playbook_id,
            "from_status": prior,
            "to_status": allocation.status,
            "trade_count": allocation.trade_count,
            "expectancy": (
                str(allocation.expectancy) if allocation.expectancy is not None else None
            ),
            "lower_confidence_bound": (
                str(allocation.lower_confidence_bound)
                if allocation.lower_confidence_bound is not None
                else None
            ),
            "source": "allocator",
        }
        ledger.record_operational_event(fund_id, "playbook_transition", transition)
        transitions.append(transition)
    return transitions
