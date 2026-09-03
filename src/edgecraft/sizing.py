"""Deterministic belief-to-quantity sizing for the paper fund."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

from edgecraft.monitor import stock_market_is_open
from edgecraft.paper_fund import (
    AssetClass,
    FundDecision,
    FundMandate,
    FundOrder,
    FundQuote,
    FundState,
    OrderSide,
    PaperFundValidationError,
)

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")


@dataclass(frozen=True)
class SizingConfig:
    fractional_kelly: Decimal = Decimal("0.25")
    minimum_edge_bps: Decimal = Decimal("2")
    maximum_driver_weight: Decimal = Decimal("0.40")
    maximum_prediction_weight: Decimal = Decimal("0.10")
    calibration_minimum_count: int = 5


@dataclass(frozen=True)
class SizingResult:
    decision: FundDecision
    accepted: tuple[dict[str, Any], ...]
    dropped: tuple[dict[str, Any], ...]


def calibration_haircut(
    p_win: Decimal,
    calibration: Sequence[dict[str, Any]],
    *,
    minimum_count: int = 5,
) -> Decimal:
    lower = min(9, max(0, int(p_win * 10))) * 10
    bucket = f"{lower:02d}-{lower + 10:02d}%"
    for row in calibration:
        if row.get("bucket") == bucket and int(row.get("count", 0)) >= minimum_count:
            return min(p_win, Decimal(str(row["realized_win_rate"])))
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


def size_decision(
    *,
    decision: FundDecision,
    quotes: Sequence[FundQuote],
    state: FundState,
    mandate: FundMandate,
    calibration: Sequence[dict[str, Any]] = (),
    sleeve_weights: dict[str, Decimal] | None = None,
    config: SizingConfig | None = None,
) -> SizingResult:
    """Replace missing entry quantities with fractional-Kelly quantities.

    Explicit quantities on exits are preserved. Entry quantities are ignored
    whenever the packet supplies a complete belief, making sizing repeatable.
    """
    config = config or SizingConfig()
    quote_by_id = {quote.instrument_id: quote for quote in quotes}
    hypotheses = {
        item.instrument_id: item
        for item in (decision.journal.hypotheses if decision.journal is not None else ())
    }
    sleeve_weights = sleeve_weights or {}
    driver_used: dict[str, Decimal] = {}
    accepted: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    orders: list[FundOrder] = []

    for order in decision.orders:
        if order.asset_class is AssetClass.STOCK and not stock_market_is_open(decision.as_of):
            dropped.append({"instrument_id": order.instrument_id, "reason": "market_closed_queued"})
            continue
        position = next(
            (item for item in state.positions if item.instrument_id == order.instrument_id), None
        )
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
        calibrated = calibration_haircut(
            p_win, calibration, minimum_count=config.calibration_minimum_count
        )
        trading_cost = (mandate.fee_bps + mandate.slippage_bps * Decimal("2")) / BPS
        minimum_edge = config.minimum_edge_bps / BPS
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
        weight = full_kelly * config.fractional_kelly
        playbook_id = order.playbook_id or (hypothesis.playbook_id if hypothesis else None)
        if playbook_id in sleeve_weights:
            weight = min(weight, sleeve_weights[playbook_id])
        weight = min(weight, mandate.max_single_position_weight)
        if order.asset_class is AssetClass.PREDICTION:
            weight = min(weight, config.maximum_prediction_weight)
        driver = order.driver or (hypothesis.driver if hypothesis else None) or "untagged"
        remaining_driver = max(
            ZERO,
            state.nav * config.maximum_driver_weight - driver_used.get(driver, ZERO),
        )
        notional = min(state.nav * weight, remaining_driver)
        quantity = _round_quantity(notional / quote.price, order.asset_class)
        if quantity <= ZERO:
            dropped.append(
                {"instrument_id": order.instrument_id, "reason": "quantity_rounded_to_zero"}
            )
            continue
        actual_notional = quantity * quote.price
        driver_used[driver] = driver_used.get(driver, ZERO) + actual_notional
        orders.append(
            order.model_copy(
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
        )
        accepted.append(
            {
                "instrument_id": order.instrument_id,
                "quantity": str(quantity),
                "p_win": str(p_win),
                "calibrated_p_win": str(calibrated),
                "expected_return": str(expected_return),
                "kelly_weight": str(weight),
                "notional": str(actual_notional),
                "driver": driver,
                "playbook_id": playbook_id or "unassigned",
            }
        )

    action = decision.action if orders else decision.action.__class__.HOLD
    sized = decision.model_copy(update={"orders": tuple(orders), "action": action})
    return SizingResult(decision=sized, accepted=tuple(accepted), dropped=tuple(dropped))
