"""The code-only control fund: two structural edges, no model in the loop.

1. Favorite bias. Contracts priced near certainty settle more often than their
   price implies (the favorite-longshot bias). Buy favorites that resolve soon
   when the fitted bias curve clears fees; the curve's gamma is refit from every
   scanned market's own price once those markets settle.
2. Exclusive NO baskets. When at most one listed outcome can win but the YES
   bids sum above $1, buying NO on every outcome locks in the excess.

If the research fund cannot beat this one, the model is costing money.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any

from edgecraft import __version__
from edgecraft.forecasts import (
    favorite_bias_probability,
    forecast_log,
    forecast_skill,
    market_forecasts,
)
from edgecraft.marketdata import fetch_quotes
from edgecraft.monitor import latest_hypotheses
from edgecraft.paper_fund import (
    AssetClass,
    CycleRuntimeMetadata,
    DecisionAction,
    DecisionJournal,
    FundDecision,
    FundEvidence,
    FundHypothesis,
    FundMandate,
    FundOrder,
    FundQuote,
    HypothesisStance,
    OrderSide,
    PaperFundLedger,
    PaperFundValidationError,
    QuoteStatus,
    execution_fee,
    mandate_digest,
    run_cycle_accounting,
)
from edgecraft.policy import TradingPolicy
from edgecraft.scanner import book_metrics, discover_markets, event_flags, prerank
from edgecraft.sizing import size_decision

BASELINE_FUND_ID = "edgecraft-baseline"
FAVORITE = "favorite_bias"
BASKET = "exclusive_no_basket"
MAX_FAVORITE_BOOKS = 30
MAX_BASKETS = 3
MAX_JOURNAL = 40  # DecisionJournal hypothesis limit
MIN_BASKET_EDGE = Decimal("0.01")
MARKET_FORECAST_SPREAD = Decimal("0.04")


def _evidence(quote: FundQuote, claim: str, summary: str = "") -> FundEvidence:
    return FundEvidence(
        evidence_id=f"baseline-{quote.quote_id}",
        observed_at=quote.observed_at,
        source_timestamp=quote.source_timestamp,
        source_name=quote.source_name,
        source_url=quote.source_url,
        claim=claim[:2000],
        summary=summary[:4000],
        instrument_ids=(quote.instrument_id,),
    )


def _horizon(hours: Decimal) -> int:
    # Allow a day past the scheduled resolution for the venue to settle.
    return max(1, min(8_760, math.ceil(hours) + 24))


def favorite_hypothesis(row: dict[str, Any], quote: FundQuote, gamma: Decimal) -> FundHypothesis:
    ask = Decimal(row["ask"])
    p_win = favorite_bias_probability(quote.price, gamma)
    return FundHypothesis(
        instrument_id=row["instrument_id"],
        stance=HypothesisStance.LONG,
        statement=f"{row['question'][:300]}: {row['instrument_id'].rsplit(':', 1)[1]} "
        f"is the favorite at {ask}; bias-corrected p_win {p_win}.",
        mechanism=f"Favorite-longshot bias: favorites settle more often than their price "
        f"implies (gamma {gamma}).",
        catalysts=(f"Scheduled resolution {row['end_at']}",),
        falsifiers=("Price falls to the invalidation level", "Rule surprise or dispute"),
        expected_horizon_hours=_horizon(Decimal(row["hours_to_resolution"])),
        confidence=p_win,
        p_win=p_win,
        playbook_id=FAVORITE,
        driver=row["event_id"][:128],
        target_price=Decimal("0.999"),
        invalidation_price=max(Decimal("0.01"), ask - Decimal("0.30")),
        evidence_ids=(f"baseline-{quote.quote_id}",),
    )


def basket_orders(
    flag: dict[str, Any],
    quotes: dict[str, FundQuote],
    rows: dict[str, dict[str, Any]],
    mandate: FundMandate,
    budget: Decimal,
) -> tuple[list[FundOrder], list[FundHypothesis], dict[str, Any]] | None:
    """Equal NO quantity on every leg when executable asks still lock in a profit."""
    legs = flag["legs"]
    if any(leg not in quotes or not quotes[leg].asks for leg in legs):
        return None
    asks = {leg: min(level.price for level in quotes[leg].asks) for leg in legs}
    cost = sum(
        (asks[leg] + execution_fee(mandate, quotes[leg], asks[leg], Decimal("100")) / 100)
        for leg in legs
    )
    edge = Decimal(len(legs) - 1) - cost
    if edge < MIN_BASKET_EDGE:
        return None
    depth = min(
        sum(level.size for level in quotes[leg].asks if level.price == asks[leg]) for leg in legs
    )
    quantity = min(depth, budget / cost).quantize(Decimal("1"), rounding=ROUND_DOWN)
    if quantity < 1:
        return None
    orders, hypotheses = [], []
    for leg in legs:
        quote = quotes[leg]
        row = rows.get(leg, {})
        statement = (
            f"NO on every outcome of '{flag['event_title'][:200]}': at most one can win, "
            f"so the basket pays at least {len(legs) - 1} for {cost} per set."
        )
        evidence_id = f"baseline-{quote.quote_id}"
        orders.append(
            FundOrder(
                instrument_id=leg,
                asset_class=AssetClass.PREDICTION,
                side=OrderSide.BUY,
                quantity=quantity,
                p_win=1 - Decimal(str(row.get("yes_mid", "0.5"))),
                target_price=Decimal("0.999"),
                invalidation_price=Decimal("0.001"),
                horizon_hours=_horizon(Decimal(str(row.get("hours", "720")))),
                playbook_id=BASKET,
                driver=flag["event_id"][:128],
                rationale=statement,
                evidence_ids=(evidence_id,),
            )
        )
        hypotheses.append(
            FundHypothesis(
                instrument_id=leg,
                stance=HypothesisStance.LONG,
                statement=statement,
                mechanism="Mutually exclusive outcomes: at most one YES can settle at $1.",
                catalysts=("Event resolution",),
                falsifiers=("Rules allow more than one listed outcome to resolve YES",),
                expected_horizon_hours=_horizon(Decimal(str(row.get("hours", "720")))),
                confidence=Decimal("1") - Decimal(str(row.get("yes_mid", "0.5"))),
                p_win=Decimal("1") - Decimal(str(row.get("yes_mid", "0.5"))),
                playbook_id=BASKET,
                driver=flag["event_id"][:128],
                target_price=Decimal("0.999"),
                invalidation_price=Decimal("0.001"),
                evidence_ids=(evidence_id,),
            )
        )
    audit = {
        "event_id": flag["event_id"],
        "legs": len(legs),
        "cost_per_basket": str(cost),
        "locked_edge_per_basket": str(edge),
        "quantity": str(quantity),
    }
    return orders, hypotheses, audit


def fitted_gamma(ledger: PaperFundLedger, policy: TradingPolicy) -> Decimal:
    """The baseline fund's fitted bias curve, shared with research scans in the same ledger."""
    try:
        ledger.get_mandate(BASELINE_FUND_ID)
    except PaperFundValidationError:
        return policy.baseline_gamma
    skill = forecast_skill(ledger, BASELINE_FUND_ID, policy)
    return Decimal(str(skill["favorite_bias"]["gamma"]))


def run_baseline(
    ledger: PaperFundLedger,
    fund_id: str,
    mandate: FundMandate,
    policy: TradingPolicy,
    router: Any,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """One scan-decide-apply pass. Writes a cycle only when there is something to buy."""
    now = now or datetime.now(UTC)
    log = forecast_log(ledger, fund_id)
    last = log["last_batch_at"]
    if not force and last and now - last < timedelta(minutes=policy.baseline_interval_minutes):
        return {"ok": True, "applied": False, "reason": "interval_not_elapsed"}
    gamma = Decimal(str(forecast_skill(ledger, fund_id, policy)["favorite_bias"]["gamma"]))
    markets = discover_markets(now=now, max_days=policy.baseline_max_days, pages=2)
    sides, _ = prerank(markets, mandate, now=now)
    eligible = {
        (row["venue"], row["market_id"]): row
        for row in sides
        if row["listing_mid"] is not None
        and row["yes_ask"] - row["yes_bid"] <= MARKET_FORECAST_SPREAD
    }
    known = {row["market_id"] for row in log["forecasts"]}
    recorded = market_forecasts(eligible.values(), known, observed_at=now)
    ledger.record_operational_event(
        fund_id, "forecast_batch", {"source": "market", "forecasts": recorded}
    )

    state = ledger.get_state(fund_id)
    held = {position.instrument_id for position in state.positions}
    favorites = [
        row
        for row in sides
        if policy.baseline_min_price <= row["indicative_ask"] <= policy.baseline_max_price
        and row["instrument_id"] not in held
        and favorite_bias_probability((row["indicative_ask"] + row["indicative_bid"]) / 2, gamma)
        > row["indicative_ask"]
    ]
    favorites.sort(key=lambda row: row["hours_to_resolution"])
    quotes, failures = fetch_quotes(
        router, [position.instrument_id for position in state.positions]
    )
    if failures:
        return {"ok": False, "applied": False, "reason": "mark_fetch_failed", "failures": failures}
    room = MAX_JOURNAL - len(state.positions)
    shortlist = favorites[: min(MAX_FAVORITE_BOOKS, room)]
    flags = [
        flag
        for flag in event_flags(markets, mandate, now=now)[:MAX_BASKETS]
        if not any(leg in held for leg in flag["legs"])
    ]
    # Fetch every candidate and basket leg before fixing the decision time.
    fetched, failures = fetch_quotes(
        router,
        [row["instrument_id"] for row in shortlist]
        + [leg for flag in flags for leg in flag["legs"]],
    )
    quotes.update(fetched)
    candidates = []
    for row in shortlist:
        quote = quotes.get(row["instrument_id"])
        metrics = quote and book_metrics(row, quote, mandate, policy, gamma)
        if metrics and Decimal(metrics["favorite_bias_edge"]) > 0:
            candidates.append((metrics, quote))
    flags = [
        flag
        for flag in flags
        if all(leg in quotes and quotes[leg].status is QuoteStatus.OPEN for leg in flag["legs"])
    ]

    latest, _ = latest_hypotheses(ledger.list_full_cycles(fund_id))
    evidence: dict[str, FundEvidence] = {}

    def cite(quote: FundQuote, claim: str, summary: str = "") -> tuple[str, ...]:
        item = _evidence(quote, claim, summary)
        evidence.setdefault(item.evidence_id, item)
        return (item.evidence_id,)

    hypotheses = [
        latest[position.instrument_id][0].model_copy(
            update={
                "evidence_ids": cite(
                    quotes[position.instrument_id],
                    f"Code-owned mark {quotes[position.instrument_id].price}.",
                )
            }
        )
        for position in state.positions
        if position.instrument_id in latest
    ]
    for metrics, quote in candidates:
        cite(
            quote,
            f"Best ask {metrics['ask']}, mid {metrics['mid']}, resolves {metrics['end_at']}.",
            metrics["rules"],
        )
        hypotheses.append(favorite_hypothesis(metrics, quote, gamma))
    as_of = max((quote.observed_at for quote in quotes.values()), default=now)
    cycle_key = as_of.strftime("baseline-%Y-%m-%dT%H%M%SZ")
    decision = FundDecision(
        decision_id=f"decision-{cycle_key}",
        fund_id=fund_id,
        cycle_key=cycle_key,
        as_of=as_of,
        action=DecisionAction.HOLD,
        thesis="Code-only baseline: favorite-longshot bias and exclusive NO baskets.",
        alternatives="Cash when no favorite clears fees and no basket locks in a profit.",
        risks="Bias curve may not hold for every venue or category; disputes; thin books.",
        journal=DecisionJournal(
            market_regime="Not assessed by the code-only baseline.",
            opportunity_set=f"{len(candidates)} favorites cleared fees at gamma {gamma}.",
            portfolio_intent="Compound many small, fast, structural edges.",
            what_changed=f"Recorded {len(recorded)} market forecasts for the bias fit.",
            hypotheses=tuple(hypotheses),
        ),
        evidence=tuple(evidence.values()),
    )
    sizing = size_decision(
        decision=decision,
        quotes=list(quotes.values()),
        state=state,
        mandate=mandate,
        trust=None,
        policy=policy,
    )
    # Keep the journal to held and ordered contracts so baskets fit beside it.
    keep = held | {order.instrument_id for order in sizing.decision.orders}
    decision = sizing.decision.model_copy(
        update={
            "journal": sizing.decision.journal.model_copy(
                update={
                    "hypotheses": tuple(
                        item
                        for item in sizing.decision.journal.hypotheses
                        if item.instrument_id in keep
                    )
                }
            )
        }
    )

    baskets = []
    rows = {
        row["instrument_id"]: {"yes_mid": row["listing_mid"], "hours": row["hours_to_resolution"]}
        for row in sides
        if row["side"] == "NO" and row["listing_mid"] is not None
    }
    for flag in flags:
        legs = flag["legs"]
        if any(leg in keep for leg in legs) or len(decision.journal.hypotheses) + len(legs) > (
            MAX_JOURNAL
        ):
            continue
        leg_quotes = {leg: quotes[leg] for leg in legs}
        built = basket_orders(flag, leg_quotes, rows, mandate, state.nav * policy.max_driver_weight)
        if built is None:
            continue
        orders, basket_hypotheses, audit = built
        for leg in legs:
            cite(leg_quotes[leg], f"NO ask {min(q.price for q in leg_quotes[leg].asks)}.")
        trial = decision.model_copy(
            update={
                "action": DecisionAction.TRADE,
                "orders": (*decision.orders, *orders),
                "journal": decision.journal.model_copy(
                    update={"hypotheses": (*decision.journal.hypotheses, *basket_hypotheses)}
                ),
                "evidence": tuple(evidence.values()),
            }
        )
        try:
            run_cycle_accounting(
                mandate=mandate, prior_state=state, decision=trial, quotes=list(quotes.values())
            )
        except PaperFundValidationError:
            continue
        decision = trial
        keep |= set(legs)
        baskets.append(audit)

    if not decision.orders:
        return {
            "ok": True,
            "applied": False,
            "reason": "no_edge",
            "gamma": str(gamma),
            "market_forecasts": len(recorded),
            "favorites_checked": len(candidates),
            "dropped": list(sizing.dropped),
            "failures": failures,
        }
    runtime = CycleRuntimeMetadata(
        edgecraft_version=__version__,
        mandate_digest=mandate_digest(mandate),
        prompt_version="code-only-baseline-v1",
        model="code-only-baseline",
        reasoning_effort="none",
        recorded_at=datetime.now(UTC),
    )
    result = ledger.execute_cycle(
        decision,
        list(quotes.values()),
        runtime=runtime,
        require_brain_journal=True,
        decision_audit={
            "sizing": {
                "policy": policy.model_dump(mode="json"),
                "gamma": str(gamma),
                "accepted": sizing.accepted,
                "dropped": sizing.dropped,
                "baskets": baskets,
            }
        },
    )
    return {
        "ok": True,
        "applied": True,
        "cycle_key": result.cycle_key,
        "gamma": str(gamma),
        "market_forecasts": len(recorded),
        "fills": len(result.fills),
        "accepted": list(sizing.accepted),
        "baskets": baskets,
        "nav": str(result.state.nav),
        "cash": str(result.state.cash),
        "failures": failures,
    }
