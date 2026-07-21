from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from edgecraft.execution_models import (
    MarketQuote,
    PortfolioSnapshot,
    ProposedOrder,
    ResearchEvidence,
    RiskDecision,
    RiskPolicy,
)


def evaluate_orders(
    snapshot: PortfolioSnapshot,
    quotes: list[MarketQuote],
    orders: list[ProposedOrder],
    policy: RiskPolicy,
    *,
    strategy: str,
    mode: str,
    daily_placed_notional: float = 0.0,
    daily_placed_order_count: int = 0,
    rolling_7d_placed_notional: float = 0.0,
    portfolio_high_watermark: float | None = None,
    successful_shadow_cycles: int = 0,
    unresolved_order_keys: list[str] | None = None,
    research: ResearchEvidence | None = None,
    now: datetime | None = None,
) -> RiskDecision:
    gross_notional = sum(order.notional for order in orders)
    turnover = (rolling_7d_placed_notional + gross_notional) / max(snapshot.portfolio_value, 1.0)
    drawdown = _drawdown(snapshot, portfolio_high_watermark)
    current_time = _aware(now or datetime.now(UTC))
    violations = [
        *_account_violations(snapshot, policy, current_time, unresolved_order_keys),
        *_usage_violations(
            snapshot,
            orders,
            policy,
            mode=mode,
            daily_placed_notional=daily_placed_notional,
            daily_placed_order_count=daily_placed_order_count,
            gross_notional=gross_notional,
            turnover=turnover,
            drawdown=drawdown,
            successful_shadow_cycles=successful_shadow_cycles,
        ),
    ]
    order_evaluation = _evaluate_order_details(
        snapshot,
        quotes,
        orders,
        policy,
        mode=mode,
        current_time=current_time,
    )
    violations.extend(order_evaluation.violations)
    warnings = order_evaluation.warnings
    projected_weights, portfolio_violations = _portfolio_constraints(
        snapshot,
        policy,
        order_evaluation.projected_values,
        order_evaluation.projected_cash,
    )
    violations.extend(portfolio_violations)
    research_issues = _research_issues(research, policy, strategy, current_time)
    (violations if mode == "live" else warnings).extend(research_issues)

    return RiskDecision(
        approved_for_review=not violations,
        violations=sorted(set(violations)),
        warnings=sorted(set(warnings)),
        projected_cash=round(order_evaluation.projected_cash, 2),
        projected_weights=projected_weights,
        gross_notional=round(gross_notional, 2),
        spread_bps={
            symbol: round(value, 4) for symbol, value in sorted(order_evaluation.spreads.items())
        },
        rolling_7d_turnover=round(turnover, 8),
        drawdown_fraction=round(drawdown, 8) if drawdown is not None else None,
    )


@dataclass(slots=True)
class _QuoteEvaluation:
    violations: list[str]
    conditional_issues: list[str]
    spread_bps: float | None


@dataclass(slots=True)
class _OrderEvaluation:
    violations: list[str]
    warnings: list[str]
    projected_values: dict[str, float]
    projected_cash: float
    spreads: dict[str, float]


def _account_violations(
    snapshot: PortfolioSnapshot,
    policy: RiskPolicy,
    current_time: datetime,
    unresolved_order_keys: list[str] | None,
) -> list[str]:
    violations = []
    if not snapshot.agentic_allowed:
        violations.append("account is not marked agentic_allowed")
    if snapshot.account_restricted:
        violations.append("account is marked restricted")
    snapshot_age = (current_time - _aware(snapshot.as_of)).total_seconds()
    if snapshot_age < -60:
        violations.append("portfolio snapshot timestamp is in the future")
    elif snapshot_age > policy.max_snapshot_age_seconds:
        violations.append(
            f"portfolio snapshot is stale ({int(snapshot_age)}s > "
            f"{policy.max_snapshot_age_seconds}s)"
        )
    if snapshot.open_orders:
        violations.append(
            f"portfolio snapshot contains {len(snapshot.open_orders)} open broker order(s)"
        )
    if unresolved_order_keys:
        violations.append(
            f"audit ledger contains unresolved placed order(s): {', '.join(unresolved_order_keys)}"
        )
    return violations


def _usage_violations(
    snapshot: PortfolioSnapshot,
    orders: list[ProposedOrder],
    policy: RiskPolicy,
    *,
    mode: str,
    daily_placed_notional: float,
    daily_placed_order_count: int,
    gross_notional: float,
    turnover: float,
    drawdown: float | None,
    successful_shadow_cycles: int,
) -> list[str]:
    violations = []
    if mode == "live" and not policy.trading_enabled:
        violations.append("live trading is disabled by policy")
    if not policy.allowed_symbols:
        violations.append("policy has no allowed_symbols whitelist")
    if daily_placed_order_count + len(orders) > policy.max_orders_per_day:
        violations.append(
            f"orders plus today's {daily_placed_order_count} placed order(s) exceed "
            f"max_orders_per_day={policy.max_orders_per_day}"
        )
    if daily_placed_notional + gross_notional > policy.max_daily_notional + 1e-9:
        violations.append(
            "orders plus today's placed notional exceed max_daily_notional="
            f"{policy.max_daily_notional:.2f}"
        )
    if not orders:
        violations.append("proposal contains no economically material orders")
    if turnover > policy.max_rolling_7d_turnover + 1e-9:
        violations.append(
            f"projected rolling 7d turnover {turnover:.1%} exceeds "
            f"max_rolling_7d_turnover={policy.max_rolling_7d_turnover:.1%}"
        )
    if drawdown is not None and drawdown > policy.max_drawdown_fraction + 1e-9:
        violations.append(
            f"portfolio drawdown {drawdown:.1%} exceeds "
            f"max_drawdown_fraction={policy.max_drawdown_fraction:.1%}"
        )
    if mode == "live" and successful_shadow_cycles < policy.min_shadow_cycles_before_live:
        violations.append(
            f"only {successful_shadow_cycles} successful shadow cycle(s); policy requires "
            f"{policy.min_shadow_cycles_before_live} before live trading"
        )
    return violations


def _evaluate_order_details(
    snapshot: PortfolioSnapshot,
    quotes: list[MarketQuote],
    orders: list[ProposedOrder],
    policy: RiskPolicy,
    *,
    mode: str,
    current_time: datetime,
) -> _OrderEvaluation:
    quote_map = {quote.symbol: quote for quote in quotes}
    projected_values = {position.symbol: position.market_value for position in snapshot.positions}
    projected_cash = snapshot.buying_power
    violations: list[str] = []
    warnings: list[str] = []
    spreads: dict[str, float] = {}
    for order in orders:
        violations.extend(_basic_order_violations(order, policy))
        quote = quote_map.get(order.symbol)
        if quote is None:
            violations.append(f"missing quote for {order.symbol}")
            continue
        quote_evaluation = _evaluate_quote(order, quote, policy, current_time)
        violations.extend(quote_evaluation.violations)
        (violations if mode == "live" else warnings).extend(quote_evaluation.conditional_issues)
        if quote_evaluation.spread_bps is not None:
            spreads[order.symbol] = quote_evaluation.spread_bps
        direction = 1 if order.side == "buy" else -1
        projected_values[order.symbol] = projected_values.get(order.symbol, 0.0) + (
            direction * order.notional
        )
        projected_cash -= direction * order.notional
        if projected_values[order.symbol] < -0.01:
            violations.append(f"{order.symbol} sell exceeds the current position")
    return _OrderEvaluation(violations, warnings, projected_values, projected_cash, spreads)


def _basic_order_violations(order: ProposedOrder, policy: RiskPolicy) -> list[str]:
    violations = []
    if order.symbol not in set(policy.allowed_symbols):
        violations.append(f"{order.symbol} is not in allowed_symbols")
    if order.notional > policy.max_order_notional + 1e-9:
        violations.append(
            f"{order.symbol} order {order.notional:.2f} exceeds max_order_notional="
            f"{policy.max_order_notional:.2f}"
        )
    if order.notional < policy.min_order_notional:
        violations.append(f"{order.symbol} order is below min_order_notional")
    if order.side == "sell" and not policy.allow_sells:
        violations.append(f"selling {order.symbol} is disabled by policy")
    return violations


def _evaluate_quote(
    order: ProposedOrder,
    quote: MarketQuote,
    policy: RiskPolicy,
    current_time: datetime,
) -> _QuoteEvaluation:
    violations = []
    conditional_issues = []
    if not quote.tradable:
        violations.append(f"{order.symbol} is not currently tradable")
    if quote.market_session not in policy.allowed_market_sessions:
        conditional_issues.append(
            f"{order.symbol} market session {quote.market_session} is not allowed"
        )
    spread_bps = _spread_bps(quote)
    if spread_bps is None:
        conditional_issues.append(f"{order.symbol} quote is missing bid/ask liquidity data")
    elif spread_bps > policy.max_spread_bps + 1e-9:
        conditional_issues.append(
            f"{order.symbol} spread {spread_bps:.1f} bps exceeds "
            f"max_spread_bps={policy.max_spread_bps:.1f}"
        )
    if quote.average_daily_dollar_volume is None:
        conditional_issues.append(f"{order.symbol} quote is missing average daily dollar volume")
    elif order.notional > float(quote.average_daily_dollar_volume) * policy.max_order_adv_fraction:
        conditional_issues.append(
            f"{order.symbol} order exceeds max_order_adv_fraction="
            f"{policy.max_order_adv_fraction:.4f}"
        )
    violations.extend(_quote_integrity_violations(order, quote, policy, current_time))
    return _QuoteEvaluation(violations, conditional_issues, spread_bps)


def _quote_integrity_violations(
    order: ProposedOrder,
    quote: MarketQuote,
    policy: RiskPolicy,
    current_time: datetime,
) -> list[str]:
    violations = []
    age = (current_time - _aware(quote.as_of)).total_seconds()
    if age < -60:
        violations.append(f"{order.symbol} quote timestamp is in the future")
    elif age > policy.max_quote_age_seconds:
        violations.append(
            f"{order.symbol} quote is stale ({int(age)}s > {policy.max_quote_age_seconds}s)"
        )
    deviation = abs(order.expected_price / quote.last - 1) * 10_000
    if deviation > policy.max_price_deviation_bps:
        violations.append(
            f"{order.symbol} expected price deviates {deviation:.1f} bps from latest quote"
        )
    approximate_quantity = order.notional / quote.last
    if (
        not quote.fractionally_tradable
        and abs(approximate_quantity - round(approximate_quantity)) > 1e-6
    ):
        violations.append(f"{order.symbol} does not support the proposed fractional order")
    return violations


def _portfolio_constraints(
    snapshot: PortfolioSnapshot,
    policy: RiskPolicy,
    projected_values: dict[str, float],
    projected_cash: float,
) -> tuple[dict[str, float], list[str]]:
    violations = []
    projected_invested = sum(max(0.0, value) for value in projected_values.values())
    if projected_invested > policy.managed_capital_limit + 1e-9:
        violations.append(
            f"projected invested value {projected_invested:.2f} exceeds managed_capital_limit="
            f"{policy.managed_capital_limit:.2f}"
        )
    if projected_cash < policy.min_cash_reserve - 1e-9:
        violations.append(
            f"projected buying power {projected_cash:.2f} is below min_cash_reserve="
            f"{policy.min_cash_reserve:.2f}"
        )
    denominator = max(snapshot.portfolio_value, projected_cash + projected_invested)
    weights = {
        symbol: max(0.0, value) / denominator
        for symbol, value in sorted(projected_values.items())
        if value > 0.01
    }
    violations.extend(_concentration_violations(weights, policy))
    return weights, violations


def _concentration_violations(projected_weights: dict[str, float], policy: RiskPolicy) -> list[str]:
    violations = []
    for symbol, weight in projected_weights.items():
        if weight > policy.max_position_weight + 1e-9:
            violations.append(
                f"{symbol} projected weight {weight:.1%} exceeds max_position_weight="
                f"{policy.max_position_weight:.1%}"
            )
    for group_name, symbols in policy.symbol_groups.items():
        group_weight = sum(projected_weights.get(symbol, 0.0) for symbol in symbols)
        if group_weight > policy.max_group_weight + 1e-9:
            violations.append(
                f"{group_name} projected weight {group_weight:.1%} exceeds "
                f"max_group_weight={policy.max_group_weight:.1%}"
            )
    return violations


def _research_issues(
    research: ResearchEvidence | None,
    policy: RiskPolicy,
    strategy: str,
    current_time: datetime,
) -> list[str]:
    if not policy.require_research_evidence:
        return []
    if research is None:
        return ["research evidence is required before live review"]
    issues = []
    if research.strategy != strategy:
        issues.append(
            f"research strategy {research.strategy} does not match proposal strategy {strategy}"
        )
    research_age = (current_time - _aware(research.data_end)).days
    if research_age < -1:
        issues.append("research data_end is in the future")
    elif research_age > policy.max_research_age_days:
        issues.append(f"research is stale ({research_age}d > {policy.max_research_age_days}d)")
    if not (
        research.walk_forward_passed
        and research.benchmark_beaten
        and research.cost_stress_passed
        and research.multiple_testing_passed
    ):
        issues.append("research evidence has not passed every promotion gate")
    return issues


def _drawdown(snapshot: PortfolioSnapshot, high_watermark: float | None) -> float | None:
    if high_watermark is None or high_watermark <= 0:
        return None
    return max(0.0, 1 - snapshot.portfolio_value / high_watermark)


def _spread_bps(quote: MarketQuote) -> float | None:
    if quote.bid is None or quote.ask is None:
        return None
    midpoint = (quote.bid + quote.ask) / 2
    return (quote.ask - quote.bid) / midpoint * 10_000


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
