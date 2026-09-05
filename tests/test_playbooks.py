from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from edgecraft.allocator import allocate_sleeves
from edgecraft.playbooks import LoadedPlaybook, PlaybookSpec, PlaybookStatus, load_playbooks

ROOT = Path(__file__).resolve().parents[1]


def test_starting_playbooks_have_separate_incubation_sleeves() -> None:
    playbooks = load_playbooks(ROOT / "playbooks")
    allocations = allocate_sleeves(playbooks, ())
    assert len(playbooks) == 4
    assert len({item.spec.id for item in playbooks}) == 4
    assert all(item.prompt_hash for item in playbooks)
    assert all(item.weight == Decimal("0.05") for item in allocations)


def test_allocator_scales_evidence_and_freezes_negative_sleeve() -> None:
    playbooks = load_playbooks(ROOT / "playbooks")
    good_id = playbooks[0].spec.id
    bad_id = playbooks[1].spec.id
    trades = [{"playbook_id": good_id, "realized_pnl_after_cost": "2"} for _ in range(20)] + [
        {"playbook_id": bad_id, "realized_pnl_after_cost": "-1"} for _ in range(30)
    ]
    allocations = {item.playbook_id: item for item in allocate_sleeves(playbooks, trades)}
    assert allocations[good_id].status == "active"
    assert allocations[good_id].weight > 0
    assert allocations[bad_id].status == "frozen"
    assert allocations[bad_id].weight == 0


def test_shadow_sleeve_records_but_does_not_receive_capital() -> None:
    spec = PlaybookSpec(
        id="shadow_probe",
        version=1,
        thesis="Prompt experiment",
        universe=("liquid crypto",),
        trigger="volume spike",
        entry_rule="shadow only",
        exit_rule="time stop",
        sizing_hints="none",
        required_evidence_types=("quote",),
        status=PlaybookStatus.SHADOW,
    )
    loaded = LoadedPlaybook(
        spec=spec,
        prompt="shadow prompt",
        prompt_hash="abc",
        directory="playbooks/shadow_probe",
    )
    allocations = allocate_sleeves(
        (loaded,),
        [{"playbook_id": "shadow_probe", "realized_pnl_after_cost": "3"}],
    )
    assert allocations[0].status == "shadow"
    assert allocations[0].weight == Decimal("0")


def test_retirement_is_sticky_and_active_sleeve_without_positive_score_does_not_crash() -> None:
    playbooks = load_playbooks(ROOT / "playbooks")[:3]
    retired, active, profitable = (book.spec.id for book in playbooks)
    trades = [{"playbook_id": retired, "realized_pnl_after_cost": "2"}] * 25
    trades += [{"playbook_id": profitable, "realized_pnl_after_cost": "2"}] * 25
    result = allocate_sleeves(
        playbooks,
        trades,
        status_overrides={retired: "retired", active: "active", profitable: "active"},
    )
    assert result[0].status == "retired"
    assert result[0].weight == 0
    assert result[1].weight == 0
    assert result[2].weight > 0
