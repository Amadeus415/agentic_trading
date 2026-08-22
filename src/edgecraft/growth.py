"""Deterministic growth objective and capital-stage policy for the paper fund."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ZERO = Decimal("0")
ONE = Decimal("1")


class GrowthObjective(BaseModel):
    """A measurable objective, not a promise of investment performance."""

    model_config = ConfigDict(extra="forbid")

    target_nav: Decimal = Field(default=Decimal("100000"), gt=0)
    target_horizon_years: Decimal = Field(default=Decimal("10"), gt=0)

    @field_validator("target_nav", "target_horizon_years", mode="before")
    @classmethod
    def _decimal_fields(cls, value: object) -> Decimal:
        return Decimal(str(value))


class GrowthSnapshot(BaseModel):
    """Point-in-time target telemetry supplied to the reasoning agent."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    initial_nav: Decimal
    current_nav: Decimal
    target_nav: Decimal
    target_multiple: Decimal
    remaining_multiple: Decimal
    simple_progress: Decimal
    log_progress: Decimal
    required_annual_return: Decimal
    objective_reached: bool


def growth_snapshot(
    *, initial_nav: Decimal, current_nav: Decimal, objective: GrowthObjective
) -> GrowthSnapshot:
    """Describe progress without allowing the target to override risk policy."""
    target_multiple = objective.target_nav / initial_nav
    remaining_multiple = (
        objective.target_nav / current_nav if current_nav > ZERO else target_multiple
    )
    simple_progress = max(
        ZERO, min(ONE, (current_nav - initial_nav) / (objective.target_nav - initial_nav))
    )

    if current_nav <= initial_nav or target_multiple <= ONE:
        log_progress = ZERO if current_nav < objective.target_nav else ONE
    else:
        # Normalize log(current/initial) by log(target/initial).
        log_progress = max(
            ZERO,
            min(ONE, (current_nav / initial_nav).ln() / target_multiple.ln()),
        )

    # Decimal supports fractional powers on supported Python versions.
    required_annual_return = target_multiple ** (ONE / objective.target_horizon_years) - ONE
    multiple = current_nav / initial_nav if initial_nav > ZERO else ZERO
    if current_nav >= objective.target_nav:
        stage = "objective_reached"
    elif multiple < Decimal("2"):
        stage = "bootstrap"
    elif multiple < Decimal("10"):
        stage = "compound"
    elif multiple < Decimal("50"):
        stage = "scale"
    else:
        stage = "protect"

    return GrowthSnapshot(
        stage=stage,
        initial_nav=initial_nav,
        current_nav=current_nav,
        target_nav=objective.target_nav,
        target_multiple=target_multiple,
        remaining_multiple=remaining_multiple,
        simple_progress=simple_progress,
        log_progress=log_progress,
        required_annual_return=required_annual_return,
        objective_reached=current_nav >= objective.target_nav,
    )
