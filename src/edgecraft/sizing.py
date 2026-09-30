"""Deterministic belief-to-quantity sizing for the paper fund."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

from edgecraft.monitor import stock_market_is_open
from edgecraft.paper_fund import (
    AssetClass,
    DecisionAction,
    FundDecision,
    FundMandate,
    FundOrder,
    FundQuote,
    FundState,
    HypothesisStance,
    OrderSide,
    PaperFundCapacityError,
    PaperFundValidationError,
    run_cycle_accounting,
)
from edgecraft.policy import TradingPolicy

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")
MINIMUM_EDGE_BPS = Decimal("2")
CALIBRATION_MINIMUM_COUNT = 5


@dataclass(frozen=True)
class SizingResult:
    decision: FundDecision
    accepted: tuple[dict[str, Any], ...]
    dropped: tuple[dict[str, Any], ...]


def _candidate_orders(
    decision: FundDecision,
    quotes: Sequence[FundQuote],
    state: FundState,
) -> tuple[FundOrder, ...]:
    """Turn complete directional research into deterministic candidate orders.

    Scheduled research supplies beliefs; Python owns whether those beliefs
    become trades. Explicit orders remain supported for compatibility and
    inventory exits, while omitted entry orders are derived from hypotheses.
    """
    orders = list(decision.orders)
    explicit = {order.instrument_id for order in orders}
    quote_by_id = {quote.instrument_id: quote for quote in quotes}
    position_by_id = {position.instrument_id: position for position in state.positions}

    for hypothesis in decision.journal.hypotheses if decision.journal else ():
        if hypothesis.instrument_id in explicit:
            continue
        position = position_by_id.get(hypothesis.instrument_id)
        if hypothesis.stance is HypothesisStance.FLAT:
            continue
        if hypothesis.stance is HypothesisStance.EXIT:
            if position is None:
                continue
            side = OrderSide.SELL if position.quantity > ZERO else OrderSide.COVER
            orders.append(
                FundOrder(
                    instrument_id=hypothesis.instrument_id,
                    asset_class=position.asset_class,
                    side=side,
                    quantity=abs(position.quantity),
                    rationale=hypothesis.statement,
                    evidence_ids=hypothesis.evidence_ids,
                )
            )
            continue
        if position is not None:
            same_direction = (position.quantity > ZERO) == (
                hypothesis.stance is HypothesisStance.LONG
            )
            if same_direction:
                continue
            orders.append(
                FundOrder(
                    instrument_id=hypothesis.instrument_id,
                    asset_class=position.asset_class,
                    side=OrderSide.SELL if position.quantity > ZERO else OrderSide.COVER,
                    quantity=abs(position.quantity),
                    rationale=hypothesis.statement,
                    evidence_ids=hypothesis.evidence_ids,
                )
            )
        quote = quote_by_id.get(hypothesis.instrument_id)
        if quote is None:
            raise PaperFundValidationError(
                f"directional candidate requires a quote: {hypothesis.instrument_id}"
            )
        side = OrderSide.BUY if hypothesis.stance is HypothesisStance.LONG else OrderSide.SHORT
        orders.append(
            FundOrder(
                instrument_id=hypothesis.instrument_id,
                asset_class=quote.asset_class,
                side=side,
                quantity=None,
                p_win=hypothesis.p_win or hypothesis.confidence,
                target_price=hypothesis.target_price,
                invalidation_price=hypothesis.invalidation_price,
                horizon_hours=hypothesis.expected_horizon_hours,
                playbook_id=hypothesis.playbook_id,
                driver=hypothesis.driver,
                rationale=hypothesis.statement,
                evidence_ids=hypothesis.evidence_ids,
            )
        )
    # Exit first; short proceeds can then fund independent longs.
    priority = {OrderSide.SELL: 0, OrderSide.COVER: 0, OrderSide.SHORT: 1, OrderSide.BUY: 2}
    return tuple(sorted(orders, key=lambda order: priority[order.side]))


def calibration_haircut(
    p_win: Decimal,
    calibration: Sequence[dict[str, Any]],
    *,
    minimum_count: int = 5,
    prior_count: int = 20,
) -> Decimal:
    lower = min(9, max(0, int(p_win * 10))) * 10
    bucket = f"{lower:02d}-{lower + 10:02d}%"
    for row in calibration:
        if row.get("bucket") == bucket and int(row.get("count", 0)) >= minimum_count:
            count = Decimal(int(row["count"]))
            measured = Decimal(str(row["realized_win_rate"]))
            # Small forward samples adjust confidence gradually. They cannot
            # turn a new version's probability into a permanent zero.
            adjusted = (p_win * prior_count + measured * count) / (prior_count + count)
            return min(p_win, adjusted)
    return p_win


def _belief(order: FundOrder, hypothesis: Any | None) -> tuple[Decimal, Decimal, Decimal]:
    p_win = order.p_win
    target = order.target_price
    stop = order.invalidation_price
    if hypothesis is not None:
        p_win = p_win if p_win is not None else (hypothesis.p_win or hypothesis.confidence)
        target = target if target is not None else hypothesis.target_price
        stop = stop if stop is not None else hypothesis.invalidation_price
    if p_win is None or target is None or stop is None:
        raise PaperFundValidationError(
            f"sized order {order.instrument_id} requires p_win, target, and invalidation"
        )
    return p_win, target, stop


def _payoffs(
    side: OrderSide, price: Decimal, target: Decimal, stop: Decimal
) -> tuple[Decimal, Decimal]:
    if side is OrderSide.BUY:
        upside = (target - price) / price
        downside = (price - stop) / price
    elif side is OrderSide.SHORT:
        upside = (price - target) / price
        downside = (stop - price) / price
    else:
        return ZERO, ZERO
    if upside <= ZERO or downside <= ZERO:
        raise PaperFundValidationError("target and invalidation must bracket the current price")
    return upside, downside


def _round_quantity(quantity: Decimal, asset_class: AssetClass) -> Decimal:
    quantum = {
        AssetClass.STOCK: Decimal("0.0001"),
        AssetClass.CRYPTO: Decimal("0.00000001"),
        AssetClass.PREDICTION: Decimal("1"),
    }[asset_class]
    return quantity.quantize(quantum, rounding=ROUND_DOWN)


def _fit_entry(
    order: FundOrder,
    prior_orders: Sequence[FundOrder],
    *,
    decision: FundDecision,
    quotes: Sequence[FundQuote],
    state: FundState,
    mandate: FundMandate,
) -> tuple[FundOrder | None, str | None]:
    """Find the largest quantity that fits; preview only, never write a ledger.

    Use the real fill/cost/risk math rather than maintaining a second budget
    engine. Search integer quantity units so the result is deterministic.
    """
    reason = None

    def fits(quantity: Decimal) -> bool:
        nonlocal reason
        trial = decision.model_copy(
            update={
                "action": DecisionAction.TRADE,
                "orders": (*prior_orders, order.model_copy(update={"quantity": quantity})),
            }
        )
        try:
            run_cycle_accounting(mandate=mandate, prior_state=state, decision=trial, quotes=quotes)
        except PaperFundValidationError as exc:
            if not isinstance(exc, PaperFundCapacityError) and not exc.audit.get("risk"):
                raise
            reason = str(exc)
            return False
        return True

    if fits(order.quantity):
        return order, None
    quantum = _round_quantity(ONE, order.asset_class).as_tuple().exponent
    unit = ONE.scaleb(quantum)
    low, high = 0, int(order.quantity / unit)
    while low < high:
        middle = (low + high + 1) // 2
        if fits(Decimal(middle) * unit):
            low = middle
        else:
            high = middle - 1
    if low == 0:
        return None, reason
    return order.model_copy(update={"quantity": Decimal(low) * unit}), reason


def size_decision(
    *,
    decision: FundDecision,
    quotes: Sequence[FundQuote],
    state: FundState,
    mandate: FundMandate,
    calibration: Sequence[dict[str, Any]] = (),
    sleeve_weights: dict[str, Decimal] | None = None,
    policy: TradingPolicy | None = None,
) -> SizingResult:
    """Replace missing entry quantities with fractional-Kelly quantities.

    Explicit quantities on exits are preserved. Entry quantities are ignored
    whenever the packet supplies a complete belief, making sizing repeatable.
    """
    policy = policy or TradingPolicy()
    decision = decision.model_copy(update={"orders": _candidate_orders(decision, quotes, state)})
    quote_by_id = {quote.instrument_id: quote for quote in quotes}
    position_by_id = {position.instrument_id: position for position in state.positions}
    hypotheses = {
        item.instrument_id: item
        for item in (decision.journal.hypotheses if decision.journal is not None else ())
    }
    enforce_sleeves = sleeve_weights is not None
    sleeve_weights = sleeve_weights or {}
    driver_used: dict[str, Decimal] = {}
    sleeve_used: dict[str, Decimal] = {}
    instrument_used: dict[str, Decimal] = {}
    # Fees on later entries reduce NAV too. Leave room for a full cycle's
    # modeled costs so an early position at its cap cannot block the rest.
    turnover_limit = mandate.effective_limit(
        mandate.max_cycle_turnover, mandate.max_cycle_turnover_nav_multiple, state.nav
    )
    nav_after_cost_budget = max(
        ZERO, state.nav - turnover_limit * (mandate.fee_bps + mandate.slippage_bps) / BPS
    )
    # Release only inventory actually scheduled to exit in this cycle. The
    # accounting preview verifies those exits before sizing replacement risk.
    exit_quantities: dict[str, Decimal] = {}
    for order in decision.orders:
        if order.side in {OrderSide.SELL, OrderSide.COVER}:
            if order.asset_class is AssetClass.STOCK and not stock_market_is_open(decision.as_of):
                continue
            position = position_by_id.get(order.instrument_id)
            quantity = order.quantity or (abs(position.quantity) if position else ZERO)
            exit_quantities[order.instrument_id] = (
                exit_quantities.get(order.instrument_id, ZERO) + quantity
            )
    for position in state.positions:
        mark = quote_by_id.get(position.instrument_id)
        price = mark.price if mark else (position.mark_price or position.average_entry)
        remaining_quantity = max(
            ZERO, abs(position.quantity) - exit_quantities.get(position.instrument_id, ZERO)
        )
        exposure = remaining_quantity * price
        driver = position.driver or "untagged"
        sleeve = position.playbook_id or "unassigned"
        driver_used[driver] = driver_used.get(driver, ZERO) + exposure
        sleeve_used[sleeve] = sleeve_used.get(sleeve, ZERO) + exposure
        instrument_used[position.instrument_id] = exposure
    accepted: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    orders: list[FundOrder] = []

    for order in decision.orders:
        if order.asset_class is AssetClass.STOCK and not stock_market_is_open(decision.as_of):
            dropped.append({"instrument_id": order.instrument_id, "reason": "market_closed_queued"})
            continue
        position = position_by_id.get(order.instrument_id)
        is_exit = order.side in {OrderSide.SELL, OrderSide.COVER}
        hypothesis = hypotheses.get(order.instrument_id)
        if is_exit:
            quantity = order.quantity or (abs(position.quantity) if position else None)
            if quantity is None:
                raise PaperFundValidationError(
                    f"cannot size exit without inventory: {order.instrument_id}"
                )
            orders.append(order.model_copy(update={"quantity": quantity}))
            accepted.append({"instrument_id": order.instrument_id, "reason": "inventory_exit"})
            continue

        quote = quote_by_id.get(order.instrument_id)
        if quote is None:
            raise PaperFundValidationError(f"missing quote for sized order {order.instrument_id}")
        p_win, target, stop = _belief(order, hypothesis)
        playbook_id = order.playbook_id or (hypothesis.playbook_id if hypothesis else None)
        calibrated = calibration_haircut(
            p_win,
            [row for row in calibration if row.get("playbook_id", playbook_id) == playbook_id],
            minimum_count=CALIBRATION_MINIMUM_COUNT,
            prior_count=policy.learning_window,
        )
        trading_cost = (mandate.fee_bps + mandate.slippage_bps) * Decimal("2") / BPS
        minimum_edge = MINIMUM_EDGE_BPS / BPS
        if order.asset_class is AssetClass.PREDICTION:
            if order.side is OrderSide.BUY:
                edge = calibrated - quote.price
                denom = ONE - quote.price
            else:
                edge = quote.price - calibrated
                denom = quote.price
            expected_return = edge - trading_cost
            if denom <= ZERO or expected_return < minimum_edge:
                dropped.append(
                    {
                        "instrument_id": order.instrument_id,
                        "reason": "below_edge_threshold",
                        "expected_return": str(expected_return),
                        "minimum": str(minimum_edge),
                    }
                )
                continue
            full_kelly = max(ZERO, edge / denom)
        else:
            upside, downside = _payoffs(order.side, quote.price, target, stop)
            expected_return = calibrated * upside - (ONE - calibrated) * downside - trading_cost
            if expected_return < minimum_edge:
                dropped.append(
                    {
                        "instrument_id": order.instrument_id,
                        "reason": "below_edge_threshold",
                        "expected_return": str(expected_return),
                        "minimum": str(minimum_edge),
                    }
                )
                continue
            payoff_ratio = upside / downside
            full_kelly = max(ZERO, (payoff_ratio * calibrated - (ONE - calibrated)) / payoff_ratio)
        weight = full_kelly * policy.kelly_fraction
        driver = order.driver or (hypothesis.driver if hypothesis else None) or "untagged"
        if (
            position
            and exit_quantities.get(order.instrument_id, ZERO) < abs(position.quantity)
            and (playbook_id != position.playbook_id or driver != (position.driver or "untagged"))
        ):
            dropped.append(
                {"instrument_id": order.instrument_id, "reason": "existing_position_attribution"}
            )
            continue
        if enforce_sleeves and playbook_id not in sleeve_weights:
            dropped.append({"instrument_id": order.instrument_id, "reason": "unknown_playbook"})
            continue
        if playbook_id in sleeve_weights:
            weight = min(weight, sleeve_weights[playbook_id])
        remaining_driver = max(
            ZERO,
            state.nav * policy.max_driver_weight - driver_used.get(driver, ZERO),
        )
        position_limit = mandate.max_single_position_weight
        if order.asset_class is AssetClass.PREDICTION:
            position_limit = min(position_limit, policy.max_prediction_weight)
        weight = min(weight, position_limit)
        remaining_position = max(
            ZERO,
            nav_after_cost_budget * position_limit - instrument_used.get(order.instrument_id, ZERO),
        )
        remaining_sleeve = (
            max(ZERO, state.nav * sleeve_weights[playbook_id] - sleeve_used.get(playbook_id, ZERO))
            if enforce_sleeves
            else state.nav
        )
        notional = min(state.nav * weight, remaining_driver, remaining_sleeve, remaining_position)
        quantity = _round_quantity(notional / quote.price, order.asset_class)
        if quantity <= ZERO:
            dropped.append(
                {"instrument_id": order.instrument_id, "reason": "quantity_rounded_to_zero"}
            )
            continue
        sized_order = order.model_copy(
            update={
                "quantity": quantity,
                "p_win": p_win,
                "target_price": target,
                "invalidation_price": stop,
                "playbook_id": playbook_id,
                "driver": driver,
                "borrow_fee_bps_annual": (
                    Decimal("300")
                    if order.asset_class is AssetClass.STOCK and order.side is OrderSide.SHORT
                    else order.borrow_fee_bps_annual
                ),
            }
        )
        sized_order, capacity_reason = _fit_entry(
            sized_order, orders, decision=decision, quotes=quotes, state=state, mandate=mandate
        )
        if sized_order is None:
            dropped.append(
                {
                    "instrument_id": order.instrument_id,
                    "reason": "portfolio_capacity",
                    "detail": capacity_reason,
                }
            )
            continue
        preview = run_cycle_accounting(
            mandate=mandate,
            prior_state=state,
            decision=decision.model_copy(update={"orders": (*orders, sized_order)}),
            quotes=quotes,
        )
        execution_price = preview.fills[-1].execution_price
        # Entry slippage/spread is already in that price. Estimate the exit
        # slippage and both fees; displayed liquidity must not erase the edge.
        remaining_cost = (2 * mandate.fee_bps + mandate.slippage_bps) / BPS
        if order.asset_class is AssetClass.STOCK and order.side is OrderSide.SHORT:
            horizon = order.horizon_hours or (
                hypothesis.expected_horizon_hours if hypothesis else 72
            )
            remaining_cost += Decimal("300") / BPS * Decimal(horizon) / Decimal("8760")
        if order.asset_class is AssetClass.PREDICTION:
            executable_return = (
                calibrated - execution_price
                if order.side is OrderSide.BUY
                else execution_price - calibrated
            ) - remaining_cost
        else:
            if not min(target, stop) < execution_price < max(target, stop):
                dropped.append(
                    {"instrument_id": order.instrument_id, "reason": "execution_outside_thesis"}
                )
                continue
            upside, downside = _payoffs(order.side, execution_price, target, stop)
            executable_return = calibrated * upside - (ONE - calibrated) * downside - remaining_cost
        if executable_return < minimum_edge:
            dropped.append(
                {
                    "instrument_id": order.instrument_id,
                    "reason": "execution_erases_edge",
                    "expected_return": str(executable_return),
                    "execution_price": str(execution_price),
                }
            )
            continue
        quantity = sized_order.quantity
        actual_notional = quantity * quote.price
        driver_used[driver] = driver_used.get(driver, ZERO) + actual_notional
        sleeve = playbook_id or "unassigned"
        sleeve_used[sleeve] = sleeve_used.get(sleeve, ZERO) + actual_notional
        instrument_used[order.instrument_id] = (
            instrument_used.get(order.instrument_id, ZERO) + actual_notional
        )
        orders.append(sized_order)
        accepted.append(
            {
                "instrument_id": order.instrument_id,
                "quantity": str(quantity),
                "p_win": str(p_win),
                "calibrated_p_win": str(calibrated),
                "expected_return": str(expected_return),
                "executable_expected_return": str(executable_return),
                "kelly_weight": str(weight),
                "notional": str(actual_notional),
                "capacity_adjustment": capacity_reason,
                "driver": driver,
                "playbook_id": playbook_id or "unassigned",
            }
        )

    action = DecisionAction.TRADE if orders else DecisionAction.HOLD
    sized = decision.model_copy(update={"orders": tuple(orders), "action": action})
    return SizingResult(decision=sized, accepted=tuple(accepted), dropped=tuple(dropped))
