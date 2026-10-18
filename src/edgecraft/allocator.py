"""Data-derived virtual sleeve allocation over the single paper ledger.

Lifecycle runs on forecast evidence, which arrives far faster than closed
trades: a playbook whose scored forecasts carry information beyond the market
price is promoted, one whose settled forecasts carry none is frozen. Realized
P&L remains a kill switch.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from edgecraft.playbooks import LoadedPlaybook, PlaybookStatus
from edgecraft.policy import TradingPolicy

ZERO = Decimal("0")
# Estimated trust at or below this means forecasts add nothing to the price.
FREEZE_TRUST = 0.05
PROMOTE_TRUST = 0.10


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
    interim = []
    active_scores: dict[str, Decimal] = {}
    for playbook in playbooks:
        pnl = by_playbook.get(playbook.spec.id, [])[-policy.learning_window :]
        mean = sum(pnl, ZERO) / Decimal(len(pnl)) if pnl else None
        metrics = skill.get(playbook.spec.id, {})
        scored = int(metrics.get("scored", 0))
        estimate = metrics.get("estimated_trust")
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
        elif scored >= policy.promotion_forecasts and estimate is not None:
            # Only settled forecasts may freeze; unresolved drift can only promote.
            if estimate <= FREEZE_TRUST and metrics.get("trust_basis") == "resolution":
                status = PlaybookStatus.FROZEN.value
                reason = "scored forecasts carry no information beyond the market price"
            elif status == PlaybookStatus.INCUBATING.value and estimate >= PROMOTE_TRUST:
                status = PlaybookStatus.ACTIVE.value
        if status == PlaybookStatus.ACTIVE.value:
            score = Decimal(str(max(estimate or 0.0, 0.0))) * Decimal(
                str(math.sqrt(max(1, scored)))
            )
            if score > ZERO:
                active_scores[playbook.spec.id] = score
        interim.append((playbook, pnl, mean, scored, estimate, status, reason))
    score_total = sum(active_scores.values(), ZERO)
    allocations: list[SleeveAllocation] = []
    for playbook, pnl, mean, scored, estimate, status, reason in interim:
        if status == PlaybookStatus.INCUBATING.value:
            weight = policy.incubation_weight
            reason = reason or "incubating until forecast skill is measured"
        elif status == PlaybookStatus.ACTIVE.value and score_total > ZERO:
            weight = min(
                policy.active_weight,
                gross_budget * active_scores.get(playbook.spec.id, ZERO) / score_total,
            )
            reason = reason or "forecasts beat the market; budget scales with trust and sample"
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
                estimated_trust=estimate,
                weight=weight,
                reason=reason,
            )
        )
    # Numerous experiments must share the same fund, never mint extra capital.
    total_weight = sum((item.weight for item in allocations), ZERO)
    if total_weight > gross_budget:
        allocations = [
            replace(item, weight=item.weight * gross_budget / total_weight) for item in allocations
        ]
    return tuple(allocations)
