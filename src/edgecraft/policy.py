"""One readable set of paper-trading and learning settings.

These tune research allocation inside the immutable fund mandate. They cannot
change cash, execution costs, accounting, or the simulated-only boundary.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TradingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kelly_fraction: Decimal = Field(default=Decimal("1.00"), gt=0, le=1)
    max_driver_weight: Decimal = Field(default=Decimal("0.60"), gt=0)
    max_prediction_weight: Decimal = Field(default=Decimal("0.60"), gt=0, le=1)
    incubation_weight: Decimal = Field(default=Decimal("0.60"), gt=0)
    active_weight: Decimal = Field(default=Decimal("1.20"), gt=0)
    review_days: int = Field(default=1, ge=1)
    review_closed_trades: int = Field(default=10, ge=1)
    learning_window: int = Field(default=20, ge=10)
