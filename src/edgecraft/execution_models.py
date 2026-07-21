from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class PositionSnapshot(BaseModel):
    symbol: str
    quantity: float = Field(ge=0)
    market_price: float = Field(gt=0)
    average_cost: float | None = Field(default=None, ge=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        clean = value.strip().upper()
        if not clean:
            raise ValueError("symbol cannot be empty")
        return clean

    @property
    def market_value(self) -> float:
        return self.quantity * self.market_price


class OpenOrderSnapshot(BaseModel):
    order_id: str = Field(min_length=1)
    symbol: str
    side: Literal["buy", "sell"]
    notional: float | None = Field(default=None, gt=0)
    status: str = Field(min_length=1)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        clean = value.strip().upper()
        if not clean:
            raise ValueError("symbol cannot be empty")
        return clean


class PortfolioSnapshot(BaseModel):
    account_id: str = Field(min_length=1)
    nickname: str = ""
    account_type: str = "individual"
    agentic_allowed: bool
    buying_power: float = Field(ge=0)
    portfolio_value: float = Field(gt=0)
    as_of: datetime
    positions: list[PositionSnapshot] = Field(default_factory=list)
    open_orders: list[OpenOrderSnapshot] = Field(default_factory=list)
    account_restricted: bool = False
    source: str = "robinhood_mcp"

    @field_validator("as_of")
    @classmethod
    def snapshot_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return value.astimezone(UTC)

    @field_validator("positions")
    @classmethod
    def unique_positions(cls, value: list[PositionSnapshot]) -> list[PositionSnapshot]:
        symbols = [position.symbol for position in value]
        if len(symbols) != len(set(symbols)):
            raise ValueError("positions must contain unique symbols")
        return value


class MarketQuote(BaseModel):
    symbol: str
    last: float = Field(gt=0)
    bid: float | None = Field(default=None, gt=0)
    ask: float | None = Field(default=None, gt=0)
    as_of: datetime
    tradable: bool = True
    fractionally_tradable: bool = True
    market_session: Literal["regular", "pre_market", "after_hours", "closed", "unknown"] = "unknown"
    average_daily_dollar_volume: Decimal | None = Field(default=None, gt=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        clean = value.strip().upper()
        if not clean:
            raise ValueError("symbol cannot be empty")
        return clean

    @field_validator("as_of")
    @classmethod
    def quote_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_market(self) -> MarketQuote:
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid cannot be greater than ask")
        return self


class TargetAllocation(BaseModel):
    weights: dict[str, float]
    rationale: str = Field(min_length=1)

    @field_validator("weights")
    @classmethod
    def normalize_weights(cls, value: dict[str, float]) -> dict[str, float]:
        clean = {symbol.strip().upper(): float(weight) for symbol, weight in value.items()}
        if not clean or any(not symbol for symbol in clean):
            raise ValueError("at least one non-empty target symbol is required")
        if any(weight < 0 or weight > 1 for weight in clean.values()):
            raise ValueError("target weights must be between 0 and 1")
        if sum(clean.values()) > 1.000001:
            raise ValueError("target weights cannot sum above 1")
        return clean


class ResearchEvidence(BaseModel):
    experiment_id: str = Field(min_length=1)
    strategy: str = Field(min_length=1)
    benchmark: str = "plain_dca"
    data_end: datetime
    walk_forward_passed: bool
    benchmark_beaten: bool
    cost_stress_passed: bool
    multiple_testing_passed: bool
    notes: list[str] = Field(default_factory=list)


class RiskPolicy(BaseModel):
    policy_name: str = "bounded-500-v1"
    trading_enabled: bool = False
    allowed_symbols: list[str] = Field(default_factory=list)
    managed_capital_limit: float = Field(500.0, gt=0)
    max_order_notional: float = Field(50.0, gt=0)
    max_daily_notional: float = Field(100.0, gt=0)
    max_orders_per_day: int = Field(2, ge=1, le=100)
    max_position_weight: float = Field(0.40, gt=0, le=1)
    symbol_groups: dict[str, list[str]] = Field(default_factory=dict)
    max_group_weight: float = Field(1.0, gt=0, le=1)
    min_cash_reserve: float = Field(25.0, ge=0)
    min_order_notional: float = Field(1.0, gt=0)
    max_quote_age_seconds: int = Field(300, ge=1, le=86_400)
    max_snapshot_age_seconds: int = Field(300, ge=1, le=86_400)
    max_research_age_days: int = Field(45, ge=1, le=365)
    max_price_deviation_bps: float = Field(100.0, ge=0, le=10_000)
    max_spread_bps: float = Field(50.0, ge=0, le=10_000)
    max_order_adv_fraction: float = Field(0.01, gt=0, le=1)
    allowed_market_sessions: list[Literal["regular", "pre_market", "after_hours"]] = Field(
        default_factory=lambda: ["regular"]
    )
    max_rolling_7d_turnover: float = Field(0.50, gt=0, le=10)
    max_drawdown_fraction: float = Field(0.10, gt=0, le=1)
    min_shadow_cycles_before_live: int = Field(0, ge=0, le=10_000)
    allow_sells: bool = False
    require_research_evidence: bool = True
    require_review: bool = True
    standing_execution_authorization: bool = False

    @field_validator("allowed_symbols")
    @classmethod
    def normalize_allowed_symbols(cls, value: list[str]) -> list[str]:
        clean = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if len(clean) != len(set(clean)):
            raise ValueError("allowed_symbols must be unique")
        return clean

    @field_validator("symbol_groups")
    @classmethod
    def normalize_symbol_groups(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        normalized: dict[str, list[str]] = {}
        for name, symbols in value.items():
            clean_name = name.strip()
            clean_symbols = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
            if not clean_name or not clean_symbols:
                raise ValueError("symbol_groups require non-empty names and symbols")
            if len(clean_symbols) != len(set(clean_symbols)):
                raise ValueError(f"symbol group {clean_name} contains duplicates")
            normalized[clean_name] = clean_symbols
        return normalized

    @model_validator(mode="after")
    def coherent_limits(self) -> RiskPolicy:
        if self.max_order_notional > self.max_daily_notional:
            raise ValueError("max_order_notional cannot exceed max_daily_notional")
        if self.min_cash_reserve >= self.managed_capital_limit:
            raise ValueError("min_cash_reserve must be below managed_capital_limit")
        if not self.allowed_market_sessions:
            raise ValueError("allowed_market_sessions must not be empty")
        allowed = set(self.allowed_symbols)
        grouped: set[str] = set()
        for name, symbols in self.symbol_groups.items():
            unknown = sorted(set(symbols) - allowed)
            if unknown:
                raise ValueError(f"symbol group {name} contains disallowed symbols: {unknown}")
            overlap = sorted(set(symbols) & grouped)
            if overlap:
                raise ValueError(f"symbols may belong to only one group: {overlap}")
            grouped.update(symbols)
        if not self.require_review and not self.standing_execution_authorization:
            raise ValueError(
                "disabling Robinhood review requires standing_execution_authorization=true"
            )
        return self


class ProposedOrder(BaseModel):
    order_key: str
    symbol: str
    side: Literal["buy", "sell"]
    notional: float = Field(gt=0)
    expected_price: float = Field(gt=0)
    order_type: Literal["market", "limit"] = "market"
    time_in_force: Literal["gfd", "gtc"] = "gfd"
    limit_price: float | None = Field(default=None, gt=0)
    rationale: str
    quote_as_of: datetime

    @model_validator(mode="after")
    def limit_has_price(self) -> ProposedOrder:
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        return self


class RiskDecision(BaseModel):
    approved_for_review: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    projected_cash: float
    projected_weights: dict[str, float]
    gross_notional: float
    spread_bps: dict[str, float] = Field(default_factory=dict)
    rolling_7d_turnover: float | None = None
    drawdown_fraction: float | None = None


class TradeProposal(BaseModel):
    schema_version: str = "edgecraft.trade-proposal.v1"
    proposal_id: str
    mandate_id: str | None = None
    run_id: str | None = None
    created_at: datetime
    mode: Literal["shadow", "live"]
    account_id: str
    strategy: str
    rationale: str
    policy_name: str
    policy_digest: str = ""
    snapshot_as_of: datetime
    orders: list[ProposedOrder]
    risk: RiskDecision
    research: ResearchEvidence | None = None
    robinhood_handoff: dict


class ExecutionPreflight(BaseModel):
    """Fresh, read-only broker truth collected before execution authority exists."""

    schema_version: str = "edgecraft.execution-preflight.v1"
    run_id: str
    proposal_id: str
    order_key: str
    observed_at: datetime
    account: PortfolioSnapshot
    quote: MarketQuote
    review_approved: bool
    review_warnings: list[str] = Field(default_factory=list)
    reviewed_notional: Decimal = Field(gt=0, max_digits=12, decimal_places=2)

    @field_validator("observed_at")
    @classmethod
    def preflight_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def sources_precede_completion(self) -> ExecutionPreflight:
        if self.account.as_of > self.observed_at or self.quote.as_of > self.observed_at:
            raise ValueError("preflight source timestamps cannot exceed observed_at")
        return self
