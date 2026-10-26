"""Deterministic belief-to-quantity sizing for prediction contracts.

Three steps turn a researched belief into a quantity:

1. Facts and opinions: a belief at p_win >= 0.95 claims a public fact already
   decides the outcome. It needs a primary source beyond the venue, and its
   probability is capped by the playbook's settled fact accuracy. Any other
   belief is an opinion, shrunk toward the market by the playbook's proven trust
   (`edgecraft.forecasts`); unproven opinions are forecast, never traded.
2. Velocity: rank entries by after-cost return per day so scarce cash goes to
   the fastest-compounding edges first, and drop edges too slow to clear the
   annualized hurdle.
3. Kelly: size with fractional Kelly inside sleeve, event, position, depth,
   and mandate limits, previewed with the real accounting engine.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any
from urllib.parse import urlparse

from edgecraft.forecasts import FACT_MIN_P, FACT_PRIOR
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
    QuoteStatus,
    execution_fee,
    run_cycle_accounting,
)
from edgecraft.policy import TradingPolicy

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")
MINIMUM_EDGE = Decimal("0.0002")
HOURS_PER_YEAR = Decimal("8760")
POSITION_HEADROOM = Decimal("0.95")
MAX_OPEN_PRICE = Decimal("0.999")
# A venue's own page restates the market; it cannot prove the fact that settles it.
VENUE_HOSTS = ("polymarket.com", "kalshi.com")


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
    become trades. Explicit orders remain supported for inventory exits, while
    omitted entry orders are derived from hypotheses.
    """
    orders = list(decision.orders)
    explicit = {order.instrument_id for order in orders}
    quote_by_id = {quote.instrument_id: quote for quote in quotes}
    position_by_id = {position.instrument_id: position for position in state.positions}

    for hypothesis in decision.journal.hypotheses if decision.journal else ():
        if hypothesis.instrument_id in explicit or hypothesis.stance is HypothesisStance.FLAT:
            continue
        position = position_by_id.get(hypothesis.instrument_id)
        if hypothesis.stance is HypothesisStance.EXIT:
            if position is not None:
                orders.append(
                    FundOrder(
                        instrument_id=hypothesis.instrument_id,
                        asset_class=position.asset_class,
                        side=OrderSide.SELL,
                        quantity=abs(position.quantity),
                        rationale=hypothesis.statement,
                        evidence_ids=hypothesis.evidence_ids,
                    )
                )
            continue
        if position is not None:
            if hypothesis.stance is HypothesisStance.LONG:
                continue  # Maintained; no scale-in without a fresh entry decision.
            orders.append(
                FundOrder(
                    instrument_id=hypothesis.instrument_id,
                    asset_class=position.asset_class,
                    side=OrderSide.SELL,
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
        orders.append(
            FundOrder(
                instrument_id=hypothesis.instrument_id,
                asset_class=quote.asset_class,
                side=OrderSide.BUY
                if hypothesis.stance is HypothesisStance.LONG
                else OrderSide.SHORT,
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
    # Exits first so their proceeds can fund new entries.
    return tuple(sorted(orders, key=lambda order: order.side is OrderSide.BUY))


def shrink_to_market(p_win: Decimal, market: Decimal, trust: Decimal) -> Decimal:
    """Keep only the measured share of the forecast's disagreement with the market."""
    return market + trust * (p_win - market)


def _primary_source(order: FundOrder, evidence_by_id: Mapping[str, Any]) -> bool:
    """A fact needs evidence on this contract from a source other than the venue."""
    for evidence_id in order.evidence_ids:
        item = evidence_by_id.get(evidence_id)
        if item is None or order.instrument_id not in item.instrument_ids:
            continue
        host = (urlparse(item.source_url).hostname or "").lower()
        if host and not any(host == venue or host.endswith("." + venue) for venue in VENUE_HOSTS):
            return True
    return False


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


def _fit_entry(
    order: FundOrder,
    prior_orders: Sequence[FundOrder],
    *,
    decision: FundDecision,
    quotes: Sequence[FundQuote],
    state: FundState,
    mandate: FundMandate,
) -> tuple[FundOrder | None, str | None]:
    """Find the largest whole-contract quantity that fits; preview only.

    Use the real fill/cost/risk math rather than maintaining a second budget
    engine. Binary search keeps the result deterministic.
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
    low, high = 0, int(order.quantity)
    while low < high:
        middle = (low + high + 1) // 2
        if fits(Decimal(middle)):
            low = middle
        else:
            high = middle - 1
    if low == 0:
        return None, reason
    return order.model_copy(update={"quantity": Decimal(low)}), reason


def size_decision(
    *,
    decision: FundDecision,
    quotes: Sequence[FundQuote],
    state: FundState,
    mandate: FundMandate,
    trust: Mapping[str, Decimal] | None = None,
    facts: Mapping[str, Decimal] | None = None,
    sleeve_weights: dict[str, Decimal] | None = None,
    policy: TradingPolicy | None = None,
) -> SizingResult:
    """Replace missing entry quantities with fact- or trust-adjusted, velocity-ranked
    Kelly sizes.

    `trust=None` uses beliefs as stated (the code-only baseline already
    calibrates its own probabilities). Explicit exit quantities are preserved.
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
    # Release only inventory actually scheduled to exit in this cycle.
    exit_quantities: dict[str, Decimal] = {}
    for order in decision.orders:
        if order.side is OrderSide.SELL:
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
    prospects: list[dict[str, Any]] = []
    evidence_by_id = {item.evidence_id: item for item in decision.evidence}

    for order in decision.orders:
        if order.asset_class is not AssetClass.PREDICTION:
            raise PaperFundValidationError("belief sizing supports prediction contracts only")
        position = position_by_id.get(order.instrument_id)
        hypothesis = hypotheses.get(order.instrument_id)
        if order.side is OrderSide.SELL:
            mark = quote_by_id.get(order.instrument_id)
            if mark is not None and mark.status is QuoteStatus.PENDING:
                # No two-sided market to sell into; the position waits for settlement.
                dropped.append({"instrument_id": order.instrument_id, "reason": "quote_pending"})
                continue
            quantity = order.quantity or (abs(position.quantity) if position else None)
            if quantity is None:
                raise PaperFundValidationError(
                    f"cannot size exit without inventory: {order.instrument_id}"
                )
            orders.append(order.model_copy(update={"quantity": quantity}))
            accepted.append({"instrument_id": order.instrument_id, "reason": "inventory_exit"})
            continue
        if order.side is not OrderSide.BUY:
            dropped.append({"instrument_id": order.instrument_id, "reason": "buy_opposite_outcome"})
            continue
        # An entry needs evidence about its own contract, not only its event.
        if not any(
            order.instrument_id in evidence_by_id[evidence_id].instrument_ids
            for evidence_id in order.evidence_ids
            if evidence_id in evidence_by_id
        ):
            dropped.append(
                {"instrument_id": order.instrument_id, "reason": "no_instrument_evidence"}
            )
            continue
        quote = quote_by_id.get(order.instrument_id)
        if quote is None:
            raise PaperFundValidationError(f"missing quote for sized order {order.instrument_id}")
        if quote.status is not QuoteStatus.OPEN:
            dropped.append({"instrument_id": order.instrument_id, "reason": "quote_not_open"})
            continue
        if not quote.asks:
            dropped.append({"instrument_id": order.instrument_id, "reason": "no_displayed_asks"})
            continue
        p_win, target, stop = _belief(order, hypothesis)
        playbook_id = order.playbook_id or (hypothesis.playbook_id if hypothesis else None)
        kind, trust_value, believed = None, None, p_win
        if trust is not None and p_win >= FACT_MIN_P:
            kind = "fact"
            if not _primary_source(order, evidence_by_id):
                dropped.append(
                    {"instrument_id": order.instrument_id, "reason": "fact_without_primary_source"}
                )
                continue
            accuracy = (facts or {}).get(
                playbook_id or "", (facts or {}).get("*", Decimal(str(FACT_PRIOR)))
            )
            believed = min(p_win, accuracy)
        elif trust is not None:
            kind = "opinion"
            trust_value = trust.get(playbook_id or "", trust.get("*", ZERO))
            if trust_value <= ZERO:
                dropped.append(
                    {"instrument_id": order.instrument_id, "reason": "opinion_without_proven_skill"}
                )
                continue
            believed = shrink_to_market(p_win, quote.price, trust_value)
        ask = min(level.price for level in quote.asks)
        cost = ask + execution_fee(mandate, quote, ask, Decimal("100")) / 100
        edge = believed - cost
        horizon = Decimal(
            order.horizon_hours or (hypothesis.expected_horizon_hours if hypothesis else 8760)
        )
        annualized = edge / cost * HOURS_PER_YEAR / horizon
        base = {"instrument_id": order.instrument_id, "believed_p_win": str(believed)}
        if edge < MINIMUM_EDGE:
            dropped.append({**base, "reason": "below_edge_threshold", "edge": str(edge)})
            continue
        if annualized < policy.min_annualized_return:
            dropped.append(
                {**base, "reason": "below_annualized_hurdle", "annualized": str(annualized)}
            )
            continue
        prospects.append(
            dict(
                order=order,
                quote=quote,
                hypothesis=hypothesis,
                p_win=p_win,
                believed=believed,
                trust=trust_value,
                target=target,
                stop=stop,
                kind=kind,
                playbook_id=playbook_id,
                cost=cost,
                edge=edge,
                annualized=annualized,
            )
        )

    # Scarce cash goes to the fastest-compounding edge first.
    prospects.sort(key=lambda item: (item["annualized"], item["edge"]), reverse=True)
    for item in prospects:
        order, quote, hypothesis = item["order"], item["quote"], item["hypothesis"]
        playbook_id = item["playbook_id"]
        position = position_by_id.get(order.instrument_id)
        weight = (item["edge"] / (ONE - item["cost"])) * policy.kelly_fraction
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
        position_limit = min(mandate.max_single_position_weight, policy.max_prediction_weight)
        weight = min(weight, position_limit)
        remaining_driver = max(
            ZERO, state.nav * policy.max_driver_weight - driver_used.get(driver, ZERO)
        )
        # Headroom: later entries pay spread, which lowers NAV and would push
        # a position sized exactly at the cap over it, blocking every later entry.
        remaining_position = max(
            ZERO,
            nav_after_cost_budget * position_limit * POSITION_HEADROOM
            - instrument_used.get(order.instrument_id, ZERO),
        )
        remaining_sleeve = (
            max(ZERO, state.nav * sleeve_weights[playbook_id] - sleeve_used.get(playbook_id, ZERO))
            if enforce_sleeves
            else state.nav
        )
        notional = min(state.nav * weight, remaining_driver, remaining_sleeve, remaining_position)
        quantity = (notional / quote.price).quantize(ONE, rounding=ROUND_DOWN)
        if quantity <= ZERO:
            dropped.append(
                {"instrument_id": order.instrument_id, "reason": "quantity_rounded_to_zero"}
            )
            continue
        sized_order = order.model_copy(
            update={
                "quantity": quantity,
                "p_win": item["p_win"],
                "target_price": item["target"],
                "invalidation_price": item["stop"],
                "playbook_id": playbook_id,
                "driver": driver,
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
        fill = preview.fills[-1]
        quantity = sized_order.quantity
        # The fill walked the book. Add its fee, the expected early-exit fee
        # (a loser exits at its stop, a winner at its target; settlement is
        # free), and exit slippage. Displayed liquidity must not erase the edge.
        believed = item["believed"]
        exit_fee = (1 - believed) * execution_fee(mandate, quote, item["stop"], quantity) + (
            believed * execution_fee(mandate, quote, min(item["target"], MAX_OPEN_PRICE), quantity)
        )
        remaining_cost = (fill.fee + exit_fee) / quantity + mandate.slippage_bps / BPS
        executable = believed - fill.execution_price - remaining_cost
        if executable < MINIMUM_EDGE:
            dropped.append(
                {
                    "instrument_id": order.instrument_id,
                    "reason": "execution_erases_edge",
                    "expected_return": str(executable),
                    "execution_price": str(fill.execution_price),
                }
            )
            continue
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
                "p_win": str(item["p_win"]),
                "kind": item["kind"],
                "trust": str(item["trust"]) if item["trust"] is not None else None,
                "believed_p_win": str(item["believed"]),
                "expected_return": str(item["edge"]),
                "annualized_return": str(round(item["annualized"], 4)),
                "executable_expected_return": str(executable),
                "kelly_weight": str(weight),
                "notional": str(actual_notional),
                "capacity_adjustment": capacity_reason,
                "driver": driver,
                "playbook_id": playbook_id or "unassigned",
            }
        )

    action = DecisionAction.TRADE if orders else DecisionAction.HOLD
    # Copies skip validation; check the final decision before it can be applied.
    sized = FundDecision.model_validate(
        decision.model_copy(update={"orders": tuple(orders), "action": action}).model_dump()
    )
    return SizingResult(decision=sized, accepted=tuple(accepted), dropped=tuple(dropped))
