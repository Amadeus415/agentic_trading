from decimal import Decimal

from edgecraft.growth import GrowthObjective, growth_snapshot
from edgecraft.paper_fund import FundMandate


def test_growth_snapshot_tracks_compounding_progress_and_stage() -> None:
    snapshot = growth_snapshot(
        initial_nav=Decimal("1000"),
        current_nav=Decimal("10000"),
        objective=GrowthObjective(target_nav="100000", target_horizon_years="10"),
    )

    assert snapshot.stage == "scale"
    assert snapshot.target_multiple == Decimal("100")
    assert snapshot.remaining_multiple == Decimal("10")
    assert abs(snapshot.log_progress - Decimal("0.5")) < Decimal("1e-20")
    assert snapshot.required_annual_return > Decimal("0.58")
    assert snapshot.objective_reached is False


def test_nav_scaled_limits_grow_only_after_nav_is_earned() -> None:
    mandate = FundMandate(
        max_gross_exposure="1500",
        max_gross_exposure_nav_multiple="1.5",
        scale_limits_with_nav=True,
    )

    assert mandate.effective_limit(
        mandate.max_gross_exposure,
        mandate.max_gross_exposure_nav_multiple,
        Decimal("1000"),
    ) == Decimal("1500")
    assert mandate.effective_limit(
        mandate.max_gross_exposure,
        mandate.max_gross_exposure_nav_multiple,
        Decimal("10000"),
    ) == Decimal("15000.0")


def test_fixed_limit_mode_preserves_legacy_behavior() -> None:
    mandate = FundMandate(scale_limits_with_nav=False)
    assert mandate.effective_limit(Decimal("1500"), Decimal("1.5"), Decimal("10000")) == Decimal(
        "1500"
    )
