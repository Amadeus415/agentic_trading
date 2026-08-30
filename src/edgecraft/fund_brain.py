"""Compact, deterministic learning memory for the active paper fund.

This module summarizes the immutable ledger for the next reasoning cycle. It
stores decision-relevant rationale and outcomes, never private chain-of-thought.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from edgecraft.paper_fund import FundHypothesis, PaperFundLedger

ZERO = Decimal("0")


class CycleMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_key: str
    as_of: datetime
    action: str
    thesis: str
    what_changed: str | None = None
    ending_nav: Decimal
    ending_position_count: int = Field(ge=0)
    fill_count: int = Field(ge=0)
    fee_total: Decimal = Field(ge=0)
    next_cycle_nav_change: Decimal | None = None
    next_cycle_outcome: str


class FundActivityMemory(BaseModel):
    """Compact activity snapshot used to counteract idle-cash drift."""

    model_config = ConfigDict(extra="forbid")

    style: str = "short_term_active"
    cash_nav_weight: Decimal
    open_position_count: int = Field(ge=0)
    consecutive_all_cash_holds: int = Field(ge=0)
    recent_trade_cycles: int = Field(ge=0)
    idle_cash: bool


class InstrumentMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str
    asset_class: str
    current_quantity: Decimal = ZERO
    current_unrealized_pnl: Decimal | None = None
    simulated_fill_count: int = Field(ge=0)
    realized_exit_count: int = Field(ge=0)
    profitable_exit_count: int = Field(ge=0)
    losing_exit_count: int = Field(ge=0)
    realized_pnl: Decimal = ZERO
    fees_paid: Decimal = ZERO
    latest_hypothesis: FundHypothesis | None = None


class RejectionMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_key: str | None = None
    reason: str
    error_type: str


class FundBrainSnapshot(BaseModel):
    """Small feedback packet supplied to the next autonomous decision."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "edgecraft.fund-brain.v1"
    generated_at: datetime
    fund_id: str
    learning_boundary: str
    recent_cycles: tuple[CycleMemory, ...] = ()
    instruments: tuple[InstrumentMemory, ...] = ()
    recent_rejections: tuple[RejectionMemory, ...] = ()
    activity: FundActivityMemory
    adaptive_prompts: tuple[str, ...] = ()


def build_fund_brain(
    ledger: PaperFundLedger,
    fund_id: str,
    *,
    generated_at: datetime | None = None,
    cycle_limit: int = 8,
    instrument_limit: int = 40,
    rejection_limit: int = 5,
) -> FundBrainSnapshot:
    """Summarize decisions and realized outcomes without changing fund state."""
    state = ledger.get_state(fund_id)
    cycles = ledger.list_full_cycles(fund_id)
    current_positions = {position.instrument_id: position for position in state.positions}

    instrument_rows: dict[str, dict[str, Any]] = {}
    last_activity: dict[str, int] = {}
    cycle_memories: list[CycleMemory] = []

    for index, cycle in enumerate(cycles):
        decision = cycle["decision"]
        journal = decision.get("journal") or {}
        for hypothesis in journal.get("hypotheses", []):
            instrument_id = str(hypothesis["instrument_id"])
            row = instrument_rows.setdefault(instrument_id, _empty_instrument(instrument_id))
            row["latest_hypothesis"] = FundHypothesis.model_validate(hypothesis)
            last_activity[instrument_id] = index

        fills = [*cycle["fills"], *cycle["settlements"]]
        for fill in fills:
            instrument_id = str(fill["instrument_id"])
            row = instrument_rows.setdefault(instrument_id, _empty_instrument(instrument_id))
            row["asset_class"] = str(fill["asset_class"])
            row["simulated_fill_count"] += 1
            realized = Decimal(str(fill["realized_pnl"]))
            row["realized_pnl"] += realized
            row["fees_paid"] += Decimal(str(fill["fee"]))
            if str(fill["side"]) in {"sell", "cover", "settle"}:
                row["realized_exit_count"] += 1
                if realized > ZERO:
                    row["profitable_exit_count"] += 1
                elif realized < ZERO:
                    row["losing_exit_count"] += 1
            last_activity[instrument_id] = index

        ending_nav = Decimal(str(cycle["state"]["nav"]))
        ending_positions = cycle["state"].get("positions") or []
        next_change: Decimal | None = None
        outcome = "pending"
        if index + 1 < len(cycles):
            next_nav = Decimal(str(cycles[index + 1]["state"]["nav"]))
            next_change = next_nav - ending_nav
            outcome = (
                "positive" if next_change > ZERO else "negative" if next_change < ZERO else "flat"
            )
        audit = cycle.get("audit") or {}
        cycle_memories.append(
            CycleMemory(
                cycle_key=str(cycle["cycle_key"]),
                as_of=datetime.fromisoformat(str(cycle["as_of"]).replace("Z", "+00:00")).astimezone(
                    UTC
                ),
                action=str(cycle["action"]),
                thesis=str(decision["thesis"]),
                what_changed=journal.get("what_changed"),
                ending_nav=ending_nav,
                ending_position_count=len(ending_positions),
                fill_count=len(fills),
                fee_total=Decimal(str(audit.get("fee_total", "0"))),
                next_cycle_nav_change=next_change,
                next_cycle_outcome=outcome,
            )
        )

    for instrument_id, position in current_positions.items():
        row = instrument_rows.setdefault(instrument_id, _empty_instrument(instrument_id))
        row["asset_class"] = position.asset_class.value
        row["current_quantity"] = position.quantity
        row["current_unrealized_pnl"] = position.unrealized_pnl
        last_activity.setdefault(instrument_id, len(cycles))

    ranked_instruments = sorted(
        instrument_rows,
        key=lambda item: (item not in current_positions, -last_activity.get(item, -1), item),
    )[:instrument_limit]
    instruments = tuple(
        InstrumentMemory.model_validate(instrument_rows[item]) for item in ranked_instruments
    )

    rejections = [
        RejectionMemory(
            cycle_key=event.payload.get("cycle_key"),
            reason=str(event.payload.get("reason", "unknown rejection")),
            error_type=str(event.payload.get("error_type", "PaperFundError")),
        )
        for event in ledger.list_events(fund_id)
        if event.event_type == "cycle_rejected"
    ][-rejection_limit:]

    recent = tuple(cycle_memories[-cycle_limit:])
    activity = _activity_memory(state, recent)
    return FundBrainSnapshot(
        generated_at=(generated_at or datetime.now(UTC)).astimezone(UTC),
        fund_id=fund_id,
        learning_boundary=(
            "Next-cycle NAV direction includes intervening marks, costs, and portfolio changes; "
            "it is feedback, not causal attribution or proof of skill."
        ),
        recent_cycles=recent,
        instruments=instruments,
        recent_rejections=tuple(rejections),
        activity=activity,
        adaptive_prompts=_adaptive_prompts(instruments, tuple(rejections), activity),
    )


def _empty_instrument(instrument_id: str) -> dict[str, Any]:
    return {
        "instrument_id": instrument_id,
        "asset_class": "unknown",
        "current_quantity": ZERO,
        "current_unrealized_pnl": None,
        "simulated_fill_count": 0,
        "realized_exit_count": 0,
        "profitable_exit_count": 0,
        "losing_exit_count": 0,
        "realized_pnl": ZERO,
        "fees_paid": ZERO,
        "latest_hypothesis": None,
    }


def _activity_memory(
    state: Any,
    recent_cycles: tuple[CycleMemory, ...],
) -> FundActivityMemory:
    nav = Decimal(str(state.nav))
    cash_weight = Decimal("1") if nav == ZERO else (Decimal(str(state.cash)) / nav)
    consecutive = 0
    for item in reversed(recent_cycles):
        if item.action == "hold" and item.ending_position_count == 0:
            consecutive += 1
            continue
        break
    return FundActivityMemory(
        cash_nav_weight=cash_weight,
        open_position_count=len(state.positions),
        consecutive_all_cash_holds=consecutive,
        recent_trade_cycles=sum(1 for item in recent_cycles if item.action == "trade"),
        idle_cash=len(state.positions) == 0,
    )


def _adaptive_prompts(
    instruments: tuple[InstrumentMemory, ...],
    rejections: tuple[RejectionMemory, ...],
    activity: FundActivityMemory,
) -> tuple[str, ...]:
    prompts = [
        "This is a short-term active book: express researched 4-72h views with orders.",
        "A sourced catalyst, target, invalidation, and size is a valid thesis; "
        "lack of a calibrated probability model is not a hold reason.",
        "U.S. cash-equity close is not a reason to stay in cash; native crypto "
        "and prediction markets remain in scope.",
        "Re-test every open position against its current falsifiers before adding risk.",
        "Compare new opportunities with the opportunity cost of every existing position.",
    ]
    if activity.idle_cash:
        prompts.insert(
            0,
            "The book is 100% cash. A scheduled hold will be rejected. Submit "
            "researched short-term buy/sell/short/cover orders with fresh quotes.",
        )
        if activity.consecutive_all_cash_holds:
            prompts.insert(
                1,
                f"The last {activity.consecutive_all_cash_holds} completed cycle(s) "
                "were all-cash holds. Idle cash is a process miss, not prudence.",
            )
    losing = [item.instrument_id for item in instruments if item.losing_exit_count > 0]
    if losing:
        prompts.append(
            "Review whether the mechanisms or sizing failed on prior losing exits: "
            + ", ".join(losing[:8])
            + "."
        )
    underwater = [
        item.instrument_id
        for item in instruments
        if item.current_unrealized_pnl is not None and item.current_unrealized_pnl < ZERO
    ]
    if underwater:
        prompts.append(
            "Explicitly keep, reduce, or exit currently underwater hypotheses: "
            + ", ".join(underwater[:8])
            + "."
        )
    if rejections:
        prompts.append(
            "Do not bypass prior rejected gates; fix the research or portfolio plan upstream."
        )
    return tuple(prompts)
