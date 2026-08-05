from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class PositionSnapshot(BaseModel):
    symbol: str
    quantity: Decimal = Field(ge=0)
    market_price: Decimal = Field(gt=0)
    average_cost: Decimal | None = Field(default=None, ge=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        clean = value.strip().upper()
        if not clean:
            raise ValueError("symbol cannot be empty")
        return clean

    @field_validator("quantity", "market_price", "average_cost", mode="before")
    @classmethod
    def coerce_position_money(cls, value):
        if value is None:
            return None
        return Decimal(str(value))

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.market_price


class OpenOrderSnapshot(BaseModel):
    order_id: str = Field(min_length=1)
    symbol: str
    side: Literal["buy", "sell"]
    notional: Decimal | None = Field(default=None, gt=0)
    status: str = Field(min_length=1)

    @field_validator("notional", mode="before")
    @classmethod
    def coerce_open_order_notional(cls, value):
        if value is None:
            return None
        return Decimal(str(value))

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
    buying_power: Decimal = Field(ge=0)
    portfolio_value: Decimal = Field(gt=0)
    as_of: datetime
    positions: list[PositionSnapshot] = Field(default_factory=list)
    open_orders: list[OpenOrderSnapshot] = Field(default_factory=list)
    account_restricted: bool = False
    source: str = "robinhood_mcp"

    @field_validator("buying_power", "portfolio_value", mode="before")
    @classmethod
    def coerce_snapshot_money(cls, value):
        return Decimal(str(value))

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
    last: Decimal = Field(gt=0)
    bid: Decimal | None = Field(default=None, gt=0)
    ask: Decimal | None = Field(default=None, gt=0)
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

    @field_validator("last", "bid", "ask", "average_daily_dollar_volume", mode="before")
    @classmethod
    def coerce_quote_money(cls, value):
        if value is None:
            return None
        return Decimal(str(value))

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


class EvidenceMetric(BaseModel):
    """One normalized value that materially informed the model decision."""

    name: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=2_000)
    unit: str | None = Field(default=None, max_length=100)


class DecisionEvidenceItem(BaseModel):
    """Source-attributed fact or calculation used by the reasoning model."""

    evidence_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{1,127}$")
    category: Literal[
        "broker",
        "quote",
        "fundamental",
        "technical",
        "historical",
        "research",
        "web",
        "regulatory",
        "social",
        "other",
    ]
    source: str = Field(min_length=1, max_length=500)
    symbol: str | None = Field(default=None, max_length=32)
    observed_at: datetime
    source_timestamp: datetime | None = None
    summary: str = Field(min_length=1, max_length=2_000)
    metrics: list[EvidenceMetric] = Field(default_factory=list, max_length=50)
    context_source_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("symbol")
    @classmethod
    def normalize_optional_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip().upper()
        if not clean:
            raise ValueError("evidence symbol cannot be blank")
        return clean

    @field_validator("observed_at", "source_timestamp")
    @classmethod
    def evidence_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("evidence timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("context_source_ids")
    @classmethod
    def unique_context_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence context_source_ids must be unique")
        return value


class DecisionReasoning(BaseModel):
    """Immutable explanation captured before any live execution authority exists."""

    schema_version: str = "edgecraft.decision-reasoning.v2"
    action: Literal["invest", "hold"]
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    hypothesis: str = Field(min_length=10, max_length=2_000)
    thesis_mechanism: str = Field(
        default="The stated hypothesis describes the expected return mechanism.",
        min_length=10,
        max_length=2_000,
    )
    expected_horizon_days: int = Field(default=63, ge=1, le=1_825)
    falsifiers: list[str] = Field(
        default_factory=lambda: ["Evidence no longer supports the stated hypothesis."],
        min_length=1,
        max_length=10,
    )
    referenced_prior_run_ids: list[str] = Field(default_factory=list, max_length=12)
    evidence: list[str] = Field(default_factory=list, max_length=30)
    alternatives_considered: list[str] = Field(default_factory=list, max_length=20)
    risks: list[str] = Field(default_factory=list, max_length=30)
    data_sources: list[str] = Field(default_factory=list, max_length=30)
    context_source_ids: list[str] = Field(default_factory=list, max_length=30)
    evidence_items: list[DecisionEvidenceItem] = Field(default_factory=list, max_length=100)
    allocation_rationales: dict[str, str] = Field(default_factory=dict)
    allocation_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)


class RiskPolicy(BaseModel):
    policy_name: str = "bounded-500-v1"
    trading_enabled: bool = False
    allowed_symbols: list[str] = Field(default_factory=list)
    managed_capital_limit: Decimal = Field(Decimal("500"), gt=0)
    max_order_notional: Decimal = Field(Decimal("50"), gt=0)
    max_daily_notional: Decimal = Field(Decimal("100"), gt=0)
    max_orders_per_day: int = Field(2, ge=1, le=100)
    max_position_weight: Decimal = Field(Decimal("0.40"), gt=0, le=1)
    symbol_groups: dict[str, list[str]] = Field(default_factory=dict)
    max_group_weight: Decimal = Field(Decimal("1"), gt=0, le=1)
    min_cash_reserve: Decimal = Field(Decimal("25"), ge=0)
    min_order_notional: Decimal = Field(Decimal("1"), gt=0)
    max_quote_age_seconds: int = Field(300, ge=1, le=86_400)
    max_snapshot_age_seconds: int = Field(300, ge=1, le=86_400)
    max_research_age_days: int = Field(45, ge=1, le=365)
    max_price_deviation_bps: Decimal = Field(Decimal("100"), ge=0, le=10_000)
    max_spread_bps: Decimal = Field(Decimal("50"), ge=0, le=10_000)
    max_order_adv_fraction: Decimal = Field(Decimal("0.01"), gt=0, le=1)
    allowed_market_sessions: list[Literal["regular", "pre_market", "after_hours"]] = Field(
        default_factory=lambda: ["regular"]
    )
    max_rolling_7d_turnover: Decimal = Field(Decimal("0.50"), gt=0, le=10)
    max_drawdown_fraction: Decimal = Field(Decimal("0.10"), gt=0, le=1)
    min_shadow_cycles_before_live: int = Field(0, ge=0, le=10_000)
    allow_sells: bool = False
    require_research_evidence: bool = True
    require_review: bool = True
    standing_execution_authorization: bool = False

    @field_validator(
        "managed_capital_limit",
        "max_order_notional",
        "max_daily_notional",
        "max_position_weight",
        "max_group_weight",
        "min_cash_reserve",
        "min_order_notional",
        "max_price_deviation_bps",
        "max_spread_bps",
        "max_order_adv_fraction",
        "max_rolling_7d_turnover",
        "max_drawdown_fraction",
        mode="before",
    )
    @classmethod
    def coerce_policy_decimals(cls, value):
        return Decimal(str(value))

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
    notional: Decimal = Field(gt=0)
    expected_price: Decimal = Field(gt=0)
    order_type: Literal["market", "limit"] = "market"
    time_in_force: Literal["gfd", "gtc"] = "gfd"
    limit_price: Decimal | None = Field(default=None, gt=0)
    rationale: str = Field(min_length=1, max_length=1_000)
    quote_as_of: datetime

    @field_validator("notional", "expected_price", "limit_price", mode="before")
    @classmethod
    def coerce_order_money(cls, value):
        if value is None:
            return None
        return Decimal(str(value))

    @model_validator(mode="after")
    def limit_has_price(self) -> ProposedOrder:
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        return self


class RiskDecision(BaseModel):
    approved_for_review: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    projected_cash: Decimal
    projected_weights: dict[str, Decimal]
    gross_notional: Decimal
    spread_bps: dict[str, Decimal] = Field(default_factory=dict)
    rolling_7d_turnover: Decimal | None = None
    drawdown_fraction: Decimal | None = None

    @field_validator(
        "projected_cash",
        "gross_notional",
        "rolling_7d_turnover",
        "drawdown_fraction",
        mode="before",
    )
    @classmethod
    def coerce_decision_money(cls, value):
        if value is None:
            return None
        return Decimal(str(value))

    @field_validator("projected_weights", "spread_bps", mode="before")
    @classmethod
    def coerce_decision_maps(cls, value):
        if value is None:
            return {}
        return {str(key): Decimal(str(item)) for key, item in value.items()}


class TradeProposal(BaseModel):
    schema_version: str = "edgecraft.trade-proposal.v2"
    proposal_id: str
    mandate_id: str | None = None
    run_id: str | None = None
    created_at: datetime
    mode: Literal["shadow", "live"]
    account_id: str
    strategy: str
    rationale: str = Field(min_length=1, max_length=2_000)
    decision_reasoning: DecisionReasoning | None = None
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


class BrokerOrderReceipt(BaseModel):
    """Minimal model-authored broker receipt; Edgecraft owns immutable order identity."""

    schema_version: str = "edgecraft.broker-order-receipt.v1"
    status: Literal[
        "placed",
        "filled",
        "partially_filled",
        "rejected",
        "canceled",
        "unknown",
    ]
    broker_order_id: str | None = None
    filled_notional: Decimal = Field(Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    average_fill_price: Decimal | None = Field(default=None, gt=0)
    fees: Decimal = Field(Decimal("0"), ge=0, max_digits=12, decimal_places=6)
    observed_at: datetime
    warnings: list[str] = Field(default_factory=list, max_length=20)
    detail: str = Field(default="", max_length=2_000)

    @field_validator("filled_notional", mode="before")
    @classmethod
    def normalize_receipt_money(cls, value):
        return Decimal(str(value)).quantize(Decimal("0.01"))

    @field_validator("fees", mode="before")
    @classmethod
    def normalize_receipt_fees(cls, value):
        return Decimal(str(value)).quantize(Decimal("0.000001"))

    @field_validator("observed_at")
    @classmethod
    def receipt_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def broker_identity_for_observed_orders(self) -> BrokerOrderReceipt:
        if self.status in {"placed", "filled", "partially_filled"} and not self.broker_order_id:
            raise ValueError("broker_order_id is required for an observed broker order")
        return self
