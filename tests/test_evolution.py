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
    effective_playbooks,
    latest_playbook_statuses,
    reconcile_allocator_lifecycle,
    review_status,
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
        patch={"exit_rule": "Exit after 48 hours."},
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
                    playbook_id=transitions[-1]["playbook_id"],
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
        candidate = next(
            book
            for book in effective_playbooks(ledger, "fund")
            if book.spec.id == transitions[-1]["playbook_id"]
        )
        assert candidate.spec.exit_rule == "Exit after 48 hours."
        assert latest_playbook_statuses(ledger, "fund")[candidate.spec.id] == "active"
        assert candidate.spec.id != "crypto_momentum"
    assert [item["to_status"] for item in transitions] == ["validated", "incubating"]
    assert promoted[0]["to_status"] == "active"


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


def _review(*proposals: ChangeProposal) -> Postmortem:
    return Postmortem(
        generated_at=datetime.now(UTC),
        fund_id="fund",
        what_worked=(),
        what_failed=(),
        calibration_gaps=(),
        suspected_mechanism_failures=(),
        proposals=proposals,
    )


def test_review_replay_is_noop_and_prompt_candidate_preserves_parent(tmp_path: Path) -> None:
    proposal = ChangeProposal(
        proposal_id="prompt-1",
        kind="research_prompt_edit",
        playbook_id="crypto_momentum",
        rationale="Measured missing volume evidence.",
        patch={"prompt": "Require volume evidence."},
        backtestable=False,
    )
    review = _review(proposal)
    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("fund", FundMandate())
        original = next(
            book
            for book in effective_playbooks(ledger, "fund")
            if book.spec.id == "crypto_momentum"
        )
        transitions = apply_postmortem(ledger, review)
        count = len(ledger.list_events("fund"))
        assert apply_postmortem(ledger, review) == []
        assert len(ledger.list_events("fund")) == count
        books = {book.spec.id: book for book in effective_playbooks(ledger, "fund")}
        candidate = books[transitions[0]["playbook_id"]]
        assert candidate.prompt == "Require volume evidence."
        assert candidate.spec.status.value == "shadow"
        assert candidate.prompt_hash != original.prompt_hash
        assert books[original.spec.id] == original
        assert ledger.verify("fund").ok


def test_invalid_second_proposal_does_not_partially_complete_review(tmp_path: Path) -> None:
    valid = ChangeProposal(
        proposal_id="retire-1",
        kind="retire_playbook",
        playbook_id="crypto_momentum",
        rationale="Poor results",
        backtestable=False,
    )
    invalid = ChangeProposal(
        proposal_id="bad-2",
        kind="research_prompt_edit",
        playbook_id="crypto_momentum",
        rationale="Invalid patch",
        patch={"nested": {"fee_bps": 0}},
        backtestable=False,
    )
    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("fund", FundMandate())
        count = len(ledger.list_events("fund"))
        with pytest.raises(ValueError, match="unsupported patch"):
            apply_postmortem(ledger, _review(valid, invalid))
        assert len(ledger.list_events("fund")) == count


def test_review_due_on_seven_days_or_twenty_new_closed_trades(tmp_path: Path) -> None:
    from datetime import timedelta

    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("fund", FundMandate())
        anchor = ledger.list_events("fund")[0].occurred_at
        assert not review_status(ledger, "fund", [], now=anchor + timedelta(days=6))["due"]
        assert review_status(ledger, "fund", [], now=anchor + timedelta(days=7))["due"]
        trades = [{"closed_at": (anchor + timedelta(hours=1)).isoformat()}] * 20
        assert (
            review_status(ledger, "fund", trades, now=anchor + timedelta(hours=2))["reason"]
            == "trade_count"
        )
        assert not review_status(ledger, "fund", trades[:19], now=anchor + timedelta(hours=2))[
            "due"
        ]
        apply_postmortem(ledger, _review())
        assert not review_status(ledger, "fund", [], now=datetime.now(UTC))["due"]
