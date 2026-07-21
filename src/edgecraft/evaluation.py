from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from math import sqrt
from statistics import mean, stdev
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from edgecraft.autonomy_models import Mandate
from edgecraft.execution_models import MarketQuote, TradeProposal

ZERO = Decimal("0")
ONE = Decimal("1")
SLEEVES = ("agent", "benchmark", "strategic")


class EvaluationSleeve(BaseModel):
    cash: Decimal = Field(default=ZERO, ge=ZERO)
    positions: dict[str, Decimal] = Field(default_factory=dict)
    total_contributions: Decimal = Field(default=ZERO, ge=ZERO)
    total_costs: Decimal = Field(default=ZERO, ge=ZERO)

    @field_validator("positions")
    @classmethod
    def positive_positions(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        clean = {symbol.strip().upper(): quantity for symbol, quantity in value.items()}
        if any(not symbol or quantity < ZERO for symbol, quantity in clean.items()):
            raise ValueError("evaluation positions require symbols and non-negative quantities")
        return {symbol: quantity for symbol, quantity in clean.items() if quantity > ZERO}


class EvaluationState(BaseModel):
    schema_version: str = "edgecraft.evaluation-state.v1"
    mandate_id: str
    benchmark: str
    updated_at: datetime
    agent: EvaluationSleeve = Field(default_factory=EvaluationSleeve)
    benchmark_sleeve: EvaluationSleeve = Field(default_factory=EvaluationSleeve)
    strategic: EvaluationSleeve = Field(default_factory=EvaluationSleeve)

    @field_validator("updated_at")
    @classmethod
    def aware_updated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("evaluation updated_at must include a timezone")
        return value.astimezone(UTC)


class EvaluationObservation(BaseModel):
    schema_version: str = "edgecraft.evaluation-observation.v1"
    run_id: str
    mandate_id: str
    cycle_key: str
    observed_at: datetime
    benchmark: str
    contribution: Decimal = Field(gt=ZERO)
    cost_bps: Decimal = Field(ge=ZERO, le=Decimal("1000"))
    agent_action: Literal["invest", "hold"]
    prices: dict[str, Decimal]
    pre_contribution_values: dict[str, Decimal]
    post_trade_values: dict[str, Decimal]
    period_costs: dict[str, Decimal]

    @field_validator("observed_at")
    @classmethod
    def aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("evaluation observed_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def complete_sleeves(self) -> EvaluationObservation:
        for field_name in ("pre_contribution_values", "post_trade_values", "period_costs"):
            value = getattr(self, field_name)
            if set(value) != set(SLEEVES):
                raise ValueError(f"{field_name} must contain all evaluation sleeves")
        return self


def advance_evaluation(
    mandate: Mandate,
    proposal: TradeProposal,
    quotes: list[MarketQuote],
    *,
    run_id: str,
    cycle_key: str,
    observed_at: datetime,
    prior: EvaluationState | None,
    cost_bps: Decimal = Decimal("10"),
) -> tuple[EvaluationState, EvaluationObservation]:
    """Advance cash-flow-matched agent, S&P benchmark, and strategic shadow books."""
    quote_map = {quote.symbol: Decimal(str(quote.last)) for quote in quotes}
    required = {mandate.benchmark, *mandate.strategic_weights}
    if prior is not None:
        required.update(prior.agent.positions)
        required.update(prior.benchmark_sleeve.positions)
        required.update(prior.strategic.positions)
    missing = sorted(required - set(quote_map))
    if missing:
        raise ValueError(f"evaluation is missing quotes for: {missing}")
    if prior is not None and (
        prior.mandate_id != mandate.mandate_id or prior.benchmark != mandate.benchmark
    ):
        raise ValueError("evaluation state does not match the active mandate and benchmark")

    state = (
        prior.model_copy(deep=True)
        if prior is not None
        else EvaluationState(
            mandate_id=mandate.mandate_id,
            benchmark=mandate.benchmark,
            updated_at=observed_at,
        )
    )
    sleeves = {
        "agent": state.agent,
        "benchmark": state.benchmark_sleeve,
        "strategic": state.strategic,
    }
    pre_values = {name: _value(sleeve, quote_map) for name, sleeve in sleeves.items()}
    contribution = mandate.cycle_budget
    for sleeve in sleeves.values():
        sleeve.cash += contribution
        sleeve.total_contributions += contribution

    rate = cost_bps / Decimal("10000")
    period_costs = {name: ZERO for name in SLEEVES}
    agent_action: Literal["invest", "hold"] = "hold"
    if proposal.risk.approved_for_review and proposal.orders:
        for order in proposal.orders:
            notional = Decimal(str(order.notional))
            _buy(state.agent, order.symbol, notional, quote_map[order.symbol], rate)
            period_costs["agent"] += notional * rate
        agent_action = "invest"

    _buy(
        state.benchmark_sleeve,
        mandate.benchmark,
        contribution,
        quote_map[mandate.benchmark],
        rate,
    )
    period_costs["benchmark"] = contribution * rate
    for symbol, weight in mandate.strategic_weights.items():
        notional = contribution * Decimal(str(weight))
        _buy(state.strategic, symbol, notional, quote_map[symbol], rate)
        period_costs["strategic"] += notional * rate

    for name, sleeve in sleeves.items():
        sleeve.total_costs += period_costs[name]
    post_values = {name: _value(sleeve, quote_map) for name, sleeve in sleeves.items()}
    state.updated_at = observed_at
    observation = EvaluationObservation(
        run_id=run_id,
        mandate_id=mandate.mandate_id,
        cycle_key=cycle_key,
        observed_at=observed_at,
        benchmark=mandate.benchmark,
        contribution=contribution,
        cost_bps=cost_bps,
        agent_action=agent_action,
        prices={symbol: quote_map[symbol] for symbol in sorted(required)},
        pre_contribution_values=pre_values,
        post_trade_values=post_values,
        period_costs=period_costs,
    )
    return state, observation


def evaluation_report(
    state: EvaluationState | None,
    observations: list[EvaluationObservation],
) -> dict:
    if state is None or not observations:
        return {
            "schema_version": "edgecraft.evaluation-report.v1",
            "status": "no_history",
            "observation_count": 0,
        }
    ordered = sorted(observations, key=lambda item: item.observed_at)
    sleeve_states = {
        "agent": state.agent,
        "benchmark": state.benchmark_sleeve,
        "strategic": state.strategic,
    }
    returns = {name: _period_returns(ordered, name) for name in SLEEVES}
    metrics = {
        name: _sleeve_metrics(ordered, name, sleeve_states[name], returns[name]) for name in SLEEVES
    }
    excess = [
        agent - benchmark
        for agent, benchmark in zip(returns["agent"], returns["benchmark"], strict=True)
    ]
    tracking_error = stdev(excess) * sqrt(252) if len(excess) >= 2 else None
    information_ratio = (
        mean(excess) * 252 / tracking_error
        if tracking_error is not None and tracking_error > 0
        else None
    )
    return {
        "schema_version": "edgecraft.evaluation-report.v1",
        "status": "measuring" if len(ordered) < 20 else "active",
        "mandate_id": state.mandate_id,
        "benchmark": state.benchmark,
        "first_observed_at": ordered[0].observed_at.isoformat(),
        "last_observed_at": ordered[-1].observed_at.isoformat(),
        "observation_count": len(ordered),
        "invest_decisions": sum(item.agent_action == "invest" for item in ordered),
        "hold_decisions": sum(item.agent_action == "hold" for item in ordered),
        "sleeves": metrics,
        "agent_excess_return_on_contributions": (
            metrics["agent"]["return_on_contributions"]
            - metrics["benchmark"]["return_on_contributions"]
        ),
        "annualized_tracking_error": tracking_error,
        "information_ratio": information_ratio,
        "minimum_interpretation": (
            "Directional only until at least 20 daily observations; a credible live conclusion "
            "requires a much longer frozen evaluation period."
        ),
    }


def _buy(
    sleeve: EvaluationSleeve,
    symbol: str,
    notional: Decimal,
    price: Decimal,
    rate: Decimal,
) -> None:
    if notional <= ZERO or notional > sleeve.cash + Decimal("0.00000001"):
        raise ValueError("evaluation purchase exceeds available sleeve cash")
    cost = notional * rate
    sleeve.cash -= notional
    sleeve.positions[symbol] = sleeve.positions.get(symbol, ZERO) + (notional - cost) / price


def _value(sleeve: EvaluationSleeve, prices: dict[str, Decimal]) -> Decimal:
    return sleeve.cash + sum(
        (quantity * prices[symbol] for symbol, quantity in sleeve.positions.items()),
        ZERO,
    )


def _period_returns(observations: list[EvaluationObservation], sleeve: str) -> list[float]:
    values: list[float] = []
    prior_post: Decimal | None = None
    for observation in observations:
        pre = observation.pre_contribution_values[sleeve]
        if prior_post is not None and prior_post > ZERO:
            values.append(float(pre / prior_post - ONE))
        prior_post = observation.post_trade_values[sleeve]
    return values


def _sleeve_metrics(
    observations: list[EvaluationObservation],
    sleeve: str,
    state: EvaluationSleeve,
    returns: list[float],
) -> dict:
    value = float(observations[-1].post_trade_values[sleeve])
    contributions = float(state.total_contributions)
    return_on_contributions = value / contributions - 1 if contributions > 0 else 0.0
    unit = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for period_return in returns:
        unit *= 1 + period_return
        peak = max(peak, unit)
        max_drawdown = min(max_drawdown, unit / peak - 1)
    return {
        "value": value,
        "cash": float(state.cash),
        "total_contributions": contributions,
        "total_costs": float(state.total_costs),
        "return_on_contributions": return_on_contributions,
        "time_weighted_return": unit - 1,
        "annualized_volatility": stdev(returns) * sqrt(252) if len(returns) >= 2 else None,
        "max_drawdown": max_drawdown,
    }
