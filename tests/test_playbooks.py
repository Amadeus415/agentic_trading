from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from edgecraft.allocator import allocate_sleeves
from edgecraft.playbooks import LoadedPlaybook, PlaybookSpec, PlaybookStatus, load_playbooks

ROOT = Path(__file__).resolve().parents[1]


def test_starting_playbooks_have_separate_incubation_sleeves() -> None:
    playbooks = load_playbooks(ROOT / "playbooks")
    allocations = allocate_sleeves(playbooks, (), gross_budget=Decimal("3"))
    assert len(playbooks) == 3
    assert len({item.spec.id for item in playbooks}) == 3
    assert all(item.prompt_hash for item in playbooks)
    assert all(item.weight == Decimal("0.50") for item in allocations)
    assert sum(item.weight for item in allocations) == Decimal("1.50")


def test_forecast_skill_promotes_informative_and_freezes_uninformative_playbooks() -> None:
    playbooks = load_playbooks(ROOT / "playbooks")
    good, bad, young = (book.spec.id for book in playbooks)
    skill = {
        good: {"scored": 40, "estimated_trust": 0.4},
        bad: {"scored": 40, "estimated_trust": 0.0, "trust_basis": "resolution"},
        young: {"scored": 5, "estimated_trust": 0.0},
    }
    allocations = {item.playbook_id: item for item in allocate_sleeves(playbooks, (), skill=skill)}
    assert allocations[good].status == "active"
    assert allocations[good].weight > 0
    assert allocations[bad].status == "frozen"
    assert allocations[bad].weight == 0
    assert "no information" in allocations[bad].reason
    assert allocations[young].status == "incubating"


def test_realized_losses_freeze_a_playbook_even_with_good_forecasts() -> None:
    playbooks = load_playbooks(ROOT / "playbooks")
    book = playbooks[0].spec.id
    trades = [{"playbook_id": book, "realized_pnl_after_cost": "-1"} for _ in range(30)]
    skill = {book: {"scored": 40, "estimated_trust": 0.4}}
    allocations = allocate_sleeves(playbooks, trades, skill=skill)
    assert allocations[0].status == "frozen"


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
    result = allocate_sleeves(
        playbooks,
        trades,
        skill={profitable: {"scored": 50, "estimated_trust": 0.3}},
        status_overrides={retired: "retired", active: "active", profitable: "active"},
    )
    assert result[0].status == "retired"
    assert result[0].weight == 0
    assert result[1].weight == 0
    assert result[2].weight > 0


def test_recent_losses_freeze_a_former_winner_and_experiments_share_gross_budget() -> None:
    playbooks = load_playbooks(ROOT / "playbooks")
    winner = playbooks[0].spec.id
    trades = [{"playbook_id": winner, "realized_pnl_after_cost": "100"}] * 100
    trades += [{"playbook_id": winner, "realized_pnl_after_cost": "-2"}] * 20
    allocations = allocate_sleeves(playbooks, trades, gross_budget=Decimal("3"))
    assert allocations[0].status == "frozen"
    assert allocations[0].trade_count == 20
    assert allocations[0].weight == 0
    assert sum(item.weight for item in allocations) <= 3


def test_many_paper_experiments_cannot_multiply_the_fund_budget() -> None:
    from edgecraft.policy import TradingPolicy

    playbooks = load_playbooks(ROOT / "playbooks")
    allocations = allocate_sleeves(
        playbooks, (), gross_budget=Decimal("1"), policy=TradingPolicy(incubation_weight="2")
    )
    assert Decimal("0.999999999999999999999999") <= sum(item.weight for item in allocations) <= 1


def test_unresolved_drift_can_promote_but_never_freeze() -> None:
    playbooks = load_playbooks(ROOT / "playbooks")
    book = playbooks[0].spec.id
    skill = {book: {"scored": 40, "estimated_trust": -0.2, "trust_basis": "drift"}}
    allocations = allocate_sleeves(playbooks, (), skill=skill)
    assert allocations[0].status == "incubating"
