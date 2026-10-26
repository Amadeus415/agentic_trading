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


def _mandate() -> FundMandate:
    raw = json.loads(Path("examples/fund.mandate.facts.json").read_text())
    return FundMandate.model_validate(raw["mandate"])


def test_experiment_incubates_then_allocator_promotes_it_on_forecast_skill(tmp_path: Path) -> None:
    proposal = ChangeProposal(
        proposal_id="p1",
        kind=ChangeKind.PLAYBOOK_PARAM,
        playbook_id="resolution_reading",
        rationale="Exit earlier when the primary source is delayed.",
        patch={"exit_rule": "Exit after 48 hours without the release."},
    )
    postmortem = Postmortem(
        generated_at=datetime(2026, 10, 18, tzinfo=UTC),
        fund_id="fund",
        what_worked=("rule reading",),
        what_failed=("slow exits",),
        calibration_gaps=(),
        suspected_mechanism_failures=("delayed releases",),
        proposals=(proposal,),
    )
    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("fund", _mandate())
        transitions = apply_postmortem(ledger, postmortem)
        promoted = reconcile_allocator_lifecycle(
            ledger,
            "fund",
            (
                SleeveAllocation(
                    playbook_id=transitions[-1]["playbook_id"],
                    status="active",
                    trade_count=0,
                    realized_pnl=Decimal("0"),
                    expectancy=None,
                    forecasts_scored=40,
                    estimated_trust=0.4,
                    weight=Decimal("0.25"),
                    reason="forecasts beat the market",
                ),
            ),
        )
        assert ledger.verify("fund").ok
        candidate = next(
            book
            for book in effective_playbooks(ledger, "fund")
            if book.spec.id == transitions[-1]["playbook_id"]
        )
        assert candidate.spec.exit_rule == "Exit after 48 hours without the release."
        assert latest_playbook_statuses(ledger, "fund")[candidate.spec.id] == "active"
        assert candidate.spec.id != "resolution_reading"
    assert [item["to_status"] for item in transitions] == ["incubating"]
    assert promoted[0]["to_status"] == "active"
    assert promoted[0]["estimated_trust"] == 0.4


def test_evolution_rejects_changes_to_human_owned_boundary() -> None:
    with pytest.raises(ValidationError, match="human-owned"):
        ChangeProposal(
            proposal_id="bad",
            kind=ChangeKind.PLAYBOOK_PARAM,
            playbook_id="resolution_reading",
            rationale="cheat",
            patch={"fee_bps": 0},
        )


def test_persisted_lifecycle_status_controls_allocator() -> None:
    playbook = LoadedPlaybook(
        spec=PlaybookSpec(
            id="test",
            version=1,
            status=PlaybookStatus.INCUBATING,
            thesis="A test playbook.",
            universe=("binary event contracts",),
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
        playbook_id="resolution_reading",
        rationale="Measured missing volume evidence.",
        patch={"prompt": "Require volume evidence."},
    )
    review = _review(proposal)
    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("fund", _mandate())
        original = next(
            book
            for book in effective_playbooks(ledger, "fund")
            if book.spec.id == "resolution_reading"
        )
        transitions = apply_postmortem(ledger, review)
        count = len(ledger.list_events("fund"))
        assert apply_postmortem(ledger, review) == []
        assert len(ledger.list_events("fund")) == count
        books = {book.spec.id: book for book in effective_playbooks(ledger, "fund")}
        candidate = books[transitions[0]["playbook_id"]]
        assert candidate.prompt == "Require volume evidence."
        assert candidate.spec.status.value == "incubating"
        assert candidate.prompt_hash != original.prompt_hash
        assert books[original.spec.id] == original
        assert ledger.verify("fund").ok


def test_invalid_second_proposal_does_not_partially_complete_review(tmp_path: Path) -> None:
    valid = ChangeProposal(
        proposal_id="retire-1",
        kind="retire_playbook",
        playbook_id="resolution_reading",
        rationale="Poor results",
    )
    invalid = ChangeProposal(
        proposal_id="bad-2",
        kind="research_prompt_edit",
        playbook_id="resolution_reading",
        rationale="Invalid patch",
        patch={"nested": {"fee_bps": 0}},
    )
    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("fund", _mandate())
        count = len(ledger.list_events("fund"))
        with pytest.raises(ValueError, match="unsupported patch"):
            apply_postmortem(ledger, _review(valid, invalid))
        assert len(ledger.list_events("fund")) == count


def test_review_due_daily_or_after_ten_new_closed_trades(tmp_path: Path) -> None:
    from datetime import timedelta

    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize("fund", _mandate())
        anchor = ledger.list_events("fund")[0].occurred_at
        assert not review_status(ledger, "fund", [], now=anchor + timedelta(hours=23))["due"]
        assert review_status(ledger, "fund", [], now=anchor + timedelta(days=1))["due"]
        trades = [{"closed_at": (anchor + timedelta(hours=1)).isoformat()}] * 10
        assert (
            review_status(ledger, "fund", trades, now=anchor + timedelta(hours=2))["reason"]
            == "trade_count"
        )
        assert not review_status(ledger, "fund", trades[:9], now=anchor + timedelta(hours=2))["due"]
        apply_postmortem(ledger, _review())
        assert not review_status(ledger, "fund", [], now=datetime.now(UTC))["due"]
