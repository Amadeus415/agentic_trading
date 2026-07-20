from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from edgecraft.execution_models import (
    MarketQuote,
    PortfolioSnapshot,
    ProposedOrder,
    ResearchEvidence,
    RiskDecision,
    RiskPolicy,
    TargetAllocation,
)


def build_rebalance_orders(
    snapshot: PortfolioSnapshot,
    quotes: list[MarketQuote],
    targets: TargetAllocation,
    policy: RiskPolicy,
) -> list[ProposedOrder]:
    quote_map = {quote.symbol: quote for quote in quotes}
    position_values = {position.symbol: position.market_value for position in snapshot.positions}
    symbols = sorted(set(position_values) | set(targets.weights))
    orders: list[ProposedOrder] = []
    for symbol in symbols:
        quote = quote_map.get(symbol)
        if quote is None:
            raise ValueError(f"Missing quote for {symbol}")
        target_value = snapshot.portfolio_value * targets.weights.get(symbol, 0.0)
        delta = target_value - position_values.get(symbol, 0.0)
        if abs(delta) < policy.min_order_notional:
            continue
        side = "buy" if delta > 0 else "sell"
        notional = round(abs(delta), 2)
        identity = (
            f"{snapshot.account_id}:{snapshot.as_of.isoformat()}:{symbol}:{side}:{notional:.2f}"
        )
        order_key = hashlib.sha256(identity.encode()).hexdigest()[:20]
        orders.append(
            ProposedOrder(
                order_key=order_key,
                symbol=symbol,
                side=side,
                notional=notional,
                expected_price=quote.last,
                rationale=targets.rationale,
                quote_as_of=quote.as_of,
            )
        )
    return orders


def evaluate_orders(
    snapshot: PortfolioSnapshot,
    quotes: list[MarketQuote],
    orders: list[ProposedOrder],
    policy: RiskPolicy,
    *,
    strategy: str,
    mode: str,
    daily_placed_notional: float = 0.0,
    unresolved_order_keys: list[str] | None = None,
    research: ResearchEvidence | None = None,
    now: datetime | None = None,
) -> RiskDecision:
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    quote_map = {quote.symbol: quote for quote in quotes}
    violations: list[str] = []
    warnings: list[str] = []

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
    if mode == "live" and not policy.trading_enabled:
        violations.append("live trading is disabled by policy")
    if not policy.allowed_symbols:
        violations.append("policy has no allowed_symbols whitelist")
    if len(orders) > policy.max_orders_per_day:
        violations.append(
            f"{len(orders)} orders exceeds max_orders_per_day={policy.max_orders_per_day}"
        )
    gross_notional = sum(order.notional for order in orders)
    if daily_placed_notional + gross_notional > policy.max_daily_notional + 1e-9:
        violations.append(
            "orders plus today's placed notional exceed max_daily_notional="
            f"{policy.max_daily_notional:.2f}"
        )
    if not orders:
        violations.append("proposal contains no economically material orders")

    current_values = {position.symbol: position.market_value for position in snapshot.positions}
    projected_values = dict(current_values)
    projected_cash = snapshot.buying_power
    allowed = set(policy.allowed_symbols)
    for order in orders:
        quote = quote_map.get(order.symbol)
        if order.symbol not in allowed:
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
        if quote is None:
            violations.append(f"missing quote for {order.symbol}")
            continue
        if not quote.tradable:
            violations.append(f"{order.symbol} is not currently tradable")
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
        if not quote.fractionally_tradable:
            approximate_quantity = order.notional / quote.last
            if abs(approximate_quantity - round(approximate_quantity)) > 1e-6:
                violations.append(f"{order.symbol} does not support the proposed fractional order")
        direction = 1 if order.side == "buy" else -1
        projected_values[order.symbol] = projected_values.get(order.symbol, 0.0) + (
            direction * order.notional
        )
        projected_cash -= direction * order.notional
        if projected_values[order.symbol] < -0.01:
            violations.append(f"{order.symbol} sell exceeds the current position")

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
    projected_weights = {
        symbol: max(0.0, value) / denominator
        for symbol, value in sorted(projected_values.items())
        if value > 0.01
    }
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

    if policy.require_research_evidence:
        if research is None:
            message = "research evidence is required before live review"
            (violations if mode == "live" else warnings).append(message)
        else:
            research_issues: list[str] = []
            if research.strategy != strategy:
                research_issues.append(
                    f"research strategy {research.strategy} does not match proposal strategy {strategy}"
                )
            research_age = (current_time - _aware(research.data_end)).days
            if research_age < -1:
                research_issues.append("research data_end is in the future")
            elif research_age > policy.max_research_age_days:
                research_issues.append(
                    f"research is stale ({research_age}d > {policy.max_research_age_days}d)"
                )
            if not (
                research.walk_forward_passed
                and research.benchmark_beaten
                and research.cost_stress_passed
                and research.multiple_testing_passed
            ):
                research_issues.append("research evidence has not passed every promotion gate")
            for message in research_issues:
                (violations if mode == "live" else warnings).append(message)

    return RiskDecision(
        approved_for_review=not violations,
        violations=sorted(set(violations)),
        warnings=sorted(set(warnings)),
        projected_cash=round(projected_cash, 2),
        projected_weights=projected_weights,
        gross_notional=round(gross_notional, 2),
    )


def proposal_id(
    snapshot: PortfolioSnapshot,
    strategy: str,
    mode: str,
    orders: list[ProposedOrder],
    policy: RiskPolicy,
) -> str:
    payload = {
        "account_id": snapshot.account_id,
        "snapshot_as_of": snapshot.as_of.isoformat(),
        "strategy": strategy,
        "mode": mode,
        "policy": policy.policy_name,
        "orders": [
            {"key": order.order_key, "notional": order.notional, "price": order.expected_price}
            for order in orders
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "prop_" + hashlib.sha256(encoded).hexdigest()[:24]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
