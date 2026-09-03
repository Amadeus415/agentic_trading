from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from edgecraft.allocator import SleeveAllocation, allocate_sleeves
from edgecraft.evolution import (
    ChangeKind,
    ChangeProposal,
    Postmortem,
    apply_postmortem,
    reconcile_allocator_lifecycle,
)
from edgecraft.paper_fund import FundMandate, PaperFundLedger
from edgecraft.playbooks import LoadedPlaybook, PlaybookSpec, PlaybookStatus


def test_evolution_records_validated_incubated_and_allocator_promoted_path(tmp_path: Path) -> None:
    walk = tmp_path / "walk.json"
    research = tmp_path / "research.json"
    walk.write_text(
        json.dumps(
            {
                "schema_version": "edgecraft.walk-forward.v1",
                "summary": {"passed": True, "oos_return": 0.08},
            }
        )
    )
    research.write_text(
        json.dumps({"results": [{"metrics": {"deflated_sharpe_probability": 0.97}}]})
    )
    proposal = ChangeProposal(
        proposal_id="p1",
        kind=ChangeKind.PLAYBOOK_PARAM,
        playbook_id="crypto_momentum",
        rationale="Shorten time stop after measured decay.",
        patch={"horizon_hours": 48},
        backtestable=True,
        validation_artifacts=(str(walk), str(research)),
    )
    postmortem = Postmortem(
        generated_at=datetime(2026, 9, 1, tzinfo=UTC),
        fund_id="fund",
        what_worked=("momentum",),
        what_failed=("slow exits",),
        calibration_gaps=("60-70%",),
        suspected_mechanism_failures=("decay",),
        proposals=(proposal,),
    )
    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("fund", FundMandate())
        transitions = apply_postmortem(ledger, postmortem)
        promoted = reconcile_allocator_lifecycle(
            ledger,
            "fund",
            (
                SleeveAllocation(
                    playbook_id="crypto_momentum",
                    status="active",
                    trade_count=20,
                    realized_pnl=Decimal("40"),
                    expectancy=Decimal("2"),
                    lower_confidence_bound=Decimal("1"),
                    weight=Decimal("0.25"),
                    reason="positive evidence",
                ),
            ),
        )
        assert ledger.verify("fund").ok
        statuses = [
            event.payload["to_status"]
            for event in ledger.list_events("fund")
            if event.event_type == "playbook_transition"
        ]
    assert [item["to_status"] for item in transitions] == ["validated", "incubating"]
    assert promoted[0]["to_status"] == "active"
    assert statuses == ["validated", "incubating", "active"]


def test_non_backtestable_prompt_edit_enters_shadow_sleeve(tmp_path: Path) -> None:
    proposal = ChangeProposal(
        proposal_id="p2",
        kind=ChangeKind.RESEARCH_PROMPT_EDIT,
        playbook_id="crypto_momentum",
        rationale="Ask for volume confirmation more explicitly.",
        patch={"prompt": "require volume"},
        backtestable=False,
    )
    postmortem = Postmortem(
        generated_at=datetime(2026, 9, 1, tzinfo=UTC),
        fund_id="fund",
        what_worked=("momentum",),
        what_failed=("slow exits",),
        calibration_gaps=(),
        suspected_mechanism_failures=(),
        proposals=(proposal,),
    )
    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("fund", FundMandate())
        transitions = apply_postmortem(ledger, postmortem)
    assert [item["to_status"] for item in transitions] == ["shadow"]


def test_evolution_rejects_changes_to_human_owned_boundary() -> None:
    with pytest.raises(ValidationError, match="human-owned"):
        ChangeProposal(
            proposal_id="bad",
            kind=ChangeKind.PLAYBOOK_PARAM,
            playbook_id="crypto_momentum",
            rationale="cheat",
            patch={"fee_bps": 0},
            backtestable=True,
        )


def test_persisted_lifecycle_status_controls_allocator() -> None:
    playbook = LoadedPlaybook(
        spec=PlaybookSpec(
            id="test",
            version=1,
            status=PlaybookStatus.INCUBATING,
            thesis="A test playbook.",
            universe=("stocks",),
            trigger="A catalyst occurs.",
            entry_rule="Positive after-cost edge.",
            exit_rule="Thesis invalidation.",
            sizing_hints="Use the deterministic allocator.",
            required_evidence_types=("catalyst",),
        ),
        prompt="Research the catalyst.",
        prompt_hash="abc",
        directory="playbooks/test",
    )

    allocation = allocate_sleeves(
        (playbook,),
        (),
        status_overrides={"test": PlaybookStatus.FROZEN.value},
    )[0]

    assert allocation.status == "frozen"
    assert allocation.weight == 0
