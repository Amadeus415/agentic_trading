"""One readable set of paper-trading and learning settings.

These tune research allocation inside the immutable fund mandate. They cannot
change cash, execution costs, accounting, or the simulated-only boundary.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TradingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Trust already shrinks every belief toward the market, so Kelly is not halved again.
    kelly_fraction: Decimal = Field(default=Decimal("1.00"), gt=0, le=1)
    max_driver_weight: Decimal = Field(default=Decimal("0.50"), gt=0)
    max_prediction_weight: Decimal = Field(default=Decimal("0.25"), gt=0, le=1)
    incubation_weight: Decimal = Field(default=Decimal("0.50"), gt=0)
    active_weight: Decimal = Field(default=Decimal("1.00"), gt=0)
    review_days: int = Field(default=1, ge=1)
    review_closed_trades: int = Field(default=10, ge=1)
    learning_window: int = Field(default=20, ge=10)
    # How far sizing trusts a forecast's distance from the market price before
    # measured skill exists, and how many scored forecasts outweigh that prior.
    prior_trust: Decimal = Field(default=Decimal("0.30"), ge=0, le=1)
    trust_prior_weight: int = Field(default=20, ge=1)
    # Scored forecasts a playbook needs before skill promotes or freezes it.
    promotion_forecasts: int = Field(default=30, ge=1)
    # Capital compounds only when it turns over: an after-cost edge must also
    # clear this annualized return over the expected holding period.
    min_annualized_return: Decimal = Field(default=Decimal("0.30"), ge=0)
    # Liquidity is a constraint, not the goal: enough displayed depth to fill.
    min_depth_usd: Decimal = Field(default=Decimal("20"), ge=0)
    # The code-only favorite-bias strategy (control fund).
    baseline_min_price: Decimal = Field(default=Decimal("0.80"), gt=0, lt=1)
    baseline_max_price: Decimal = Field(default=Decimal("0.985"), gt=0, lt=1)
    baseline_max_days: int = Field(default=21, ge=1, le=365)
    baseline_gamma: Decimal = Field(default=Decimal("1.15"), ge=1, le=3)
    baseline_interval_minutes: int = Field(default=30, ge=1)
