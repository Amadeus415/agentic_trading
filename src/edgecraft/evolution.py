"""Typed postmortems and evidence-gated playbook lifecycle transitions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edgecraft.allocator import SleeveAllocation
from edgecraft.paper_fund import PaperFundLedger
from edgecraft.playbooks import LoadedPlaybook, PlaybookSpec, load_playbooks


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
        if event.event_type == "postmortem_completed":
            for transition in event.payload.get("transitions", []):
                latest[transition["playbook_id"]] = transition["to_status"]
    return latest


def effective_playbooks(
    ledger: PaperFundLedger, fund_id: str, root: Path = Path("playbooks")
) -> tuple[LoadedPlaybook, ...]:
    """Checked-in seeds plus immutable experiment versions from completed reviews."""
    books = {book.spec.id: book for book in load_playbooks(root)}
    for event in ledger.list_events(fund_id):
        if event.event_type == "postmortem_completed":
            for raw in event.payload.get("playbooks", []):
                book = LoadedPlaybook.model_validate(raw)
                books[book.spec.id] = book
    return tuple(books.values())


def review_status(
    ledger: PaperFundLedger,
    fund_id: str,
    trades: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Review after seven days or twenty additional closed round trips."""
    now = now or datetime.now(UTC)
    events = ledger.list_events(fund_id)
    reviews = [event for event in events if event.event_type == "postmortem_completed"]
    last = reviews[-1] if reviews else None
    anchor = last.occurred_at if last else events[0].occurred_at
    since = sum(
        datetime.fromisoformat(trade["closed_at"].replace("Z", "+00:00")) > anchor
        for trade in trades
    )
    deadline = anchor + timedelta(days=7)
    return {
        "due": now >= deadline or since >= 20,
        "last_review_at": last.occurred_at.isoformat() if last else None,
        "next_review_at": deadline.isoformat(),
        "closed_trades_since_review": since,
        "trade_threshold": 20,
        "reason": "trade_count" if since >= 20 else ("weekly" if now >= deadline else "not_due"),
        "completed_reviews": len(reviews),
    }


def build_postmortem(report: dict[str, Any]) -> Postmortem:
    summary = report["summary"]
    calibration = report["calibration"]
    gaps = tuple(
        f"{item['bucket']} error={item['calibration_error']} n={item['count']}"
        for item in calibration
        if float(item["calibration_error"]) >= 0.10
    )
    from edgecraft.attribution import _aggregate_trades

    trades = report["round_trips"]
    cuts = {
        name: _aggregate_trades([trade for trade in trades if trade["playbook_id"] == name])
        for name in {trade["playbook_id"] for trade in trades}
    }
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
    *,
    root: Path = Path("playbooks"),
) -> list[dict[str, Any]]:
    """Validate the whole review, then append versions and transitions atomically."""
    payload = postmortem.model_dump(mode="json")
    review_id = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    prior_events = ledger.list_events(postmortem.fund_id)
    if any(event.payload.get("review_id") == review_id for event in prior_events):
        return []
    seen = {
        proposal["proposal_id"]
        for event in prior_events
        if event.event_type == "postmortem_completed"
        for proposal in event.payload.get("proposals", [])
    }
    ids = [proposal.proposal_id for proposal in postmortem.proposals]
    if len(ids) != len(set(ids)) or seen.intersection(ids):
        raise ValueError("proposal IDs must be unique and cannot be reused")
    books = {book.spec.id: book for book in effective_playbooks(ledger, postmortem.fund_id, root)}
    transitions: list[dict[str, Any]] = []
    versions: list[dict[str, Any]] = []
    for proposal in postmortem.proposals:
        validation = validate_proposal(proposal)
        parent = books.get(proposal.playbook_id)
        if parent is None and proposal.kind is not ChangeKind.NEW_PLAYBOOK:
            raise ValueError(f"unknown playbook: {proposal.playbook_id}")
        target_id = proposal.playbook_id
        if proposal.kind is ChangeKind.RETIRE_PLAYBOOK:
            if proposal.patch:
                raise ValueError("retirement has no patch")
            targets = ["retired"]
        else:
            allowed = {
                ChangeKind.RESEARCH_PROMPT_EDIT: {"prompt"},
                ChangeKind.UNIVERSE_EDIT: {"universe"},
                ChangeKind.PLAYBOOK_PARAM: {"trigger", "entry_rule", "exit_rule", "sizing_hints"},
                ChangeKind.NEW_PLAYBOOK: {
                    "thesis",
                    "universe",
                    "trigger",
                    "entry_rule",
                    "exit_rule",
                    "sizing_hints",
                    "required_evidence_types",
                    "prompt",
                },
            }[proposal.kind]
            if not proposal.patch or set(proposal.patch) - allowed:
                raise ValueError(f"unsupported patch fields for {proposal.kind.value}")
            spec = parent.spec.model_dump(mode="json") if parent else {}
            prompt = proposal.patch.get("prompt", parent.prompt if parent else "")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("experiment requires a nonempty research prompt")
            digest = hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()[:12]
            target_id = f"{proposal.playbook_id[:48]}_{digest}"
            targets = (
                ["proposed"]
                if not validation.passed
                else ["validated", "incubating"]
                if proposal.backtestable
                else ["shadow"]
            )
            spec.update({key: value for key, value in proposal.patch.items() if key != "prompt"})
            spec.update(
                id=target_id, version=(parent.spec.version + 1 if parent else 1), status=targets[-1]
            )
            version = LoadedPlaybook(
                spec=PlaybookSpec.model_validate(spec),
                prompt=prompt.strip(),
                prompt_hash=hashlib.sha256(prompt.strip().encode()).hexdigest(),
                directory="ledger",
            )
            versions.append(version.model_dump(mode="json"))
        for target in targets:
            transition = {
                "proposal_id": proposal.proposal_id,
                "playbook_id": target_id,
                "parent_playbook_id": proposal.playbook_id,
                "kind": proposal.kind.value,
                "to_status": target,
                "validation": validation.model_dump(mode="json"),
            }
            transitions.append(transition)
    ledger.record_operational_event(
        postmortem.fund_id,
        "postmortem_completed",
        {**payload, "review_id": review_id, "transitions": transitions, "playbooks": versions},
    )
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
