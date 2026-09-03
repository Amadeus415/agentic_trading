"""Deterministic, append-only $1,000 paper-fund accounting core.

Paper-only by construction: no broker imports, no live execution path, and no
cash injection after one-time capitalization. State is recoverable from the
latest completed cycle; audit events are hash-chained and immutable in SQLite.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from edgecraft.growth import GrowthObjective

# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------

BPS_DIVISOR = Decimal("10000")
ZERO = Decimal("0")
ONE = Decimal("1")
GENESIS_HASH = "0" * 64
INSTRUMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,127}$")
BUSY_TIMEOUT_MS = 30_000
MAX_SCHEDULED_HYPOTHESIS_HORIZON_HOURS = 72


class PaperFundError(Exception):
    """Base error for the paper fund domain."""

    def __init__(self, message: str, *, audit: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.audit = audit or {}


class PaperFundValidationError(PaperFundError, ValueError):
    """Raised when a request fails validation or risk policy."""


class PaperFundIdempotencyError(PaperFundError, ValueError):
    """Raised when a cycle_key is reused with a different request payload."""


class PaperFundIntegrityError(PaperFundError, RuntimeError):
    """Raised when audit chain or accounting verification fails."""


class AssetClass(StrEnum):
    STOCK = "stock"
    CRYPTO = "crypto"
    PREDICTION = "prediction"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"


class DecisionAction(StrEnum):
    TRADE = "trade"
    HOLD = "hold"


class HypothesisStance(StrEnum):
    LONG = "long"
    SHORT = "short"
    EXIT = "exit"


class QuoteStatus(StrEnum):
    OPEN = "open"
    SETTLED = "settled"


class BookLevel(BaseModel):
    """One public CLOB or displayed-book level used for honest simulated fills."""

    model_config = ConfigDict(extra="forbid")

    price: Decimal = Field(gt=0)
    size: Decimal = Field(gt=0)

    @field_validator("price", "size", mode="before")
    @classmethod
    def _dec(cls, value: Any) -> Decimal:
        return _as_decimal(value)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _ensure_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso_z(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        raise TypeError(f"cannot convert {type(value).__name__} to Decimal")
    return Decimal(str(value))


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _iso_z(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, default=_json_default, sort_keys=True, separators=(",", ":"))


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_instrument_id(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or not INSTRUMENT_ID_RE.fullmatch(cleaned):
        raise ValueError(
            "instrument_id must be 1-128 chars of alphanumerics plus . _ : / - "
            "and start with alphanumeric"
        )
    return cleaned


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class FundMandate(BaseModel):
    """Paper-only fund mandate with deterministic risk and data limits."""

    model_config = ConfigDict(extra="forbid")

    initial_cash: Decimal = Field(default=Decimal("1000.00"), gt=0)
    supported_asset_classes: tuple[AssetClass, ...] = (
        AssetClass.STOCK,
        AssetClass.CRYPTO,
        AssetClass.PREDICTION,
    )
    fee_bps: Decimal = Field(default=Decimal("5"), ge=0)
    slippage_bps: Decimal = Field(default=Decimal("10"), ge=0)
    quote_freshness: dict[AssetClass, timedelta] = Field(
        default_factory=lambda: {
            AssetClass.STOCK: timedelta(minutes=15),
            AssetClass.CRYPTO: timedelta(minutes=5),
            AssetClass.PREDICTION: timedelta(hours=1),
        }
    )
    max_source_age: dict[AssetClass, timedelta] = Field(
        default_factory=lambda: {
            AssetClass.STOCK: timedelta(days=4),
            AssetClass.CRYPTO: timedelta(minutes=10),
            AssetClass.PREDICTION: timedelta(minutes=30),
        }
    )
    max_gross_exposure: Decimal = Field(default=Decimal("2000"), gt=0)
    max_absolute_net_exposure: Decimal = Field(default=Decimal("1500"), gt=0)
    max_short_exposure: Decimal = Field(default=Decimal("500"), ge=0)
    max_single_position_weight: Decimal = Field(default=Decimal("0.40"), gt=0, le=1)
    max_cycle_turnover: Decimal = Field(default=Decimal("1000"), ge=0)
    max_order_count: int = Field(default=20, ge=0)
    max_drawdown: Decimal = Field(default=Decimal("0.25"), ge=0, le=1)
    growth_objective: GrowthObjective = Field(default_factory=GrowthObjective)
    scale_limits_with_nav: bool = True
    max_gross_exposure_nav_multiple: Decimal = Field(default=Decimal("1.50"), gt=0)
    max_absolute_net_exposure_nav_multiple: Decimal = Field(default=Decimal("1.00"), gt=0)
    max_short_exposure_nav_multiple: Decimal = Field(default=Decimal("0.50"), ge=0)
    max_cycle_turnover_nav_multiple: Decimal = Field(default=Decimal("1.00"), ge=0)

    @field_validator("initial_cash", "fee_bps", "slippage_bps", mode="before")
    @classmethod
    def _dec_fields(cls, value: Any) -> Decimal:
        return _as_decimal(value)

    @field_validator(
        "max_gross_exposure",
        "max_absolute_net_exposure",
        "max_short_exposure",
        "max_single_position_weight",
        "max_cycle_turnover",
        "max_drawdown",
        "max_gross_exposure_nav_multiple",
        "max_absolute_net_exposure_nav_multiple",
        "max_short_exposure_nav_multiple",
        "max_cycle_turnover_nav_multiple",
        mode="before",
    )
    @classmethod
    def _dec_limits(cls, value: Any) -> Decimal:
        return _as_decimal(value)

    @field_validator("supported_asset_classes")
    @classmethod
    def _nonempty_classes(cls, value: Sequence[AssetClass]) -> tuple[AssetClass, ...]:
        if not value:
            raise ValueError("supported_asset_classes must be non-empty")
        return tuple(value)

    @field_validator("quote_freshness", "max_source_age", mode="before")
    @classmethod
    def _normalize_freshness(cls, value: Any) -> dict[AssetClass, timedelta]:
        if not isinstance(value, Mapping):
            raise TypeError("quote_freshness must be a mapping")
        out: dict[AssetClass, timedelta] = {}
        for key, raw in value.items():
            asset = AssetClass(key) if not isinstance(key, AssetClass) else key
            if isinstance(raw, timedelta):
                out[asset] = raw
            elif isinstance(raw, (int, float, Decimal, str)):
                out[asset] = timedelta(seconds=float(raw))
            else:
                raise TypeError(f"unsupported freshness value for {asset}")
            if out[asset].total_seconds() <= 0:
                raise ValueError(f"quote freshness for {asset} must be positive")
        return out

    @model_validator(mode="after")
    def _freshness_covers_classes(self) -> Self:
        for field_name in ("quote_freshness", "max_source_age"):
            values = getattr(self, field_name)
            missing = [ac for ac in self.supported_asset_classes if ac not in values]
            if missing:
                raise ValueError(f"{field_name} missing asset classes: {missing}")
        return self

    @field_serializer("quote_freshness", "max_source_age")
    def _serialize_freshness(self, value: Mapping[AssetClass, timedelta]) -> dict[str, float]:
        """Persist timedeltas as portable seconds rather than ISO duration strings."""
        return {asset.value: duration.total_seconds() for asset, duration in value.items()}

    def freshness_for(self, asset_class: AssetClass) -> timedelta:
        return self.quote_freshness[asset_class]

    def source_age_for(self, asset_class: AssetClass) -> timedelta:
        return self.max_source_age[asset_class]

    def effective_limit(
        self, absolute_floor: Decimal, nav_multiple: Decimal, nav: Decimal
    ) -> Decimal:
        """Scale a risk ceiling with earned NAV, never with injected capital."""
        if not self.scale_limits_with_nav:
            return absolute_floor
        return max(absolute_floor, nav * nav_multiple)


class FundQuote(BaseModel):
    """Market quote with provenance used for marks and execution."""

    model_config = ConfigDict(extra="forbid")

    quote_id: str = Field(min_length=1, max_length=128)
    instrument_id: str = Field(min_length=1, max_length=128)
    asset_class: AssetClass
    price: Decimal
    observed_at: datetime
    source_timestamp: datetime
    source_name: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=2000)
    status: QuoteStatus = QuoteStatus.OPEN
    bids: tuple[BookLevel, ...] = ()
    asks: tuple[BookLevel, ...] = ()

    @field_validator("instrument_id")
    @classmethod
    def _instrument(cls, value: str) -> str:
        return _validate_instrument_id(value)

    @field_validator("price", mode="before")
    @classmethod
    def _price_dec(cls, value: Any) -> Decimal:
        return _as_decimal(value)

    @field_validator("observed_at", "source_timestamp")
    @classmethod
    def _obs_utc(cls, value: datetime) -> datetime:
        return _ensure_utc(value, "observed_at")

    @model_validator(mode="after")
    def _price_rules(self) -> Self:
        if self.source_timestamp > self.observed_at + timedelta(minutes=1):
            raise ValueError("source_timestamp cannot be after observed_at")
        if self.asset_class in (AssetClass.STOCK, AssetClass.CRYPTO):
            if self.price <= ZERO:
                raise ValueError(f"{self.asset_class} quote price must be > 0")
        elif self.asset_class is AssetClass.PREDICTION:
            if self.price < ZERO or self.price > ONE:
                raise ValueError("prediction quote price must be in [0, 1]")
            if self.status is QuoteStatus.OPEN and (self.price == ZERO or self.price == ONE):
                raise ValueError("open prediction quotes cannot be exactly 0 or 1")
            if self.status is QuoteStatus.SETTLED and self.price not in (ZERO, ONE):
                raise ValueError("settled prediction quotes must be exactly 0 or 1")
        if self.status is QuoteStatus.SETTLED and self.asset_class is not AssetClass.PREDICTION:
            raise ValueError("only prediction quotes may be settled")
        return self


class FundEvidence(BaseModel):
    """Provenance-preserving research evidence item."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=128)
    observed_at: datetime
    source_timestamp: datetime
    source_name: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=2000)
    claim: str = Field(min_length=1, max_length=2000)
    summary: str = Field(default="", max_length=4000)
    instrument_ids: tuple[str, ...] = ()
    content: str = Field(default="", max_length=20000)

    @field_validator("observed_at", "source_timestamp")
    @classmethod
    def _obs_utc(cls, value: datetime) -> datetime:
        return _ensure_utc(value, "observed_at")

    @field_validator("instrument_ids")
    @classmethod
    def _instruments(cls, value: Sequence[str]) -> tuple[str, ...]:
        return tuple(_validate_instrument_id(item) for item in value)

    @model_validator(mode="after")
    def _source_not_after_observation(self) -> Self:
        if self.source_timestamp > self.observed_at + timedelta(minutes=1):
            raise ValueError("source_timestamp cannot be after observed_at")
        return self


class FundOrder(BaseModel):
    """Explicit-side paper order; cannot cross long/short with the wrong side."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1, max_length=128)
    asset_class: AssetClass
    side: OrderSide
    quantity: Decimal | None = Field(default=None, gt=0)
    p_win: Decimal | None = Field(default=None, ge=0, le=1)
    target_price: Decimal | None = Field(default=None, gt=0)
    invalidation_price: Decimal | None = Field(default=None, gt=0)
    horizon_hours: int | None = Field(default=None, ge=1, le=8_760)
    playbook_id: str | None = Field(default=None, min_length=1, max_length=128)
    driver: str | None = Field(default=None, min_length=1, max_length=128)
    borrow_fee_bps_annual: Decimal | None = Field(default=None, ge=0)
    extra_slippage_bps: Decimal | None = Field(default=None, ge=0)
    rationale: str = Field(min_length=1, max_length=4000)
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("instrument_id")
    @classmethod
    def _instrument(cls, value: str) -> str:
        return _validate_instrument_id(value)

    @field_validator("quantity", mode="before")
    @classmethod
    def _qty_dec(cls, value: Any) -> Decimal | None:
        return None if value is None else _as_decimal(value)

    @field_validator(
        "p_win",
        "target_price",
        "invalidation_price",
        "borrow_fee_bps_annual",
        "extra_slippage_bps",
        mode="before",
    )
    @classmethod
    def _belief_decimals(cls, value: Any) -> Decimal | None:
        return None if value is None else _as_decimal(value)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids(cls, value: Sequence[str]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value if str(item).strip())
        if not cleaned:
            raise ValueError("evidence_ids must be non-empty")
        return cleaned


class FundHypothesis(BaseModel):
    """Falsifiable, instrument-level reasoning retained in the fund journal."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1, max_length=128)
    stance: HypothesisStance
    statement: str = Field(min_length=1, max_length=2000)
    mechanism: str = Field(min_length=1, max_length=2000)
    catalysts: tuple[str, ...] = Field(min_length=1, max_length=8)
    falsifiers: tuple[str, ...] = Field(min_length=1, max_length=8)
    expected_horizon_hours: int = Field(ge=1, le=8_760)
    confidence: Decimal = Field(ge=0, le=1)
    p_win: Decimal | None = Field(default=None, ge=0, le=1)
    playbook_id: str | None = Field(default=None, min_length=1, max_length=128)
    driver: str | None = Field(default=None, min_length=1, max_length=128)
    target_price: Decimal | None = Field(default=None, gt=0)
    invalidation_price: Decimal | None = Field(default=None, gt=0)
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("instrument_id")
    @classmethod
    def _instrument(cls, value: str) -> str:
        return _validate_instrument_id(value)

    @field_validator("confidence", "p_win", "target_price", "invalidation_price", mode="before")
    @classmethod
    def _decimals(cls, value: Any) -> Decimal | None:
        return None if value is None else _as_decimal(value)

    @field_validator("catalysts", "falsifiers", "evidence_ids")
    @classmethod
    def _nonempty_strings(cls, value: Sequence[str]) -> tuple[str, ...]:
        cleaned = tuple(str(item).strip() for item in value if str(item).strip())
        if not cleaned:
            raise ValueError("journal lists must contain at least one non-empty item")
        return cleaned


class DecisionJournal(BaseModel):
    """Concise auditable reasoning; deliberately not private chain-of-thought."""

    model_config = ConfigDict(extra="forbid")

    market_regime: str = Field(min_length=1, max_length=2000)
    opportunity_set: str = Field(min_length=1, max_length=4000)
    portfolio_intent: str = Field(min_length=1, max_length=4000)
    what_changed: str = Field(min_length=1, max_length=4000)
    lessons_applied: tuple[str, ...] = Field(default=(), max_length=12)
    hypotheses: tuple[FundHypothesis, ...] = Field(default=(), max_length=40)

    @field_validator("lessons_applied")
    @classmethod
    def _lessons(cls, value: Sequence[str]) -> tuple[str, ...]:
        return tuple(str(item).strip() for item in value if str(item).strip())

    @model_validator(mode="after")
    def _unique_instruments(self) -> Self:
        instruments = [item.instrument_id for item in self.hypotheses]
        if len(instruments) != len(set(instruments)):
            raise ValueError("journal hypotheses must use unique instrument_id values")
        return self


class FundDecision(BaseModel):
    """Normalized cycle decision: trade with orders, or hold with none."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1, max_length=128)
    fund_id: str = Field(min_length=1, max_length=128)
    cycle_key: str = Field(min_length=1, max_length=200)
    as_of: datetime
    action: DecisionAction
    thesis: str = Field(min_length=1, max_length=8000)
    alternatives: str = Field(default="", max_length=8000)
    risks: str = Field(default="", max_length=8000)
    journal: DecisionJournal | None = None
    evidence: tuple[FundEvidence, ...] = ()
    orders: tuple[FundOrder, ...] = ()

    @field_validator("as_of")
    @classmethod
    def _as_of_utc(cls, value: datetime) -> datetime:
        return _ensure_utc(value, "as_of")

    @model_validator(mode="after")
    def _action_orders_and_evidence(self) -> Self:
        if self.action is DecisionAction.TRADE and not self.orders:
            raise ValueError("trade decisions require at least one order")
        if self.action is DecisionAction.HOLD and self.orders:
            raise ValueError("hold decisions must not include orders")

        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        if len(evidence_by_id) != len(self.evidence):
            raise ValueError("duplicate evidence_id in decision inventory")
        future_evidence = [
            item.evidence_id
            for item in self.evidence
            if item.observed_at > self.as_of or item.source_timestamp > self.as_of
        ]
        if future_evidence:
            raise ValueError(f"evidence is newer than decision: {future_evidence}")

        for order in self.orders:
            _require_cited_evidence(
                evidence_by_id,
                order.evidence_ids,
                order.instrument_id,
                role="order",
            )

        if self.journal is not None:
            hypotheses = {item.instrument_id: item for item in self.journal.hypotheses}
            for hypothesis in self.journal.hypotheses:
                _require_cited_evidence(
                    evidence_by_id,
                    hypothesis.evidence_ids,
                    hypothesis.instrument_id,
                    role="hypothesis",
                )
            missing = sorted({order.instrument_id for order in self.orders}.difference(hypotheses))
            if missing:
                raise ValueError(f"ordered instruments are missing journal hypotheses: {missing}")
        return self


class FundCyclePacket(BaseModel):
    """Strict model-produced portion of one cycle input."""

    model_config = ConfigDict(extra="forbid")

    decision: FundDecision
    quotes: tuple[FundQuote, ...]


def _require_cited_evidence(
    evidence_by_id: Mapping[str, FundEvidence],
    evidence_ids: Sequence[str],
    instrument_id: str,
    *,
    role: str,
) -> None:
    cited: list[FundEvidence] = []
    for evidence_id in evidence_ids:
        if evidence_id not in evidence_by_id:
            raise ValueError(f"{role} on {instrument_id} cites unknown evidence_id {evidence_id}")
        item = evidence_by_id[evidence_id]
        cited.append(item)
        if item.instrument_ids and instrument_id not in item.instrument_ids:
            target = "instrument" if role == "order" else "hypothesis"
            raise ValueError(f"evidence {evidence_id} is not relevant to {target} {instrument_id}")
    if role == "order" and not any(instrument_id in item.instrument_ids for item in cited):
        raise ValueError(f"order on {instrument_id} requires instrument-specific evidence")


class FundPosition(BaseModel):
    """Signed position: positive long, negative short; average entry always > 0."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    asset_class: AssetClass
    quantity: Decimal  # signed
    average_entry: Decimal = Field(gt=0)
    mark_price: Decimal | None = None
    market_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    playbook_id: str | None = None
    driver: str | None = None
    opened_at: datetime | None = None
    borrow_fee_bps_annual: Decimal | None = None

    @field_validator("quantity", "average_entry", mode="before")
    @classmethod
    def _dec(cls, value: Any) -> Decimal:
        return _as_decimal(value)


class FundFill(BaseModel):
    """Single fill or settlement event produced by a cycle."""

    model_config = ConfigDict(extra="forbid")

    fill_id: str
    instrument_id: str
    asset_class: AssetClass
    side: Literal["buy", "sell", "short", "cover", "settle"]
    quantity: Decimal = Field(gt=0)
    quote_price: Decimal
    execution_price: Decimal
    gross_notional: Decimal
    fee: Decimal
    cash_delta: Decimal
    realized_pnl: Decimal
    quote_id: str
    is_settlement: bool = False
    playbook_id: str | None = None
    driver: str | None = None
    borrow_fee: Decimal = ZERO


class FundState(BaseModel):
    """Point-in-time fund state recoverable from the latest completed cycle."""

    model_config = ConfigDict(extra="forbid")

    fund_id: str
    as_of: datetime
    cash: Decimal
    positions: tuple[FundPosition, ...] = ()
    nav: Decimal
    peak_nav: Decimal
    drawdown: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    short_exposure: Decimal
    realized_pnl_cumulative: Decimal = ZERO
    cycle_count: int = 0
    last_cycle_key: str | None = None

    @field_validator("as_of")
    @classmethod
    def _as_of_utc(cls, value: datetime) -> datetime:
        return _ensure_utc(value, "as_of")


def _initial_state(fund_id: str, cash: Decimal, as_of: datetime) -> FundState:
    return FundState(
        fund_id=fund_id,
        as_of=as_of,
        cash=cash,
        positions=(),
        nav=cash,
        peak_nav=cash,
        drawdown=ZERO,
        gross_exposure=ZERO,
        net_exposure=ZERO,
        short_exposure=ZERO,
        realized_pnl_cumulative=ZERO,
        cycle_count=0,
        last_cycle_key=None,
    )


def validate_decision_journal(decision: FundDecision, prior_state: FundState) -> None:
    """Require the scheduled agent to refresh every live or ordered hypothesis.

    Historical cycles remain replayable through accounting without this check.
    New scheduled applies retain short horizons while allowing cash when every
    researched belief falls below the deterministic after-cost edge threshold.
    """
    if decision.journal is None:
        raise PaperFundValidationError("scheduled decisions require an auditable journal")
    journal_instruments = {hypothesis.instrument_id for hypothesis in decision.journal.hypotheses}
    required = {position.instrument_id for position in prior_state.positions} | {
        order.instrument_id for order in decision.orders
    }
    missing = sorted(required.difference(journal_instruments))
    if missing:
        raise PaperFundValidationError(
            f"journal is missing hypotheses for open or ordered instruments: {missing}"
        )
    long_horizon = [
        f"{item.instrument_id}:{item.expected_horizon_hours}h"
        for item in decision.journal.hypotheses
        if item.expected_horizon_hours > MAX_SCHEDULED_HYPOTHESIS_HORIZON_HOURS
    ]
    if long_horizon:
        raise PaperFundValidationError(
            "scheduled hypotheses must use a short-term horizon of "
            f"{MAX_SCHEDULED_HYPOTHESIS_HORIZON_HOURS}h or less: {long_horizon}"
        )
    incomplete = [
        item.instrument_id
        for item in decision.journal.hypotheses
        if item.p_win is None or not item.driver or not item.playbook_id
    ]
    if incomplete:
        raise PaperFundValidationError(
            "scheduled hypotheses require p_win, driver, and playbook_id: " + ", ".join(incomplete)
        )


class RiskCheck(BaseModel):
    """One deterministic risk or policy check with the observed value and limit."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    passed: bool
    observed: str = Field(min_length=1, max_length=200)
    limit: str | None = Field(default=None, max_length=200)
    detail: str = Field(default="", max_length=2000)


class RiskEvaluation(BaseModel):
    """Policy/risk engine outcome retained for audit and replay."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    checks: tuple[RiskCheck, ...] = ()
    order_count: int = Field(ge=0)
    turnover: Decimal = ZERO
    pre_nav: Decimal
    post_nav: Decimal
    post_gross_exposure: Decimal
    post_net_exposure: Decimal
    post_short_exposure: Decimal
    post_drawdown: Decimal
    prediction_short_reserve: Decimal = ZERO

    @field_validator(
        "turnover",
        "pre_nav",
        "post_nav",
        "post_gross_exposure",
        "post_net_exposure",
        "post_short_exposure",
        "post_drawdown",
        "prediction_short_reserve",
        mode="before",
    )
    @classmethod
    def _dec(cls, value: Any) -> Decimal:
        return _as_decimal(value)


class QuoteFreshnessRecord(BaseModel):
    """Source and observation freshness for one quote used in a cycle."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    quote_id: str
    asset_class: AssetClass
    status: QuoteStatus
    price: Decimal
    observed_at: datetime
    source_timestamp: datetime
    observation_age_seconds: int = Field(ge=0)
    source_age_seconds: int = Field(ge=0)
    max_observation_age_seconds: int = Field(ge=0)
    max_source_age_seconds: int = Field(ge=0)
    source_name: str
    source_url: str

    @field_validator("price", mode="before")
    @classmethod
    def _price_dec(cls, value: Any) -> Decimal:
        return _as_decimal(value)

    @field_validator("observed_at", "source_timestamp")
    @classmethod
    def _obs_utc(cls, value: datetime) -> datetime:
        return _ensure_utc(value, "observed_at")


class CycleRuntimeMetadata(BaseModel):
    """Process provenance for the cycle apply step (not agent-writable state)."""

    model_config = ConfigDict(extra="forbid")

    edgecraft_version: str = Field(min_length=1, max_length=50)
    mandate_digest: str = Field(min_length=1, max_length=128)
    prompt_version: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    reasoning_effort: str | None = Field(default=None, max_length=50)
    input_path: str | None = Field(default=None, max_length=2000)
    input_sha256: str | None = Field(default=None, max_length=128)
    recorded_at: datetime | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    model_cost_usd: Decimal | None = Field(default=None, ge=0)

    @field_validator("model_cost_usd", mode="before")
    @classmethod
    def _cost_dec(cls, value: Any) -> Decimal | None:
        return None if value is None else _as_decimal(value)

    @field_validator("recorded_at")
    @classmethod
    def _recorded_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _ensure_utc(value, "recorded_at")


class CycleAuditRecord(BaseModel):
    """Immutable risk + provenance sidecar stored with every completed cycle."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "edgecraft.fund-cycle-audit.v1"
    runtime: CycleRuntimeMetadata
    risk: RiskEvaluation
    quote_freshness: tuple[QuoteFreshnessRecord, ...] = ()
    fee_total: Decimal = ZERO
    fill_count: int = Field(ge=0, default=0)
    settlement_count: int = Field(ge=0, default=0)
    sleeve_allocation: dict[str, Decimal] = Field(default_factory=dict)
    sizing: dict[str, Any] | None = None

    @field_validator("fee_total", mode="before")
    @classmethod
    def _fee_dec(cls, value: Any) -> Decimal:
        return _as_decimal(value)


class CycleResult(BaseModel):
    """Result of one atomic cycle execution or idempotent replay."""

    model_config = ConfigDict(extra="forbid")

    fund_id: str
    cycle_key: str
    decision_id: str
    action: DecisionAction
    as_of: datetime
    fills: tuple[FundFill, ...] = ()
    settlements: tuple[FundFill, ...] = ()
    state: FundState
    request_digest: str
    replayed: bool = False
    event_sequence: int
    audit: CycleAuditRecord | None = None


class VerificationReport(BaseModel):
    """Machine-readable integrity report from verify()."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    fund_id: str | None
    event_count: int
    cycle_count: int
    chain_ok: bool
    accounting_ok: bool
    details: list[str] = Field(default_factory=list)


class AuditEvent(BaseModel):
    """Append-only hash-chained audit event."""

    model_config = ConfigDict(extra="forbid")

    sequence: int
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any]
    prev_hash: str
    event_hash: str


class AccountingOutcome(BaseModel):
    """Pure accounting result including the deterministic risk evaluation."""

    model_config = ConfigDict(extra="forbid")

    fills: tuple[FundFill, ...] = ()
    settlements: tuple[FundFill, ...] = ()
    state: FundState
    risk: RiskEvaluation
    quote_freshness: tuple[QuoteFreshnessRecord, ...] = ()


# ---------------------------------------------------------------------------
# Accounting engine (pure functions)
# ---------------------------------------------------------------------------


def _execution_price(quote_price: Decimal, side: OrderSide, slippage_bps: Decimal) -> Decimal:
    slip = quote_price * slippage_bps / BPS_DIVISOR
    if side in (OrderSide.BUY, OrderSide.COVER):
        return quote_price + slip
    return quote_price - slip


def _walk_book(levels: Sequence[BookLevel], quantity: Decimal, *, descending: bool) -> Decimal:
    """Return quantity-weighted average price, consuming displayed size."""
    ordered = sorted(levels, key=lambda level: level.price, reverse=descending)
    remaining = quantity
    cost = ZERO
    for level in ordered:
        take = min(remaining, level.size)
        cost += take * level.price
        remaining -= take
        if remaining <= ZERO:
            return cost / quantity
    raise PaperFundValidationError("insufficient displayed book depth for simulated fill")


def _fill_price(quote: FundQuote, order: FundOrder, mandate: FundMandate) -> Decimal:
    extra = order.extra_slippage_bps or ZERO
    if order.side in {OrderSide.BUY, OrderSide.COVER} and quote.asks:
        price = _walk_book(quote.asks, order.quantity or ZERO, descending=False)
        return _execution_price(price, order.side, extra)
    if order.side in {OrderSide.SELL, OrderSide.SHORT} and quote.bids:
        price = _walk_book(quote.bids, order.quantity or ZERO, descending=True)
        return _execution_price(price, order.side, extra)
    return _execution_price(quote.price, order.side, mandate.slippage_bps + extra)


def _fee(gross_notional: Decimal, fee_bps: Decimal) -> Decimal:
    return abs(gross_notional) * fee_bps / BPS_DIVISOR


def _position_map(positions: Sequence[FundPosition]) -> dict[str, FundPosition]:
    return {p.instrument_id: p for p in positions}


def _mark_positions(
    positions: Sequence[FundPosition],
    quotes: Mapping[str, FundQuote],
) -> list[FundPosition]:
    marked: list[FundPosition] = []
    for pos in positions:
        quote = quotes.get(pos.instrument_id)
        if quote is None:
            raise PaperFundValidationError(f"missing quote for open position {pos.instrument_id}")
        if quote.asset_class != pos.asset_class:
            raise PaperFundValidationError(
                f"asset class mismatch for {pos.instrument_id}: "
                f"position={pos.asset_class} quote={quote.asset_class}"
            )
        mv = pos.quantity * quote.price
        if pos.quantity > ZERO:
            upnl = (quote.price - pos.average_entry) * pos.quantity
        else:
            upnl = (pos.average_entry - quote.price) * abs(pos.quantity)
        marked.append(
            pos.model_copy(
                update={
                    "mark_price": quote.price,
                    "market_value": mv,
                    "unrealized_pnl": upnl,
                }
            )
        )
    return marked


def _compute_exposures(
    cash: Decimal, positions: Sequence[FundPosition]
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    net = sum((p.market_value or ZERO for p in positions), ZERO)
    gross = sum((abs(p.market_value or ZERO) for p in positions), ZERO)
    short = ZERO
    for position in positions:
        market_value = position.market_value or ZERO
        if market_value >= ZERO:
            continue
        if position.asset_class is AssetClass.PREDICTION:
            if position.mark_price is None:
                raise PaperFundValidationError(
                    f"prediction short {position.instrument_id} is missing a mark"
                )
            # A short binary contract sold at p can still owe 1 at settlement.
            # Cap the remaining worst-case liability, not its deceptively small
            # current marked value.
            short += abs(position.quantity) * (ONE - position.mark_price)
        else:
            short += abs(market_value)
    nav = cash + net
    return nav, gross, net, short


def _prediction_short_reserve(positions: Sequence[FundPosition]) -> Decimal:
    """Cash needed if every open binary short settles at its $1 payout."""
    return sum(
        (
            abs(position.quantity)
            for position in positions
            if position.asset_class is AssetClass.PREDICTION and position.quantity < ZERO
        ),
        ZERO,
    )


def _apply_fill_to_position(
    existing: FundPosition | None,
    *,
    instrument_id: str,
    asset_class: AssetClass,
    side: OrderSide,
    quantity: Decimal,
    execution_price: Decimal,
    playbook_id: str | None = None,
    driver: str | None = None,
    opened_at: datetime | None = None,
    borrow_fee_bps_annual: Decimal | None = None,
) -> FundPosition | None:
    """Return updated position or None if closed. Enforces explicit side rules."""
    if existing is None:
        existing_qty = ZERO
        avg = ZERO
    else:
        existing_qty = existing.quantity
        avg = existing.average_entry
        if existing.asset_class != asset_class:
            raise PaperFundValidationError(f"asset class mismatch for position {instrument_id}")
        if playbook_id and existing.playbook_id and playbook_id != existing.playbook_id:
            raise PaperFundValidationError(
                f"position {instrument_id} belongs to playbook {existing.playbook_id}"
            )
        playbook_id = existing.playbook_id or playbook_id
        driver = existing.driver or driver
        opened_at = existing.opened_at or opened_at
        borrow_fee_bps_annual = existing.borrow_fee_bps_annual or borrow_fee_bps_annual

    if side is OrderSide.BUY:
        if existing_qty < ZERO:
            raise PaperFundValidationError(f"buy cannot cover short on {instrument_id}; use cover")
        new_qty = existing_qty + quantity
        new_avg = (
            (existing_qty * avg + quantity * execution_price) / new_qty
            if existing_qty > ZERO
            else execution_price
        )
        return FundPosition(
            instrument_id=instrument_id,
            asset_class=asset_class,
            quantity=new_qty,
            average_entry=new_avg,
            playbook_id=playbook_id,
            driver=driver,
            opened_at=opened_at,
            borrow_fee_bps_annual=borrow_fee_bps_annual,
        )

    if side is OrderSide.SELL:
        if existing_qty <= ZERO:
            raise PaperFundValidationError(
                f"sell cannot open or increase short on {instrument_id}; use short"
            )
        if quantity > existing_qty:
            raise PaperFundValidationError(
                f"oversell on {instrument_id}: have {existing_qty}, sell {quantity}"
            )
        new_qty = existing_qty - quantity
        if new_qty == ZERO:
            return None
        return FundPosition(
            instrument_id=instrument_id,
            asset_class=asset_class,
            quantity=new_qty,
            average_entry=avg,
            playbook_id=playbook_id,
            driver=driver,
            opened_at=opened_at,
            borrow_fee_bps_annual=borrow_fee_bps_annual,
        )

    if side is OrderSide.SHORT:
        if existing_qty > ZERO:
            raise PaperFundValidationError(f"short cannot reduce long on {instrument_id}; use sell")
        abs_existing = abs(existing_qty)
        new_qty = existing_qty - quantity  # more negative
        new_avg = (
            (abs_existing * avg + quantity * execution_price) / (abs_existing + quantity)
            if abs_existing > ZERO
            else execution_price
        )
        return FundPosition(
            instrument_id=instrument_id,
            asset_class=asset_class,
            quantity=new_qty,
            average_entry=new_avg,
            playbook_id=playbook_id,
            driver=driver,
            opened_at=opened_at,
            borrow_fee_bps_annual=borrow_fee_bps_annual,
        )

    if side is OrderSide.COVER:
        if existing_qty >= ZERO:
            raise PaperFundValidationError(
                f"cover cannot open or increase long on {instrument_id}; use buy"
            )
        abs_existing = abs(existing_qty)
        if quantity > abs_existing:
            raise PaperFundValidationError(
                f"over-cover on {instrument_id}: short {abs_existing}, cover {quantity}"
            )
        new_qty = existing_qty + quantity  # toward zero
        if new_qty == ZERO:
            return None
        return FundPosition(
            instrument_id=instrument_id,
            asset_class=asset_class,
            quantity=new_qty,
            average_entry=avg,
            playbook_id=playbook_id,
            driver=driver,
            opened_at=opened_at,
            borrow_fee_bps_annual=borrow_fee_bps_annual,
        )

    raise PaperFundValidationError(f"unsupported side {side}")


def _execute_order(
    *,
    order: FundOrder,
    quote: FundQuote,
    mandate: FundMandate,
    existing: FundPosition | None,
    cash: Decimal,
    as_of: datetime,
) -> tuple[FundFill, FundPosition | None, Decimal, Decimal]:
    if order.quantity is None:
        raise PaperFundValidationError(
            f"order {order.instrument_id} requires quantity or deterministic sizing"
        )
    if quote.status is QuoteStatus.SETTLED:
        raise PaperFundValidationError(
            f"settled instrument {order.instrument_id} cannot receive new orders"
        )
    if quote.instrument_id != order.instrument_id:
        raise PaperFundValidationError("quote instrument_id mismatch")
    if quote.asset_class != order.asset_class:
        raise PaperFundValidationError(
            f"order/quote asset class mismatch for {order.instrument_id}"
        )

    exec_px = _fill_price(quote, order, mandate)
    if exec_px <= ZERO and order.asset_class is not AssetClass.PREDICTION:
        raise PaperFundValidationError(f"non-positive execution price for {order.instrument_id}")
    if order.asset_class is AssetClass.PREDICTION and not ZERO <= exec_px <= ONE:
        # Slippage can push outside the bounded contract payoff range. Refuse
        # rather than inventing a clipped fill price.
        raise PaperFundValidationError(
            f"execution price outside [0, 1] for prediction {order.instrument_id}"
        )

    gross = exec_px * order.quantity
    fee = _fee(gross, mandate.fee_bps)
    borrow_fee = ZERO
    if (
        order.side is OrderSide.COVER
        and existing is not None
        and existing.asset_class is AssetClass.STOCK
        and existing.opened_at is not None
        and existing.borrow_fee_bps_annual is not None
    ):
        held_seconds = max(0, (as_of - existing.opened_at).total_seconds())
        years = Decimal(str(held_seconds)) / Decimal("31536000")
        borrow_fee = (
            existing.average_entry
            * order.quantity
            * existing.borrow_fee_bps_annual
            / BPS_DIVISOR
            * years
        )
        fee += borrow_fee
    realized = ZERO

    if order.side is OrderSide.BUY:
        cash_delta = -(gross + fee)
        if cash + cash_delta < ZERO:
            raise PaperFundValidationError(
                f"insufficient cash for buy {order.instrument_id}: need {-(cash_delta)}, have {cash}"
            )
    elif order.side is OrderSide.SELL:
        if existing is None or existing.quantity <= ZERO:
            raise PaperFundValidationError(f"sell cannot open short on {order.instrument_id}")
        cash_delta = gross - fee
        realized = (exec_px - existing.average_entry) * order.quantity - fee
    elif order.side is OrderSide.SHORT:
        cash_delta = gross - fee
    elif order.side is OrderSide.COVER:
        if existing is None or existing.quantity >= ZERO:
            raise PaperFundValidationError(f"cover cannot open long on {order.instrument_id}")
        cash_delta = -(gross + fee)
        if cash + cash_delta < ZERO:
            raise PaperFundValidationError(
                f"insufficient cash for cover {order.instrument_id}: need {-(cash_delta)}, have {cash}"
            )
        realized = (existing.average_entry - exec_px) * order.quantity - fee
    else:
        raise PaperFundValidationError(f"unsupported side {order.side}")

    new_pos = _apply_fill_to_position(
        existing,
        instrument_id=order.instrument_id,
        asset_class=order.asset_class,
        side=order.side,
        quantity=order.quantity,
        execution_price=exec_px,
        playbook_id=order.playbook_id,
        driver=order.driver,
        opened_at=as_of if order.borrow_fee_bps_annual is not None else None,
        borrow_fee_bps_annual=order.borrow_fee_bps_annual,
    )
    fill = FundFill(
        fill_id=str(uuid.uuid4()),
        instrument_id=order.instrument_id,
        asset_class=order.asset_class,
        side=order.side.value,  # type: ignore[arg-type]
        quantity=order.quantity,
        quote_price=quote.price,
        execution_price=exec_px,
        gross_notional=gross,
        fee=fee,
        cash_delta=cash_delta,
        realized_pnl=realized,
        quote_id=quote.quote_id,
        is_settlement=False,
        playbook_id=order.playbook_id or (existing.playbook_id if existing else None),
        driver=order.driver or (existing.driver if existing else None),
        borrow_fee=borrow_fee,
    )
    return fill, new_pos, cash + cash_delta, realized


def _settle_position(
    position: FundPosition,
    quote: FundQuote,
) -> tuple[FundFill, Decimal, Decimal]:
    """Settle a prediction position at 0 or 1 with no fee/slippage."""
    if quote.asset_class is not AssetClass.PREDICTION:
        raise PaperFundValidationError("only prediction positions settle via settled quotes")
    if quote.status is not QuoteStatus.SETTLED:
        raise PaperFundValidationError("settlement requires settled quote status")
    if quote.instrument_id != position.instrument_id:
        raise PaperFundValidationError("settlement quote instrument mismatch")
    if quote.price not in (ZERO, ONE):
        raise PaperFundValidationError("settlement price must be 0 or 1")

    qty_abs = abs(position.quantity)
    exec_px = quote.price
    gross = exec_px * qty_abs
    # Closing cash flow mirrors sell (long) or cover (short) without fee/slippage.
    if position.quantity > ZERO:
        cash_delta = gross  # sell at settlement price
        realized = (exec_px - position.average_entry) * qty_abs
        side: Literal["settle"] = "settle"
    else:
        cash_delta = -gross  # cover at settlement price
        realized = (position.average_entry - exec_px) * qty_abs
        side = "settle"

    fill = FundFill(
        fill_id=str(uuid.uuid4()),
        instrument_id=position.instrument_id,
        asset_class=position.asset_class,
        side=side,
        quantity=qty_abs,
        quote_price=quote.price,
        execution_price=exec_px,
        gross_notional=gross,
        fee=ZERO,
        cash_delta=cash_delta,
        realized_pnl=realized,
        quote_id=quote.quote_id,
        is_settlement=True,
        playbook_id=position.playbook_id,
        driver=position.driver,
        borrow_fee=ZERO,
    )
    return fill, cash_delta, realized


def _validate_quotes_for_cycle(
    *,
    mandate: FundMandate,
    as_of: datetime,
    quotes: Sequence[FundQuote],
    open_positions: Sequence[FundPosition],
    orders: Sequence[FundOrder],
) -> dict[str, FundQuote]:
    by_id: dict[str, FundQuote] = {}
    for quote in quotes:
        if quote.instrument_id in by_id:
            raise PaperFundValidationError(f"duplicate quote for instrument {quote.instrument_id}")
        if quote.observed_at > as_of:
            raise PaperFundValidationError(
                f"future quote for {quote.instrument_id}: observed_at {quote.observed_at} > as_of {as_of}"
            )
        if quote.asset_class not in mandate.supported_asset_classes:
            raise PaperFundValidationError(
                f"unsupported asset class {quote.asset_class} for {quote.instrument_id}"
            )
        age = as_of - quote.observed_at
        max_age = mandate.freshness_for(quote.asset_class)
        # Settled quotes still must not be future, but settlement is a terminal event;
        # apply freshness so we don't mark with ancient settled prints accidentally.
        if age > max_age:
            raise PaperFundValidationError(
                f"stale quote for {quote.instrument_id}: age {age} > {max_age}"
            )
        source_age = as_of - quote.source_timestamp
        max_source_age = mandate.source_age_for(quote.asset_class)
        if source_age > max_source_age:
            raise PaperFundValidationError(
                f"stale source price for {quote.instrument_id}: age {source_age} > {max_source_age}"
            )
        by_id[quote.instrument_id] = quote

    required: set[str] = {p.instrument_id for p in open_positions}
    for order in orders:
        required.add(order.instrument_id)
        if order.asset_class not in mandate.supported_asset_classes:
            raise PaperFundValidationError(
                f"unsupported asset class on order {order.instrument_id}"
            )

    for instrument_id in required:
        if instrument_id not in by_id:
            raise PaperFundValidationError(f"missing quote for instrument {instrument_id}")
        quote = by_id[instrument_id]
        # Match asset class for orders
        for order in orders:
            if order.instrument_id == instrument_id and order.asset_class != quote.asset_class:
                raise PaperFundValidationError(
                    f"mismatched quote asset class for order {instrument_id}"
                )
        for pos in open_positions:
            if pos.instrument_id == instrument_id and pos.asset_class != quote.asset_class:
                raise PaperFundValidationError(
                    f"mismatched quote asset class for position {instrument_id}"
                )

    quote_ids = [q.quote_id for q in quotes]
    if len(quote_ids) != len(set(quote_ids)):
        raise PaperFundValidationError("duplicate quote_id in cycle quotes")

    return by_id


def _cycle_turnover(fills: Sequence[FundFill]) -> Decimal:
    return sum((f.gross_notional for f in fills if not f.is_settlement), ZERO)


def mandate_digest(mandate: FundMandate) -> str:
    """Canonical SHA-256 of the immutable mandate payload used for a cycle."""
    return _sha256_hex(_canonical_json(json.loads(mandate.model_dump_json())))


def _quote_freshness_records(
    *,
    mandate: FundMandate,
    as_of: datetime,
    quotes: Sequence[FundQuote],
) -> tuple[QuoteFreshnessRecord, ...]:
    records: list[QuoteFreshnessRecord] = []
    for quote in quotes:
        max_obs = mandate.freshness_for(quote.asset_class)
        max_src = mandate.source_age_for(quote.asset_class)
        records.append(
            QuoteFreshnessRecord(
                instrument_id=quote.instrument_id,
                quote_id=quote.quote_id,
                asset_class=quote.asset_class,
                status=quote.status,
                price=quote.price,
                observed_at=quote.observed_at,
                source_timestamp=quote.source_timestamp,
                observation_age_seconds=max(0, int((as_of - quote.observed_at).total_seconds())),
                source_age_seconds=max(0, int((as_of - quote.source_timestamp).total_seconds())),
                max_observation_age_seconds=int(max_obs.total_seconds()),
                max_source_age_seconds=int(max_src.total_seconds()),
                source_name=quote.source_name,
                source_url=quote.source_url,
            )
        )
    return tuple(records)


def _risk_check(
    name: str,
    *,
    passed: bool,
    observed: Any,
    limit: Any,
    detail: str,
) -> RiskCheck:
    return RiskCheck(
        name=name,
        passed=passed,
        observed=str(observed),
        limit=None if limit is None else str(limit),
        detail=detail,
    )


def evaluate_risk(
    *,
    mandate: FundMandate,
    pre_state: FundState,
    post_cash: Decimal,
    post_positions: Sequence[FundPosition],
    fills: Sequence[FundFill],
    order_count: int,
) -> RiskEvaluation:
    """Evaluate every mandate risk rule and return a durable audit record.

    Raises PaperFundValidationError when any hard limit fails, after the full
    checklist is assembled so rejections remain explainable.
    """
    turnover = _cycle_turnover(fills)
    nav, gross, net, short = _compute_exposures(post_cash, post_positions)
    prediction_reserve = _prediction_short_reserve(post_positions)
    peak = max(pre_state.peak_nav, nav)
    post_dd = (peak - nav) / peak if peak > ZERO else ZERO
    risk_nav = max(pre_state.nav, ZERO)
    turnover_limit = mandate.effective_limit(
        mandate.max_cycle_turnover, mandate.max_cycle_turnover_nav_multiple, risk_nav
    )
    gross_limit = mandate.effective_limit(
        mandate.max_gross_exposure, mandate.max_gross_exposure_nav_multiple, risk_nav
    )
    net_limit = mandate.effective_limit(
        mandate.max_absolute_net_exposure,
        mandate.max_absolute_net_exposure_nav_multiple,
        risk_nav,
    )
    short_limit = mandate.effective_limit(
        mandate.max_short_exposure, mandate.max_short_exposure_nav_multiple, risk_nav
    )

    checks: list[RiskCheck] = [
        _risk_check(
            "order_count",
            passed=order_count <= mandate.max_order_count,
            observed=order_count,
            limit=mandate.max_order_count,
            detail=(
                f"order count {order_count} exceeds max_order_count {mandate.max_order_count}"
                if order_count > mandate.max_order_count
                else ""
            ),
        ),
        _risk_check(
            "cycle_turnover",
            passed=turnover <= turnover_limit,
            observed=turnover,
            limit=turnover_limit,
            detail=(
                f"cycle turnover {turnover} exceeds effective max_cycle_turnover {turnover_limit}"
                if turnover > turnover_limit
                else ""
            ),
        ),
        _risk_check(
            "post_nav_positive",
            passed=nav > ZERO,
            observed=nav,
            limit="> 0",
            detail=f"post-trade NAV must be positive: {nav}" if nav <= ZERO else "",
        ),
        _risk_check(
            "prediction_short_reserve",
            passed=post_cash >= prediction_reserve,
            observed=post_cash,
            limit=prediction_reserve,
            detail=(
                f"cash {post_cash} is below prediction-short settlement reserve {prediction_reserve}"
                if post_cash < prediction_reserve
                else "cash covers worst-case binary short settlement liability"
            ),
        ),
        _risk_check(
            "gross_exposure",
            passed=gross <= gross_limit,
            observed=gross,
            limit=gross_limit,
            detail=(
                f"gross exposure {gross} exceeds max {gross_limit}" if gross > gross_limit else ""
            ),
        ),
        _risk_check(
            "absolute_net_exposure",
            passed=abs(net) <= net_limit,
            observed=abs(net),
            limit=net_limit,
            detail=(
                f"absolute net exposure {abs(net)} exceeds max {net_limit}"
                if abs(net) > net_limit
                else ""
            ),
        ),
        _risk_check(
            "short_exposure",
            passed=short <= short_limit,
            observed=short,
            limit=short_limit,
            detail=(
                f"short exposure {short} exceeds max {short_limit}" if short > short_limit else ""
            ),
        ),
    ]

    if nav > ZERO:
        for pos in post_positions:
            weight = abs(pos.market_value or ZERO) / nav
            checks.append(
                _risk_check(
                    f"position_weight:{pos.instrument_id}",
                    passed=weight <= mandate.max_single_position_weight,
                    observed=weight,
                    limit=mandate.max_single_position_weight,
                    detail=(
                        f"position weight {weight} for {pos.instrument_id} exceeds "
                        f"max_single_position_weight {mandate.max_single_position_weight}"
                        if weight > mandate.max_single_position_weight
                        else ""
                    ),
                )
            )

    # Drawdown gate: if pre-trade drawdown already beyond threshold, refuse
    # risk-increasing cycles (post gross > pre gross).
    pre_gross = pre_state.gross_exposure
    drawdown_breach = pre_state.drawdown > mandate.max_drawdown
    risk_increasing = gross > pre_gross
    checks.append(
        _risk_check(
            "drawdown_risk_increase",
            passed=not (drawdown_breach and risk_increasing),
            observed=pre_state.drawdown,
            limit=mandate.max_drawdown,
            detail=(
                f"drawdown {pre_state.drawdown} exceeds max_drawdown {mandate.max_drawdown}; "
                f"refusing risk-increasing cycle (gross {pre_gross} -> {gross})"
                if drawdown_breach and risk_increasing
                else ""
            ),
        )
    )

    failures = [check for check in checks if not check.passed]
    evaluation = RiskEvaluation(
        approved=not failures,
        checks=tuple(checks),
        order_count=order_count,
        turnover=turnover,
        pre_nav=pre_state.nav,
        post_nav=nav,
        post_gross_exposure=gross,
        post_net_exposure=net,
        post_short_exposure=short,
        post_drawdown=post_dd,
        prediction_short_reserve=prediction_reserve,
    )
    if failures:
        primary = failures[0]
        raise PaperFundValidationError(
            primary.detail
            or (
                f"{primary.name} failed: observed {primary.observed}"
                + (f" limit {primary.limit}" if primary.limit is not None else "")
            ),
            audit={"risk": evaluation.model_dump(mode="json")},
        )
    return evaluation


def run_cycle_accounting(
    *,
    mandate: FundMandate,
    prior_state: FundState,
    decision: FundDecision,
    quotes: Sequence[FundQuote],
) -> AccountingOutcome:
    """Pure cycle accounting: settlements, orders, marks, risk. No I/O."""
    if decision.fund_id != prior_state.fund_id:
        raise PaperFundValidationError("decision fund_id does not match fund state")
    if prior_state.cycle_count and decision.as_of < prior_state.as_of:
        raise PaperFundValidationError(
            f"decision as_of {decision.as_of} predates prior state {prior_state.as_of}"
        )

    open_positions = list(prior_state.positions)
    quote_map = _validate_quotes_for_cycle(
        mandate=mandate,
        as_of=decision.as_of,
        quotes=quotes,
        open_positions=open_positions,
        orders=decision.orders,
    )
    quote_freshness = _quote_freshness_records(mandate=mandate, as_of=decision.as_of, quotes=quotes)

    cash = prior_state.cash
    realized_cum = prior_state.realized_pnl_cumulative
    pos_map = _position_map(open_positions)
    settlements: list[FundFill] = []
    fills: list[FundFill] = []

    # 1) Automatic prediction settlements before new orders
    settled_instruments: set[str] = set()
    for instrument_id, quote in list(quote_map.items()):
        if quote.status is not QuoteStatus.SETTLED:
            continue
        settled_instruments.add(instrument_id)
        pos = pos_map.get(instrument_id)
        if pos is None:
            continue
        fill, cash_delta, realized = _settle_position(pos, quote)
        settlements.append(fill)
        cash += cash_delta
        realized_cum += realized
        del pos_map[instrument_id]

    if cash < ZERO:
        raise PaperFundValidationError(f"prediction settlement would leave negative cash: {cash}")

    # 2) Reject orders on settled instruments
    for order in decision.orders:
        q = quote_map[order.instrument_id]
        if q.status is QuoteStatus.SETTLED or order.instrument_id in settled_instruments:
            raise PaperFundValidationError(
                f"settled instrument {order.instrument_id} cannot receive new orders"
            )

    # 3) Execute orders
    for order in decision.orders:
        quote = quote_map[order.instrument_id]
        fill, new_pos, cash, realized = _execute_order(
            order=order,
            quote=quote,
            mandate=mandate,
            existing=pos_map.get(order.instrument_id),
            cash=cash,
            as_of=decision.as_of,
        )
        fills.append(fill)
        realized_cum += realized
        if new_pos is None:
            pos_map.pop(order.instrument_id, None)
        else:
            pos_map[order.instrument_id] = new_pos

    # 4) Mark remaining open positions (exclude settled-closed; need quotes)
    remaining = list(pos_map.values())
    # Quotes required for all remaining open positions
    mark_quotes = {
        iid: q
        for iid, q in quote_map.items()
        if iid in pos_map and q.status is not QuoteStatus.SETTLED
    }
    # If somehow a settled quote remains for an open pos, that is invalid
    for pos in remaining:
        q = quote_map.get(pos.instrument_id)
        if q is None:
            raise PaperFundValidationError(f"missing mark quote for {pos.instrument_id}")
        if q.status is QuoteStatus.SETTLED:
            raise PaperFundValidationError(
                f"position remains open on settled instrument {pos.instrument_id}"
            )
    marked = _mark_positions(remaining, mark_quotes)

    # Pre-trade marked state for drawdown gate uses prior_state already
    prior_open_positions = [
        position
        for position in prior_state.positions
        if quote_map[position.instrument_id].status is not QuoteStatus.SETTLED
    ]
    pre_marked = _mark_positions(
        prior_open_positions,
        {
            position.instrument_id: quote_map[position.instrument_id]
            for position in prior_open_positions
        },
    )
    # For instruments that settle this cycle, pre-trade mark uses settlement price
    pre_positions_for_gross: list[FundPosition] = []
    for p in prior_state.positions:
        q = quote_map.get(p.instrument_id)
        if q is None:
            continue
        if q.status is QuoteStatus.SETTLED:
            mv = p.quantity * q.price
            pre_positions_for_gross.append(
                p.model_copy(update={"mark_price": q.price, "market_value": mv})
            )
        else:
            match = next((m for m in pre_marked if m.instrument_id == p.instrument_id), None)
            pre_positions_for_gross.append(match if match is not None else p)

    pre_nav, pre_gross, pre_net, pre_short = _compute_exposures(
        prior_state.cash, pre_positions_for_gross
    )
    # Prefer persisted peak/drawdown; refresh drawdown from current peak
    peak = max(prior_state.peak_nav, pre_nav)
    pre_dd = (peak - pre_nav) / peak if peak > ZERO else ZERO
    pre_state = prior_state.model_copy(
        update={
            "nav": pre_nav,
            "peak_nav": peak,
            "drawdown": pre_dd,
            "gross_exposure": pre_gross,
            "net_exposure": pre_net,
            "short_exposure": pre_short,
            "positions": tuple(pre_positions_for_gross),
        }
    )

    all_fills = settlements + fills
    risk = evaluate_risk(
        mandate=mandate,
        pre_state=pre_state,
        post_cash=cash,
        post_positions=marked,
        fills=all_fills,
        order_count=len(decision.orders),
    )

    post_nav, post_gross, post_net, post_short = _compute_exposures(cash, marked)
    post_peak = max(peak, post_nav)
    post_dd = (post_peak - post_nav) / post_peak if post_peak > ZERO else ZERO

    new_state = FundState(
        fund_id=prior_state.fund_id,
        as_of=decision.as_of,
        cash=cash,
        positions=tuple(marked),
        nav=post_nav,
        peak_nav=post_peak,
        drawdown=post_dd,
        gross_exposure=post_gross,
        net_exposure=post_net,
        short_exposure=post_short,
        realized_pnl_cumulative=realized_cum,
        cycle_count=prior_state.cycle_count + 1,
        last_cycle_key=decision.cycle_key,
    )
    return AccountingOutcome(
        fills=tuple(fills),
        settlements=tuple(settlements),
        state=new_state,
        risk=risk,
        quote_freshness=quote_freshness,
    )


def request_digest(
    decision: FundDecision,
    quotes: Sequence[FundQuote],
) -> str:
    decision_payload = decision.model_dump(mode="json")
    # The journal was added after immutable v1 cycles existed. Omitting an absent
    # journal preserves their canonical request digests; present journals remain
    # part of the signed request and cannot be changed on replay.
    if decision.journal is None:
        decision_payload.pop("journal", None)
    # Optional belief/sizing fields were added after immutable v1 cycles. Drop
    # absent defaults so historical request digests remain byte-for-byte stable.
    for order in decision_payload.get("orders", []):
        for field in (
            "p_win",
            "target_price",
            "invalidation_price",
            "horizon_hours",
            "playbook_id",
            "driver",
            "borrow_fee_bps_annual",
            "extra_slippage_bps",
        ):
            if order.get(field) is None:
                order.pop(field, None)
    journal = decision_payload.get("journal") or {}
    for hypothesis in journal.get("hypotheses", []):
        for field in ("p_win", "playbook_id", "driver"):
            if hypothesis.get(field) is None:
                hypothesis.pop(field, None)
    quote_payloads = [q.model_dump(mode="json") for q in quotes]
    for quote in quote_payloads:
        for field in ("bids", "asks"):
            if not quote.get(field):
                quote.pop(field, None)
    payload = {
        "decision": decision_payload,
        "quotes": quote_payloads,
    }
    return _sha256_hex(_canonical_json(payload))


def _event_hash(
    prev_hash: str, sequence: int, event_type: str, occurred_at: str, payload: str
) -> str:
    material = f"{prev_hash}|{sequence}|{event_type}|{occurred_at}|{payload}"
    return _sha256_hex(material)


# ---------------------------------------------------------------------------
# SQLite ledger
# ---------------------------------------------------------------------------

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS funds (
    fund_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    mandate_json TEXT NOT NULL,
    initial_cash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cycles (
    fund_id TEXT NOT NULL,
    cycle_key TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    action TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    quotes_json TEXT NOT NULL,
    fills_json TEXT NOT NULL,
    settlements_json TEXT NOT NULL,
    state_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (fund_id, cycle_key),
    FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    UNIQUE (fund_id, sequence),
    UNIQUE (event_hash),
    FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
);

CREATE INDEX IF NOT EXISTS idx_events_fund_seq ON events(fund_id, sequence);
CREATE INDEX IF NOT EXISTS idx_cycles_fund ON cycles(fund_id, created_at);
"""

_IMMUTABLE_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS funds_no_update
BEFORE UPDATE ON funds
BEGIN
    SELECT RAISE(ABORT, 'funds is append-only; UPDATE forbidden');
END;
CREATE TRIGGER IF NOT EXISTS funds_no_delete
BEFORE DELETE ON funds
BEGIN
    SELECT RAISE(ABORT, 'funds is append-only; DELETE forbidden');
END;
CREATE TRIGGER IF NOT EXISTS cycles_no_update
BEFORE UPDATE ON cycles
BEGIN
    SELECT RAISE(ABORT, 'cycles is append-only; UPDATE forbidden');
END;
CREATE TRIGGER IF NOT EXISTS cycles_no_delete
BEFORE DELETE ON cycles
BEGIN
    SELECT RAISE(ABORT, 'cycles is append-only; DELETE forbidden');
END;
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events is append-only; UPDATE forbidden');
END;
CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events is append-only; DELETE forbidden');
END;
"""


class PaperFundLedger:
    """SQLite-backed append-only paper fund ledger.

    Initializes a fund exactly once, executes atomic cycles, reconstructs state
    from the latest completed cycle, and verifies the audit hash chain.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._open()

    def _open(self) -> None:
        if self._conn is not None:
            return
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.executescript(_SCHEMA)
        conn.executescript(_IMMUTABLE_TRIGGERS)
        conn.commit()
        self._conn = conn

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise PaperFundError("ledger is closed")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Self:
        self._open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connection
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _latest_event_hash(self, conn: sqlite3.Connection, fund_id: str) -> tuple[int, str]:
        row = conn.execute(
            "SELECT sequence, event_hash FROM events WHERE fund_id = ? ORDER BY sequence DESC LIMIT 1",
            (fund_id,),
        ).fetchone()
        if row is None:
            return 0, GENESIS_HASH
        return int(row["sequence"]), str(row["event_hash"])

    def _append_event(
        self,
        conn: sqlite3.Connection,
        *,
        fund_id: str,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: datetime | None = None,
    ) -> int:
        occurred = (occurred_at or _utc_now()).astimezone(UTC)
        occurred_s = _iso_z(occurred)
        payload_json = _canonical_json(payload)
        prev_seq, prev_hash = self._latest_event_hash(conn, fund_id)
        sequence = prev_seq + 1
        event_hash = _event_hash(prev_hash, sequence, event_type, occurred_s, payload_json)
        conn.execute(
            """
            INSERT INTO events (
                fund_id, sequence, event_type, occurred_at, payload_json, prev_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (fund_id, sequence, event_type, occurred_s, payload_json, prev_hash, event_hash),
        )
        return sequence

    def initialize(
        self,
        fund_id: str,
        mandate: FundMandate | None = None,
        *,
        created_at: datetime | None = None,
    ) -> FundState:
        """Capitalize a fund exactly once. Subsequent calls with same id raise."""
        mandate = mandate or FundMandate()
        created = (created_at or _utc_now()).astimezone(UTC)
        if not fund_id.strip():
            raise PaperFundValidationError("fund_id must be non-empty")

        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT fund_id FROM funds WHERE fund_id = ?", (fund_id,)
            ).fetchone()
            if existing is not None:
                raise PaperFundValidationError(
                    f"fund {fund_id} already initialized; capitalization is one-time"
                )
            conn.execute(
                """
                INSERT INTO funds (fund_id, created_at, mandate_json, initial_cash)
                VALUES (?, ?, ?, ?)
                """,
                (
                    fund_id,
                    _iso_z(created),
                    mandate.model_dump_json(),
                    str(mandate.initial_cash),
                ),
            )
            state = _initial_state(fund_id, mandate.initial_cash, created)
            self._append_event(
                conn,
                fund_id=fund_id,
                event_type="fund_initialized",
                payload={
                    "fund_id": fund_id,
                    "initial_cash": str(mandate.initial_cash),
                    "mandate": json.loads(mandate.model_dump_json()),
                },
                occurred_at=created,
            )
            return state

    def _load_mandate(self, conn: sqlite3.Connection, fund_id: str) -> FundMandate:
        row = conn.execute(
            "SELECT mandate_json FROM funds WHERE fund_id = ?", (fund_id,)
        ).fetchone()
        if row is None:
            raise PaperFundValidationError(f"fund {fund_id} is not initialized")
        return FundMandate.model_validate_json(row["mandate_json"])

    def _load_latest_state(self, conn: sqlite3.Connection, fund_id: str) -> FundState:
        row = conn.execute(
            """
            SELECT state_json FROM cycles
            WHERE fund_id = ?
            ORDER BY created_at DESC, cycle_key DESC
            LIMIT 1
            """,
            (fund_id,),
        ).fetchone()
        if row is not None:
            return FundState.model_validate_json(row["state_json"])

        fund = conn.execute(
            "SELECT created_at, initial_cash FROM funds WHERE fund_id = ?",
            (fund_id,),
        ).fetchone()
        if fund is None:
            raise PaperFundValidationError(f"fund {fund_id} is not initialized")
        cash = Decimal(fund["initial_cash"])
        created = _parse_iso_z(fund["created_at"])
        return _initial_state(fund_id, cash, created)

    def get_state(self, fund_id: str) -> FundState:
        return self._load_latest_state(self.connection, fund_id)

    def get_mandate(self, fund_id: str) -> FundMandate:
        return self._load_mandate(self.connection, fund_id)

    def list_cycles(self, fund_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT fund_id, cycle_key, decision_id, as_of, action, request_digest, created_at
            FROM cycles WHERE fund_id = ? ORDER BY created_at ASC, cycle_key ASC
            """,
            (fund_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _cycle_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        result = CycleResult.model_validate_json(row["result_json"])
        return {
            "fund_id": row["fund_id"],
            "cycle_key": row["cycle_key"],
            "decision_id": row["decision_id"],
            "as_of": row["as_of"],
            "action": row["action"],
            "request_digest": row["request_digest"],
            "created_at": row["created_at"],
            "decision": json.loads(row["decision_json"]),
            "quotes": json.loads(row["quotes_json"]),
            "fills": json.loads(row["fills_json"]),
            "settlements": json.loads(row["settlements_json"]),
            "state": json.loads(row["state_json"]),
            "result": result.model_dump(mode="json"),
            "audit": (result.audit.model_dump(mode="json") if result.audit is not None else None),
        }

    def list_full_cycles(self, fund_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT fund_id, cycle_key, decision_id, as_of, action, request_digest,
                   decision_json, quotes_json, fills_json, settlements_json,
                   state_json, result_json, created_at
            FROM cycles WHERE fund_id = ? ORDER BY created_at ASC, cycle_key ASC
            """,
            (fund_id,),
        ).fetchall()
        return [self._cycle_from_row(row) for row in rows]

    def get_cycle(self, fund_id: str, cycle_key: str) -> dict[str, Any]:
        """Return the full immutable cycle row used for audit and replay."""
        row = self.connection.execute(
            """
            SELECT fund_id, cycle_key, decision_id, as_of, action, request_digest,
                   decision_json, quotes_json, fills_json, settlements_json,
                   state_json, result_json, created_at
            FROM cycles WHERE fund_id = ? AND cycle_key = ?
            """,
            (fund_id, cycle_key),
        ).fetchone()
        if row is None:
            raise PaperFundValidationError(f"cycle {cycle_key!r} not found for fund {fund_id}")
        return self._cycle_from_row(row)

    def cycle_audit(self, fund_id: str, cycle_key: str) -> dict[str, Any]:
        """Join one cycle with related events and sidecar completeness gaps.

        Does not replay accounting; run verify() for hash-chain and book integrity.
        """
        cycle = self.get_cycle(fund_id, cycle_key)
        related = [
            event.model_dump(mode="json")
            for event in self.list_events(fund_id)
            if event.payload.get("cycle_key") == cycle_key
        ]
        audit = cycle.get("audit") or {}
        gaps: list[str] = []
        if not audit:
            gaps.append("No structured audit sidecar recorded for this cycle")
        else:
            if audit.get("risk") is None:
                gaps.append("No structured risk evaluation recorded for this cycle")
            runtime = audit.get("runtime") or {}
            if not runtime.get("edgecraft_version"):
                gaps.append("Runtime provenance is missing edgecraft_version")
            if not runtime.get("mandate_digest"):
                gaps.append("Runtime provenance is missing mandate_digest")
        if not related:
            gaps.append("No hash-chained event references this cycle_key")
        return {
            "schema_version": "edgecraft.fund-cycle-audit-view.v1",
            "generated_at": _iso_z(_utc_now()),
            "fund_id": fund_id,
            "cycle_key": cycle_key,
            "cycle": cycle,
            "audit": audit,
            "events": related,
            "audit_gaps": gaps,
            "reconciliation": {
                "request_digest": cycle["request_digest"],
                "event_count": len(related),
                "has_audit_sidecar": bool(audit),
            },
        }

    def state_history(self, fund_id: str) -> list[dict[str, Any]]:
        """Return the immutable NAV/exposure path recorded after every cycle."""
        rows = self.connection.execute(
            """
            SELECT cycle_key, decision_id, action, state_json, result_json
            FROM cycles WHERE fund_id = ? ORDER BY created_at ASC, cycle_key ASC
            """,
            (fund_id,),
        ).fetchall()
        history: list[dict[str, Any]] = []
        for row in rows:
            state = FundState.model_validate_json(row["state_json"])
            result = CycleResult.model_validate_json(row["result_json"])
            history.append(
                {
                    "cycle_key": row["cycle_key"],
                    "decision_id": row["decision_id"],
                    "action": row["action"],
                    "as_of": _iso_z(state.as_of),
                    "nav": str(state.nav),
                    "cash": str(state.cash),
                    "gross_exposure": str(state.gross_exposure),
                    "net_exposure": str(state.net_exposure),
                    "short_exposure": str(state.short_exposure),
                    "drawdown": str(state.drawdown),
                    "fill_count": len(result.fills),
                    "settlement_count": len(result.settlements),
                }
            )
        return history

    def list_events(self, fund_id: str) -> list[AuditEvent]:
        rows = self.connection.execute(
            """
            SELECT sequence, event_type, occurred_at, payload_json, prev_hash, event_hash
            FROM events WHERE fund_id = ? ORDER BY sequence ASC
            """,
            (fund_id,),
        ).fetchall()
        events: list[AuditEvent] = []
        for row in rows:
            occurred = _parse_iso_z(row["occurred_at"])
            events.append(
                AuditEvent(
                    sequence=int(row["sequence"]),
                    event_type=row["event_type"],
                    occurred_at=occurred,
                    payload=json.loads(row["payload_json"]),
                    prev_hash=row["prev_hash"],
                    event_hash=row["event_hash"],
                )
            )
        return events

    def record_operational_event(
        self,
        fund_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        occurred_at: datetime | None = None,
    ) -> int:
        """Append a non-accounting lifecycle/operations event to the hash chain."""
        if not event_type.startswith(("playbook_", "postmortem_", "alert_")):
            raise PaperFundValidationError("unsupported operational event type")
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM funds WHERE fund_id = ?", (fund_id,)).fetchone() is None:
                raise PaperFundValidationError(f"fund {fund_id!r} is not initialized")
            return self._append_event(
                conn,
                fund_id=fund_id,
                event_type=event_type,
                payload=dict(payload),
                occurred_at=occurred_at,
            )

    def execute_cycle(
        self,
        decision: FundDecision,
        quotes: Sequence[FundQuote],
        *,
        runtime: CycleRuntimeMetadata | None = None,
        require_brain_journal: bool = False,
        decision_audit: dict[str, Any] | None = None,
    ) -> CycleResult:
        """Execute atomically and retain rejected normalized requests in the audit chain."""
        try:
            return self._execute_cycle(
                decision,
                quotes,
                runtime=runtime,
                require_brain_journal=require_brain_journal,
                decision_audit=decision_audit,
            )
        except (PaperFundValidationError, PaperFundIdempotencyError) as exc:
            self._record_rejection(decision, quotes, exc, runtime=runtime)
            raise

    def _record_rejection(
        self,
        decision: FundDecision,
        quotes: Sequence[FundQuote],
        error: PaperFundError,
        *,
        runtime: CycleRuntimeMetadata | None = None,
    ) -> None:
        digest = request_digest(decision, quotes)
        with self._transaction() as conn:
            exists = conn.execute(
                "SELECT 1 FROM funds WHERE fund_id = ?", (decision.fund_id,)
            ).fetchone()
            if exists is None:
                return
            mandate = self._load_mandate(conn, decision.fund_id)
            runtime_payload = self._runtime_for_cycle(mandate, runtime)
            payload: dict[str, Any] = {
                "fund_id": decision.fund_id,
                "cycle_key": decision.cycle_key,
                "decision_id": decision.decision_id,
                "request_digest": digest,
                "error_type": type(error).__name__,
                "reason": str(error),
                "decision": decision.model_dump(mode="json"),
                "quotes": [quote.model_dump(mode="json") for quote in quotes],
                "thesis": decision.thesis,
                "alternatives": decision.alternatives,
                "risks": decision.risks,
                "runtime": runtime_payload.model_dump(mode="json"),
                "quote_freshness": [
                    item.model_dump(mode="json")
                    for item in _quote_freshness_records(
                        mandate=mandate, as_of=decision.as_of, quotes=quotes
                    )
                ],
            }
            if isinstance(error, PaperFundError) and error.audit:
                payload.update(error.audit)
            self._append_event(
                conn,
                fund_id=decision.fund_id,
                event_type="cycle_rejected",
                payload=payload,
            )

    @staticmethod
    def _runtime_for_cycle(
        mandate: FundMandate,
        runtime: CycleRuntimeMetadata | None,
    ) -> CycleRuntimeMetadata:
        from edgecraft import __version__

        if runtime is None:
            return CycleRuntimeMetadata(
                edgecraft_version=__version__,
                mandate_digest=mandate_digest(mandate),
                recorded_at=_utc_now(),
            )
        return runtime.model_copy(
            update={
                "edgecraft_version": runtime.edgecraft_version or __version__,
                "mandate_digest": runtime.mandate_digest or mandate_digest(mandate),
                "recorded_at": runtime.recorded_at or _utc_now(),
            }
        )

    def _execute_cycle(
        self,
        decision: FundDecision,
        quotes: Sequence[FundQuote],
        *,
        runtime: CycleRuntimeMetadata | None = None,
        require_brain_journal: bool = False,
        decision_audit: dict[str, Any] | None = None,
    ) -> CycleResult:
        """Execute one atomic cycle, or replay if the exact request was stored."""
        digest = request_digest(decision, quotes)

        with self._transaction() as conn:
            mandate = self._load_mandate(conn, decision.fund_id)
            existing = conn.execute(
                """
                SELECT request_digest, result_json FROM cycles
                WHERE fund_id = ? AND cycle_key = ?
                """,
                (decision.fund_id, decision.cycle_key),
            ).fetchone()
            if existing is not None:
                if existing["request_digest"] != digest:
                    raise PaperFundIdempotencyError(
                        f"cycle_key {decision.cycle_key!r} already used with different request"
                    )
                result = CycleResult.model_validate_json(existing["result_json"])
                return result.model_copy(update={"replayed": True})

            prior = self._load_latest_state(conn, decision.fund_id)
            if require_brain_journal:
                validate_decision_journal(decision, prior)
            outcome = run_cycle_accounting(
                mandate=mandate,
                prior_state=prior,
                decision=decision,
                quotes=quotes,
            )
            fills = list(outcome.fills)
            settlements = list(outcome.settlements)
            new_state = outcome.state
            runtime_payload = self._runtime_for_cycle(mandate, runtime)
            fee_total = sum((fill.fee for fill in fills + settlements), ZERO)
            audit = CycleAuditRecord(
                runtime=runtime_payload,
                risk=outcome.risk,
                quote_freshness=outcome.quote_freshness,
                fee_total=fee_total,
                fill_count=len(fills),
                settlement_count=len(settlements),
                sleeve_allocation=(decision_audit or {}).get("sleeve_allocation", {}),
                sizing=(decision_audit or {}).get("sizing"),
            )

            result = CycleResult(
                fund_id=decision.fund_id,
                cycle_key=decision.cycle_key,
                decision_id=decision.decision_id,
                action=decision.action,
                as_of=decision.as_of,
                fills=tuple(fills),
                settlements=tuple(settlements),
                state=new_state,
                request_digest=digest,
                replayed=False,
                event_sequence=0,  # filled after event insert
                audit=audit,
            )

            created = _utc_now()
            sequence = self._append_event(
                conn,
                fund_id=decision.fund_id,
                event_type="cycle_completed",
                payload={
                    "fund_id": decision.fund_id,
                    "cycle_key": decision.cycle_key,
                    "decision_id": decision.decision_id,
                    "action": decision.action.value,
                    "request_digest": digest,
                    "fill_count": len(fills),
                    "settlement_count": len(settlements),
                    "nav": str(new_state.nav),
                    "cash": str(new_state.cash),
                    "thesis": decision.thesis,
                    "alternatives": decision.alternatives,
                    "risks": decision.risks,
                    "decision": decision.model_dump(mode="json"),
                    "quotes": [quote.model_dump(mode="json") for quote in quotes],
                    "fills": [fill.model_dump(mode="json") for fill in fills],
                    "settlements": [
                        settlement.model_dump(mode="json") for settlement in settlements
                    ],
                    "state": new_state.model_dump(mode="json"),
                    "audit": audit.model_dump(mode="json"),
                    "fee_total": str(fee_total),
                },
                occurred_at=decision.as_of,
            )
            result = result.model_copy(update={"event_sequence": sequence})

            conn.execute(
                """
                INSERT INTO cycles (
                    fund_id, cycle_key, decision_id, as_of, action, request_digest,
                    decision_json, quotes_json, fills_json, settlements_json,
                    state_json, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.fund_id,
                    decision.cycle_key,
                    decision.decision_id,
                    _iso_z(decision.as_of),
                    decision.action.value,
                    digest,
                    decision.model_dump_json(),
                    _canonical_json([q.model_dump(mode="json") for q in quotes]),
                    _canonical_json([f.model_dump(mode="json") for f in fills]),
                    _canonical_json([s.model_dump(mode="json") for s in settlements]),
                    new_state.model_dump_json(),
                    result.model_dump_json(),
                    _iso_z(created),
                ),
            )
            return result

    def verify(
        self, fund_id: str | None = None, *, raise_on_error: bool = True
    ) -> VerificationReport:
        """Recompute event hash chain and check state/accounting consistency."""
        conn = self.connection
        details: list[str] = []
        chain_ok = True
        accounting_ok = True

        if fund_id is None:
            row = conn.execute("SELECT fund_id FROM funds LIMIT 1").fetchone()
            fund_id = row["fund_id"] if row else None
        if fund_id is None:
            report = VerificationReport(
                ok=True,
                fund_id=None,
                event_count=0,
                cycle_count=0,
                chain_ok=True,
                accounting_ok=True,
                details=["no funds present"],
            )
            return report

        events = conn.execute(
            """
            SELECT sequence, event_type, occurred_at, payload_json, prev_hash, event_hash
            FROM events WHERE fund_id = ? ORDER BY sequence ASC
            """,
            (fund_id,),
        ).fetchall()
        prev_hash = GENESIS_HASH
        expected_seq = 1
        for row in events:
            seq = int(row["sequence"])
            if seq != expected_seq:
                chain_ok = False
                details.append(f"event sequence gap: expected {expected_seq}, got {seq}")
            material_hash = _event_hash(
                prev_hash,
                seq,
                row["event_type"],
                row["occurred_at"],
                row["payload_json"],
            )
            if row["prev_hash"] != prev_hash:
                chain_ok = False
                details.append(f"event {seq} prev_hash mismatch")
            if row["event_hash"] != material_hash:
                chain_ok = False
                details.append(f"event {seq} event_hash mismatch")
            prev_hash = row["event_hash"]
            expected_seq = seq + 1

        # Replay accounting from init
        fund_row = conn.execute(
            "SELECT mandate_json, initial_cash, created_at FROM funds WHERE fund_id = ?",
            (fund_id,),
        ).fetchone()
        if fund_row is None:
            accounting_ok = False
            details.append(f"fund {fund_id} missing")
        else:
            mandate = FundMandate.model_validate_json(fund_row["mandate_json"])
            cash = Decimal(fund_row["initial_cash"])
            if cash != mandate.initial_cash:
                accounting_ok = False
                details.append("initial_cash does not match mandate")
            created = _parse_iso_z(fund_row["created_at"])
            state = _initial_state(fund_id, cash, created)
            cycles = conn.execute(
                """
                SELECT decision_json, quotes_json, state_json, request_digest
                FROM cycles WHERE fund_id = ?
                ORDER BY created_at ASC, cycle_key ASC
                """,
                (fund_id,),
            ).fetchall()
            for crow in cycles:
                decision = FundDecision.model_validate_json(crow["decision_json"])
                quotes = [FundQuote.model_validate(q) for q in json.loads(crow["quotes_json"])]
                digest = request_digest(decision, quotes)
                if digest != crow["request_digest"]:
                    accounting_ok = False
                    details.append(f"request digest mismatch for cycle {decision.cycle_key}")
                try:
                    outcome = run_cycle_accounting(
                        mandate=mandate,
                        prior_state=state,
                        decision=decision,
                        quotes=quotes,
                    )
                    state = outcome.state
                except PaperFundError as exc:
                    accounting_ok = False
                    details.append(f"replay failed for {decision.cycle_key}: {exc}")
                    break
                stored = FundState.model_validate_json(crow["state_json"])
                if stored != state:
                    accounting_ok = False
                    details.append(f"full state mismatch after cycle {decision.cycle_key}")

        cycle_count = conn.execute(
            "SELECT COUNT(*) AS c FROM cycles WHERE fund_id = ?", (fund_id,)
        ).fetchone()["c"]
        ok = chain_ok and accounting_ok
        report = VerificationReport(
            ok=ok,
            fund_id=fund_id,
            event_count=len(events),
            cycle_count=int(cycle_count),
            chain_ok=chain_ok,
            accounting_ok=accounting_ok,
            details=details,
        )
        if not ok and raise_on_error:
            raise PaperFundIntegrityError(
                f"verification failed: {'; '.join(details) if details else 'unknown'}"
            )
        return report
