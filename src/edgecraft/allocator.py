"""Data-derived virtual sleeve allocation over the single paper ledger.

A sleeve is a cap on how much of NAV one playbook may hold, not a slice of the
fund: the mandate's gross limit already keeps experiments from minting capital,
and sizing funds the fastest edges first whichever playbook found them.
Forecast skill gates opinions inside sizing, so lifecycle stays simple: a
playbook incubates until its forecasts can be measured, and realized losses
freeze it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from edgecraft.playbooks import LoadedPlaybook, PlaybookStatus
from edgecraft.policy import TradingPolicy

ZERO = Decimal("0")


@dataclass(frozen=True)
class SleeveAllocation:
    playbook_id: str
    status: str
    trade_count: int
    realized_pnl: Decimal
    expectancy: Decimal | None
    forecasts_scored: int
    estimated_trust: float | None
    weight: Decimal
    reason: str


def allocate_sleeves(
    playbooks: Sequence[LoadedPlaybook],
    round_trips: Sequence[dict[str, Any]],
    *,
    skill: Mapping[str, Mapping[str, Any]] | None = None,
    status_overrides: Mapping[str, str] | None = None,
    policy: TradingPolicy | None = None,
    gross_budget: Decimal = Decimal("1"),
) -> tuple[SleeveAllocation, ...]:
    policy = policy or TradingPolicy()
    status_overrides = status_overrides or {}
    skill = skill or {}
    by_playbook: dict[str, list[Decimal]] = defaultdict(list)
    for trade in round_trips:
        by_playbook[str(trade.get("playbook_id", "unassigned"))].append(
            Decimal(str(trade["realized_pnl_after_cost"]))
        )
    allocations: list[SleeveAllocation] = []
    for playbook in playbooks:
        pnl = by_playbook.get(playbook.spec.id, [])[-policy.learning_window :]
        mean = sum(pnl, ZERO) / Decimal(len(pnl)) if pnl else None
        metrics = skill.get(playbook.spec.id, {})
        scored = int(metrics.get("scored", 0))
        status = status_overrides.get(playbook.spec.id, playbook.spec.status.value)
        reason = None
        if status in {
            PlaybookStatus.RETIRED.value,
            PlaybookStatus.SHADOW.value,
            PlaybookStatus.PROPOSED.value,
            PlaybookStatus.VALIDATED.value,
            PlaybookStatus.FROZEN.value,
        }:
            pass
        elif len(pnl) >= 10 and mean is not None and mean <= ZERO:
            status, reason = PlaybookStatus.FROZEN.value, "nonpositive recent after-cost P&L"
        elif status == PlaybookStatus.INCUBATING.value and scored >= policy.promotion_forecasts:
            status = PlaybookStatus.ACTIVE.value
        if status == PlaybookStatus.INCUBATING.value:
            weight = policy.incubation_weight
            reason = reason or "incubating until enough forecasts settle to measure skill"
        elif status == PlaybookStatus.ACTIVE.value:
            weight = policy.active_weight
            reason = reason or "measured; sizing applies its proven trust and fact accuracy"
        else:
            weight = ZERO
            reason = reason or "no capital while proposed, shadow, frozen, or retired"
        allocations.append(
            SleeveAllocation(
                playbook_id=playbook.spec.id,
                status=status,
                trade_count=len(pnl),
                realized_pnl=sum(pnl, ZERO),
                expectancy=mean,
                forecasts_scored=scored,
                estimated_trust=metrics.get("estimated_trust"),
                weight=min(weight, gross_budget),
                reason=reason,
            )
        )
    return tuple(allocations)
