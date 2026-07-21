from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from edgecraft.execution_models import DecisionEvidenceItem, MarketQuote, PortfolioSnapshot

RunMode = Literal["shadow", "live"]
RiskLevel = Literal["conservative", "balanced", "aggressive"]
CycleFrequency = Literal["weekly", "market_day"]
DecisionAction = Literal["invest", "hold"]


class Mandate(BaseModel):
    """Versioned owner intent and the hard boundary for an autonomous portfolio."""

    schema_version: str = "edgecraft.mandate.v2"
    mandate_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    goal: str = Field(min_length=10, max_length=2_000)
    enabled: bool = True
    mode: RunMode = "shadow"
    cycle_frequency: CycleFrequency = "weekly"
    weekly_budget: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    daily_budget: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    max_rollover_weeks: int = Field(1, ge=0, le=12)
    risk_level: RiskLevel = "balanced"
    universe: list[str] = Field(min_length=1, max_length=60)
    strategic_weights: dict[str, Decimal]
    max_tactical_tilt: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("0.50"))
    minimum_confidence: Decimal = Field(Decimal("0.55"), ge=Decimal("0"), le=Decimal("1"))
    allow_sells: bool = False
    schedule_weekday: int = Field(0, ge=0, le=6)
    schedule_time: time = time(10, 0)
    timezone: str = "America/New_York"
    benchmark: str = "SPY"
    evaluation_cost_bps: Decimal = Field(Decimal("10"), ge=Decimal("0"), le=Decimal("1000"))
    decision_model: str | None = None
    decision_reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"] | None = (
        None
    )
    policy_path: str
    promotion_source_mandate_id: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_-]{2,63}$",
    )
    research_evidence_path: str | None = None
    external_context_path: str | None = None
    owner_notes: str = Field(default="", max_length=2_000)

    @field_validator("universe")
    @classmethod
    def normalize_universe(cls, value: list[str]) -> list[str]:
        clean = [symbol.strip().upper() for symbol in value if symbol.strip()]
        if not clean:
            raise ValueError("universe must contain at least one symbol")
        if len(clean) != len(set(clean)):
            raise ValueError("universe symbols must be unique")
        return clean

    @field_validator("strategic_weights")
    @classmethod
    def normalize_weights(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        clean = {
            symbol.strip().upper(): Decimal(str(weight))
            for symbol, weight in value.items()
            if symbol.strip()
        }
        if not clean:
            raise ValueError("strategic_weights must not be empty")
        if any(weight < 0 or weight > 1 for weight in clean.values()):
            raise ValueError("strategic weights must be between zero and one")
        if abs(sum(clean.values()) - Decimal("1")) > Decimal("0.000001"):
            raise ValueError("strategic weights must sum to one")
        return clean

    @field_validator("benchmark")
    @classmethod
    def normalize_benchmark(cls, value: str) -> str:
        clean = value.strip().upper()
        if not clean:
            raise ValueError("benchmark cannot be empty")
        return clean

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def coherent_mandate(self) -> Mandate:
        missing = sorted(set(self.strategic_weights) - set(self.universe))
        if missing:
            raise ValueError(f"strategic_weights symbols are outside universe: {missing}")
        if self.allow_sells and self.mode == "live" and self.risk_level == "conservative":
            raise ValueError("conservative live mandates cannot enable autonomous sells")
        if self.mode == "live" and not self.external_context_path:
            raise ValueError("live mandates require external_context_path")
        if self.cycle_frequency == "weekly":
            if self.weekly_budget is None or self.daily_budget is not None:
                raise ValueError("weekly mandates require weekly_budget and no daily_budget")
        else:
            if self.daily_budget is None or self.weekly_budget is not None:
                raise ValueError("market_day mandates require daily_budget and no weekly_budget")
            if self.max_rollover_weeks:
                raise ValueError("market_day mandates cannot roll unused budget forward")
        return self

    @property
    def cycle_budget(self) -> Decimal:
        budget = self.daily_budget if self.cycle_frequency == "market_day" else self.weekly_budget
        if budget is None:
            raise ValueError("mandate cycle budget is missing")
        return budget

    @property
    def tactical_tilt_limit(self) -> Decimal:
        if self.max_tactical_tilt is not None:
            return self.max_tactical_tilt
        return {
            "conservative": Decimal("0.05"),
            "balanced": Decimal("0.15"),
            "aggressive": Decimal("0.30"),
        }[self.risk_level]


class DecisionAllocation(BaseModel):
    symbol: str
    notional: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    conviction: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    rationale: str = Field(min_length=5, max_length=1_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        clean = value.strip().upper()
        if not clean:
            raise ValueError("symbol cannot be empty")
        return clean

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("allocation evidence_ids must be unique")
        return value


class WeeklyDecision(BaseModel):
    """Structured cycle output from the reasoning agent; never execution authority."""

    schema_version: str = "edgecraft.weekly-decision.v2"
    mandate_id: str
    run_id: str
    as_of: datetime
    action: DecisionAction
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    hypothesis: str = Field(min_length=10, max_length=2_000)
    evidence: list[str] = Field(default_factory=list, max_length=30)
    alternatives_considered: list[str] = Field(default_factory=list, max_length=20)
    risks: list[str] = Field(default_factory=list, max_length=30)
    allocations: list[DecisionAllocation] = Field(default_factory=list, max_length=20)
    data_sources: list[str] = Field(default_factory=list, max_length=30)
    context_source_ids: list[str] = Field(default_factory=list, max_length=30)
    evidence_items: list[DecisionEvidenceItem] = Field(default_factory=list, max_length=100)

    @field_validator("as_of")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def action_matches_allocations(self) -> WeeklyDecision:
        if self.action == "invest" and not self.allocations:
            raise ValueError("invest decisions require at least one allocation")
        if self.action == "hold" and self.allocations:
            raise ValueError("hold decisions cannot contain allocations")
        symbols = [allocation.symbol for allocation in self.allocations]
        if len(symbols) != len(set(symbols)):
            raise ValueError("decision allocations must contain unique symbols")
        if len(self.context_source_ids) != len(set(self.context_source_ids)):
            raise ValueError("context_source_ids must be unique")
        evidence_ids = [item.evidence_id for item in self.evidence_items]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("decision evidence IDs must be unique")
        unknown = sorted(
            {
                evidence_id
                for allocation in self.allocations
                for evidence_id in allocation.evidence_ids
                if evidence_id not in set(evidence_ids)
            }
        )
        if unknown:
            raise ValueError(f"allocations cite unknown evidence IDs: {unknown}")
        return self


class AgentCyclePayload(BaseModel):
    """Broker truth plus the model's bounded weekly recommendation."""

    schema_version: str = "edgecraft.agent-cycle-payload.v1"
    observed_at: datetime
    account: PortfolioSnapshot
    quotes: list[MarketQuote] = Field(min_length=1, max_length=60)
    recent_order_summary: list[str] = Field(default_factory=list, max_length=50)
    realized_pnl_summary: str = Field(default="", max_length=2_000)
    decision: WeeklyDecision

    @field_validator("observed_at")
    @classmethod
    def observed_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def symbols_and_times_cohere(self) -> AgentCyclePayload:
        quote_symbols = [quote.symbol for quote in self.quotes]
        if len(quote_symbols) != len(set(quote_symbols)):
            raise ValueError("quotes must contain unique symbols")
        if self.decision.as_of > self.observed_at:
            raise ValueError("decision cannot be newer than the completed observation")
        return self


class ExecutionResult(BaseModel):
    schema_version: str = "edgecraft.execution-result.v1"
    run_id: str
    proposal_id: str
    order_key: str
    status: Literal[
        "aborted",
        "reviewed",
        "placed",
        "filled",
        "partially_filled",
        "rejected",
        "canceled",
        "unknown",
    ]
    broker_order_id: str | None = None
    symbol: str
    side: Literal["buy", "sell"]
    requested_notional: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    filled_notional: Decimal = Field(Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    average_fill_price: Decimal | None = Field(default=None, gt=0)
    fees: Decimal = Field(Decimal("0"), ge=0, max_digits=12, decimal_places=6)
    observed_at: datetime
    review_warnings: list[str] = Field(default_factory=list)
    detail: str = ""

    @field_validator("requested_notional", "filled_notional", mode="before")
    @classmethod
    def normalize_money_to_cents(cls, value):
        return Decimal(str(value)).quantize(Decimal("0.01"))

    @field_validator("fees", mode="before")
    @classmethod
    def normalize_fees(cls, value):
        return Decimal(str(value)).quantize(Decimal("0.000001"))

    @field_validator("observed_at")
    @classmethod
    def result_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(UTC)
