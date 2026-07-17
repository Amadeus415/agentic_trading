from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator

Frequency = Literal["daily", "weekly", "monthly"]


class CostModel(BaseModel):
    commission_per_order: float = Field(0.0, ge=0)
    slippage_bps: float = Field(2.0, ge=0, le=500)
    spread_bps: float = Field(1.0, ge=0, le=500)


class StrategySpec(BaseModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class ValidationConfig(BaseModel):
    bootstrap_samples: int = Field(300, ge=0, le=5_000)
    bootstrap_block_size: int = Field(20, ge=2, le=252)
    cscv_slices: int = Field(8, ge=4, le=16)
    random_seed: int = 7


class BacktestRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["SPY"], min_length=1, max_length=20)
    start: date = date(2015, 1, 1)
    end: date = date(2026, 7, 15)
    initial_capital: float = Field(10_000, gt=0, le=100_000_000)
    contribution_amount: float = Field(250, ge=0, le=1_000_000)
    contribution_frequency: Frequency = "weekly"
    costs: CostModel = Field(default_factory=CostModel)
    strategies: list[StrategySpec] = Field(
        default_factory=lambda: [
            StrategySpec(name="plain_dca"),
            StrategySpec(name="value_tilted_dca"),
            StrategySpec(name="trend_vol_target"),
        ],
        min_length=1,
        max_length=40,
    )
    validation: ValidationConfig = Field(default_factory=ValidationConfig)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        clean = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if not clean:
            raise ValueError("At least one symbol is required")
        if len(set(clean)) != len(clean):
            raise ValueError("Symbols must be unique")
        return clean

    @field_validator("end")
    @classmethod
    def end_after_start(cls, value: date, info):
        start = info.data.get("start")
        if start and value <= start:
            raise ValueError("end must be after start")
        return value


@dataclass(slots=True)
class OrderIntent:
    symbol: str
    side: Literal["buy", "sell"]
    notional: float
    reason: str


@dataclass(slots=True)
class Fill:
    date: pd.Timestamp
    symbol: str
    side: str
    quantity: float
    price: float
    notional: float
    costs: float
    reason: str


@dataclass
class PortfolioState:
    cash: float
    shares: dict[str, float] = field(default_factory=dict)
    external_contributions: float = 0.0
    turnover_notional: float = 0.0

    def value(self, prices: dict[str, float]) -> float:
        return self.cash + sum(self.shares.get(s, 0.0) * p for s, p in prices.items())


@dataclass(slots=True)
class StrategyContext:
    date: pd.Timestamp
    session_index: int
    history: dict[str, pd.DataFrame]
    state: PortfolioState
    prices: dict[str, float]
    contribution_due: bool
    contribution_amount: float


@dataclass
class BacktestResult:
    strategy: str
    params: dict[str, Any]
    daily: pd.DataFrame
    fills: list[Fill]
    metrics: dict[str, float | int | None]
