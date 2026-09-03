"""Data-derived virtual sleeve allocation over the single paper ledger."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from edgecraft.playbooks import LoadedPlaybook, PlaybookStatus

ZERO = Decimal("0")


@dataclass(frozen=True)
class SleeveAllocation:
    playbook_id: str
    status: str
    trade_count: int
    realized_pnl: Decimal
    expectancy: Decimal | None
    lower_confidence_bound: Decimal | None
    weight: Decimal
    reason: str


def _statistics(pnl: list[Decimal]) -> tuple[Decimal | None, Decimal | None]:
    if not pnl:
        return None, None
    mean = sum(pnl, ZERO) / Decimal(len(pnl))
    if len(pnl) < 2:
        return mean, None
    values = [float(item) for item in pnl]
    sample_mean = sum(values) / len(values)
    variance = sum((item - sample_mean) ** 2 for item in values) / (len(values) - 1)
    lower = sample_mean - 1.96 * math.sqrt(variance / len(values))
    return mean, Decimal(str(lower))


def allocate_sleeves(
    playbooks: Sequence[LoadedPlaybook],
    round_trips: Sequence[dict[str, Any]],
    *,
    status_overrides: Mapping[str, str] | None = None,
) -> tuple[SleeveAllocation, ...]:
    status_overrides = status_overrides or {}
    by_playbook: dict[str, list[Decimal]] = defaultdict(list)
    for trade in round_trips:
        by_playbook[str(trade.get("playbook_id", "unassigned"))].append(
            Decimal(str(trade["realized_pnl_after_cost"]))
        )
    allocations: list[SleeveAllocation] = []
    active_scores: dict[str, Decimal] = {}
    interim: list[tuple[LoadedPlaybook, list[Decimal], Decimal | None, Decimal | None, str]] = []
    for playbook in playbooks:
        pnl = by_playbook.get(playbook.spec.id, [])
        mean, lower = _statistics(pnl)
        status = status_overrides.get(playbook.spec.id, playbook.spec.status.value)
        if len(pnl) >= 60 and (lower is None or lower <= ZERO):
            status = PlaybookStatus.RETIRED.value
        elif len(pnl) >= 30 and (lower is None or lower <= ZERO):
            status = PlaybookStatus.FROZEN.value
        elif (
            status == PlaybookStatus.INCUBATING.value and len(pnl) >= 20 and lower and lower > ZERO
        ):
            status = PlaybookStatus.ACTIVE.value
        if status == PlaybookStatus.ACTIVE.value and mean and mean > ZERO:
            active_scores[playbook.spec.id] = mean * Decimal(str(math.sqrt(max(1, len(pnl)))))
        interim.append((playbook, pnl, mean, lower, status))
    score_total = sum(active_scores.values(), ZERO)
    for playbook, pnl, mean, lower, status in interim:
        if status == PlaybookStatus.SHADOW.value:
            weight = ZERO
            reason = "shadow sleeve records packets but does not fill"
        elif status == PlaybookStatus.INCUBATING.value:
            weight = Decimal("0.05")
            reason = "incubation budget"
        elif status == PlaybookStatus.ACTIVE.value and score_total > ZERO:
            weight = min(Decimal("0.40"), active_scores[playbook.spec.id] / score_total)
            reason = "positive after-cost evidence"
        else:
            weight = ZERO
            reason = "no capital while proposed, validated, frozen, or retired"
        allocations.append(
            SleeveAllocation(
                playbook_id=playbook.spec.id,
                status=status,
                trade_count=len(pnl),
                realized_pnl=sum(pnl, ZERO),
                expectancy=mean,
                lower_confidence_bound=lower,
                weight=weight,
                reason=reason,
            )
        )
    return tuple(allocations)
