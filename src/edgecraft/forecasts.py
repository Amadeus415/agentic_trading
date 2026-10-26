"""Forecast log: many cheap probability calls, scored against the market.

Closed trades are too few and too noisy to learn from. Forecasts on many
markets, each stamped with the code-owned market price at the moment it was
made, measure whether a playbook knows more than the market. Two numbers per
playbook come from settled forecasts only:

- trust (lambda) for opinions: sizing bets on market + trust * (forecast - market),
  using the lower 95% bound of lambda. Until settled forecasts prove skill, trust
  is zero and opinions are forecast, never traded.
- fact accuracy for facts: how often a call that the outcome is already decided
  (p >= 0.95 while the market doubted it) settled that way, starting from a 0.95 prior.

Later price drift is reported but never sizes a bet: early drift estimates
trusted forecasts that settled worse than the market. The same log fits the
favorite-longshot curve the code-only baseline trades.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from edgecraft.paper_fund import (
    AssetClass,
    FundDecision,
    FundQuote,
    PaperFundLedger,
    QuoteStatus,
)
from edgecraft.policy import TradingPolicy

MARKET_VARIANT = "market"
CACHE_FRESHNESS = timedelta(minutes=15)
DRIFT_MIN_AGE = timedelta(hours=12)
# Resolved observations a fitted bias curve needs before it outweighs the prior.
GAMMA_PRIOR_WEIGHT = 100
# A belief at or above this p_win claims the outcome is already decided by a public fact.
FACT_MIN_P = Decimal("0.95")
# Fact accuracy starts at the claim itself and moves with settled fact calls.
FACT_PRIOR = 0.95
FACT_PRIOR_WEIGHT = 20
# Log-likelihood drop that bounds a 95% profile-likelihood interval for lambda.
LAMBDA_BOUND_DROP = 1.92
LAMBDA_GRID = [round(-0.5 + step * 0.05, 2) for step in range(41)]  # -0.5 .. 1.5
GAMMA_GRID = [round(0.7 + step * 0.05, 2) for step in range(37)]  # 0.7 .. 2.5


class ForecastInput(BaseModel):
    """One research probability. Code stamps the market price, never the model."""

    model_config = ConfigDict(extra="forbid")

    market_id: str = Field(pattern=r"^(polymarket|kalshi):[A-Za-z0-9_.-]{1,120}$")
    p_yes: Decimal = Field(ge=0, le=1)
    variant: str = Field(min_length=1, max_length=128)
    category: str = Field(default="uncategorized", min_length=1, max_length=64)
    question: str = Field(default="", max_length=500)
    resolves_at: datetime | None = None

    @field_validator("market_id", mode="before")
    @classmethod
    def _strip_side(cls, value: Any) -> Any:
        text = str(value)
        return text.rsplit(":", 1)[0] if text.endswith((":YES", ":NO")) else text


class ForecastFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fund_id: str = Field(min_length=1, max_length=128)
    forecasts: tuple[ForecastInput, ...] = Field(min_length=1, max_length=400)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _record(
    *,
    market_id: str,
    p_yes: Decimal,
    market_yes: Decimal,
    observed_at: datetime,
    variant: str,
    category: str,
    question: str,
    resolves_at: datetime | str | None,
    quote_id: str | None = None,
) -> dict[str, Any]:
    if isinstance(resolves_at, datetime):
        resolves_at = _iso(resolves_at)
    return {
        "market_id": market_id,
        "p_yes": str(p_yes),
        "market_yes": str(market_yes),
        "observed_at": _iso(observed_at),
        "variant": variant,
        "category": category,
        "question": question[:500],
        "resolves_at": resolves_at,
        "quote_id": quote_id,
    }


def _yes_quote(router: Any, market_id: str, now: datetime) -> FundQuote:
    instrument = f"{market_id}:YES"
    try:
        cached = router.latest_cached_quote(instrument, at_or_before=now)
        if now - cached.observed_at <= CACHE_FRESHNESS:
            return cached
    except Exception:  # No fresh cached quote; fetch one below.
        pass
    return router.quote(instrument, AssetClass.PREDICTION)


def record_research_forecasts(
    ledger: PaperFundLedger,
    fund_id: str,
    forecasts: ForecastFile,
    router: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Stamp each forecast with a code-owned open market price and append one batch.

    Recording is idempotent: a session records its file as soon as it is written, and
    the apply step records it again without duplicating what already counts.
    """
    if forecasts.fund_id != fund_id:
        raise ValueError("forecast file fund_id does not match config")
    now = now or datetime.now(UTC)
    known = {
        (row["market_id"], row["variant"]) for row in forecast_log(ledger, fund_id)["forecasts"]
    }
    records, failures, already = [], [], 0
    for item in forecasts.forecasts:
        if (item.market_id, item.variant) in known:
            already += 1
            continue
        try:
            quote = _yes_quote(router, item.market_id, now)
            if quote.status is not QuoteStatus.OPEN:
                raise ValueError("market is settled or pending; forecasts must precede outcomes")
        except Exception as exc:
            failures.append({"market_id": item.market_id, "detail": str(exc)})
            continue
        records.append(
            _record(
                market_id=item.market_id,
                p_yes=item.p_yes,
                market_yes=quote.price,
                observed_at=quote.observed_at,
                variant=item.variant,
                category=item.category,
                question=item.question,
                resolves_at=item.resolves_at,
                quote_id=quote.quote_id,
            )
        )
    if not records and not already:
        raise ValueError(f"no forecast could be stamped with a market price: {failures}")
    if records:
        ledger.record_operational_event(
            fund_id, "forecast_batch", {"source": "research", "forecasts": records}
        )
    return {
        "ok": True,
        "recorded": len(records),
        "already_recorded": already,
        "failures": failures,
    }


def journal_forecasts(decision: FundDecision, quotes: Sequence[FundQuote]) -> list[dict[str, Any]]:
    """Directional journal beliefs are forecasts too; convert them to YES terms."""
    quote_by_id = {quote.instrument_id: quote for quote in quotes}
    records = []
    for hypothesis in decision.journal.hypotheses if decision.journal else ():
        quote = quote_by_id.get(hypothesis.instrument_id)
        if hypothesis.p_win is None or quote is None or quote.status is not QuoteStatus.OPEN:
            continue
        market_id, _, side = hypothesis.instrument_id.rpartition(":")
        if side not in {"YES", "NO"} or hypothesis.stance.value not in {"long", "flat"}:
            continue
        # A flat stance still states p_win for the named outcome.
        p_yes = hypothesis.p_win if side == "YES" else 1 - hypothesis.p_win
        market_yes = quote.price if side == "YES" else 1 - quote.price
        records.append(
            _record(
                market_id=market_id,
                p_yes=p_yes,
                market_yes=market_yes,
                observed_at=quote.observed_at,
                variant=hypothesis.playbook_id or "unassigned",
                category="uncategorized",
                question=hypothesis.statement,
                resolves_at=quote.observed_at + timedelta(hours=hypothesis.expected_horizon_hours),
                quote_id=quote.quote_id,
            )
        )
    return records


def market_forecasts(
    markets: Iterable[Mapping[str, Any]],
    known: set[str],
    *,
    observed_at: datetime,
    limit: int = 300,
) -> list[dict[str, Any]]:
    """Record the market's own listed price once per contract to fit the bias curve."""
    records = []
    for row in markets:
        key = f"{row['venue']}:{row['market_id']}"
        if key in known or row.get("listing_mid") is None:
            continue
        records.append(
            _record(
                market_id=key,
                p_yes=Decimal(str(row["listing_mid"])),
                market_yes=Decimal(str(row["listing_mid"])),
                observed_at=observed_at,
                variant=MARKET_VARIANT,
                category=row.get("category") or "uncategorized",
                question=row.get("question", ""),
                resolves_at=row.get("end_at"),
            )
        )
        known.add(key)
        if len(records) >= limit:
            break
    return records


def forecast_log(ledger: PaperFundLedger, fund_id: str) -> dict[str, Any]:
    """Collapse the event chain into forecasts, outcomes, and latest marks."""
    forecasts: dict[tuple[str, str], dict[str, Any]] = {}
    outcomes: dict[str, int] = {}
    marks: dict[str, list[tuple[datetime, Decimal]]] = defaultdict(list)
    checked: dict[str, datetime] = {}
    last_batch: datetime | None = None
    for event in ledger.list_events(fund_id):
        if event.event_type == "forecast_batch":
            last_batch = event.occurred_at
            for row in event.payload.get("forecasts", []):
                # First forecast per contract and variant: refreshes never add samples.
                forecasts.setdefault((row["market_id"], row["variant"]), row)
        elif event.event_type == "forecast_scoring":
            for row in event.payload.get("resolutions", []):
                outcomes.setdefault(row["market_id"], int(row["outcome"]))
                checked[row["market_id"]] = _dt(row["observed_at"])
            for row in event.payload.get("marks", []):
                at = _dt(row["observed_at"])
                marks[row["market_id"]].append((at, Decimal(row["price"])))
                checked[row["market_id"]] = at
    return {
        "forecasts": list(forecasts.values()),
        "outcomes": outcomes,
        "marks": marks,
        "checked": checked,
        "last_batch_at": last_batch,
    }


def score_forecasts(
    ledger: PaperFundLedger,
    fund_id: str,
    router: Any,
    *,
    limit: int = 60,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch outcomes (and drift marks for research forecasts) for open forecasts."""
    now = now or datetime.now(UTC)
    log = forecast_log(ledger, fund_id)
    research: set[str] = set()
    due: set[str] = set()
    for row in log["forecasts"]:
        market = row["market_id"]
        if market in log["outcomes"]:
            continue
        if row["variant"] != MARKET_VARIANT:
            research.add(market)
        if row.get("resolves_at") is None or _dt(row["resolves_at"]) <= now:
            due.add(market)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    # Past-due contracts first, then the least recently checked research contracts.
    queue = sorted(
        research | due,
        key=lambda market: (market not in due, log["checked"].get(market, epoch)),
    )[:limit]
    from edgecraft.marketdata import fetch_quotes

    quotes, failures = fetch_quotes(router, [f"{market}:YES" for market in queue])
    resolutions, marks = [], []
    for market in queue:
        quote = quotes.get(f"{market}:YES")
        if quote is None:
            continue
        row = {"market_id": market, "observed_at": _iso(quote.observed_at)}
        if quote.status is QuoteStatus.SETTLED:
            resolutions.append({**row, "outcome": int(quote.price)})
        elif market in research and quote.status is QuoteStatus.OPEN:
            marks.append({**row, "price": str(quote.price)})
    if resolutions or marks:
        ledger.record_operational_event(
            fund_id, "forecast_scoring", {"resolutions": resolutions, "marks": marks}
        )
    return {
        "ok": True,
        "checked": len(queue),
        "resolved": len(resolutions),
        "marked": len(marks),
        "failures": failures,
    }


def _clip(value: float) -> float:
    return min(0.99, max(0.01, value))


def _logit(value: float) -> float:
    value = _clip(value)
    return math.log(value / (1 - value))


def favorite_bias_probability(price: Decimal, gamma: Decimal) -> Decimal:
    """Favorite-longshot correction: stretch the market's log-odds by gamma > 1."""
    stretched = float(gamma) * _logit(float(price))
    return Decimal(str(round(1 / (1 + math.exp(-stretched)), 6)))


def _loglik(pairs: Sequence[tuple[float, int]]) -> float:
    return sum(math.log(p if y else 1 - p) for p, y in pairs)


def _fit_trust(rows: Sequence[tuple[float, float, int]]) -> tuple[float, float] | None:
    """Maximum-likelihood lambda for p = market + lambda * (forecast - market),
    with the lower end of its 95% profile-likelihood interval."""
    if not rows:
        return None
    fits = {
        lam: _loglik([(_clip(m + lam * (f - m)), y) for f, m, y in rows]) for lam in LAMBDA_GRID
    }
    best = max(fits, key=fits.__getitem__)
    lower = min(lam for lam, value in fits.items() if value >= fits[best] - LAMBDA_BOUND_DROP)
    return best, lower


def _is_fact_call(p_yes: float, market_yes: float) -> bool:
    """The forecast says the outcome is decided while the market still doubts it."""
    p, market = (p_yes, market_yes) if p_yes >= 0.5 else (1 - p_yes, 1 - market_yes)
    return p >= float(FACT_MIN_P) and market < float(FACT_MIN_P)


def fit_gamma(rows: Sequence[tuple[float, int]]) -> float | None:
    if not rows:
        return None
    return max(
        GAMMA_GRID,
        key=lambda g: _loglik([(_clip(1 / (1 + math.exp(-g * _logit(m)))), y) for m, y in rows]),
    )


def _metrics(rows: list[dict[str, Any]], policy: TradingPolicy) -> dict[str, Any]:
    resolved = [row for row in rows if row["outcome"] is not None]
    drifted = [row for row in rows if row["later_market"] is not None]
    model = [(float(r["p_yes"]) - r["outcome"]) ** 2 for r in resolved]
    market = [(float(r["market_yes"]) - r["outcome"]) ** 2 for r in resolved]
    signed = [
        (r["later_market"] - float(r["market_yes"]))
        * math.copysign(1, float(r["p_yes"]) - float(r["market_yes"]))
        for r in drifted
        if float(r["p_yes"]) != float(r["market_yes"])
    ]
    fit = (
        _fit_trust([(float(r["p_yes"]), float(r["market_yes"]), r["outcome"]) for r in resolved])
        if len(resolved) >= 10
        else None
    )
    # Opinions earn capital only once settled forecasts prove skill; the lower
    # bound keeps a lucky streak from sizing like a measured edge.
    proven = fit is not None and len(resolved) >= policy.promotion_forecasts
    trust = min(1.0, max(0.0, fit[1])) if proven else 0.0
    facts = [r for r in resolved if _is_fact_call(float(r["p_yes"]), float(r["market_yes"]))]
    fact_wins = sum(r["outcome"] == (1 if float(r["p_yes"]) >= 0.5 else 0) for r in facts)
    return {
        "forecasts": len(rows),
        "resolved": len(resolved),
        "model_brier": round(sum(model) / len(model), 6) if model else None,
        "market_brier": round(sum(market) / len(market), 6) if market else None,
        # Positive skill: the forecasts beat the market's own price at the time.
        "skill": round((sum(market) - sum(model)) / len(model), 6) if model else None,
        "drift_observed": len(drifted),
        "mean_drift_toward_forecast": round(sum(signed) / len(signed), 6) if signed else None,
        "fitted_trust": fit[0] if fit else None,
        "trust_lower": fit[1] if fit else None,
        "trust_basis": "resolution" if proven else "unproven",
        "scored": len(resolved),
        "estimated_trust": fit[0] if fit else None,
        "trust": round(trust, 4),
        "fact_calls": len(facts),
        "fact_wins": fact_wins,
        "fact_accuracy": round(
            (fact_wins + FACT_PRIOR * FACT_PRIOR_WEIGHT) / (len(facts) + FACT_PRIOR_WEIGHT), 4
        ),
    }


def forecast_skill(
    ledger: PaperFundLedger, fund_id: str, policy: TradingPolicy | None = None
) -> dict[str, Any]:
    """Per-variant and per-category skill, sizing trust, head-to-head, and bias curve."""
    policy = policy or TradingPolicy()
    log = forecast_log(ledger, fund_id)
    rows = []
    for forecast in log["forecasts"]:
        made = _dt(forecast["observed_at"])
        # A mark minutes after the forecast is noise: the market has not had time to learn.
        later = [
            price
            for at, price in log["marks"].get(forecast["market_id"], [])
            if at - made >= DRIFT_MIN_AGE
        ]
        rows.append(
            {
                **forecast,
                "outcome": log["outcomes"].get(forecast["market_id"]),
                "later_market": float(later[-1]) if later else None,
            }
        )
    research = [row for row in rows if row["variant"] != MARKET_VARIANT]
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in research:
        by_variant[row["variant"]].append(row)
        by_category[row["category"]].append(row)
    variants = {name: _metrics(items, policy) for name, items in sorted(by_variant.items())}
    head_to_head = []
    names = sorted(by_variant)
    for index, left in enumerate(names):
        left_rows = {r["market_id"]: r for r in by_variant[left] if r["outcome"] is not None}
        for right in names[index + 1 :]:
            right_rows = {r["market_id"]: r for r in by_variant[right] if r["outcome"] is not None}
            shared = sorted(set(left_rows) & set(right_rows))
            if len(shared) < 5:
                continue
            diff = [
                (float(right_rows[m]["p_yes"]) - right_rows[m]["outcome"]) ** 2
                - (float(left_rows[m]["p_yes"]) - left_rows[m]["outcome"]) ** 2
                for m in shared
            ]
            head_to_head.append(
                {
                    "left": left,
                    "right": right,
                    "shared_resolved": len(shared),
                    # Positive: left had the lower Brier score on the same contracts.
                    "left_advantage": round(sum(diff) / len(diff), 6),
                }
            )
    bias_rows = [
        (float(row["market_yes"]), row["outcome"])
        for row in rows
        if row["variant"] == MARKET_VARIANT and row["outcome"] is not None
    ]
    fitted_gamma = fit_gamma(bias_rows) if len(bias_rows) >= 20 else None
    gamma = float(policy.baseline_gamma)
    if fitted_gamma is not None:
        n = len(bias_rows)
        gamma = (n * fitted_gamma + GAMMA_PRIOR_WEIGHT * gamma) / (n + GAMMA_PRIOR_WEIGHT)
    return {
        "schema_version": "edgecraft.forecast-skill.v1",
        "fund_id": fund_id,
        "summary": _metrics(research, policy),
        "variants": variants,
        "categories": {
            name: _metrics(items, policy) for name, items in sorted(by_category.items())
        },
        "head_to_head": head_to_head,
        "trust": {name: item["trust"] for name, item in variants.items()},
        "fact_accuracy": {name: item["fact_accuracy"] for name, item in variants.items()},
        "favorite_bias": {
            "observed": sum(row["variant"] == MARKET_VARIANT for row in rows),
            "resolved": len(bias_rows),
            "fitted_gamma": fitted_gamma,
            "gamma": round(max(1.0, gamma), 4),
            "prior_gamma": float(policy.baseline_gamma),
        },
        "last_batch_at": _iso(log["last_batch_at"]) if log["last_batch_at"] else None,
        "interpretation": "Trust shrinks each opinion toward the market price before sizing. "
        "It is zero until settled forecasts prove skill, then the lower 95% bound of the "
        "fitted lambda. Fact accuracy caps the probability of a call that the outcome is "
        "already decided. Skill > 0 means forecasts beat the market's price at the time. "
        "Gamma > 1 means favorites settle more often than their price implies.",
    }


def trust_map(skill: Mapping[str, Any]) -> dict[str, Decimal]:
    """Opinion sizing trust per playbook; unmeasured playbooks get none."""
    return {
        "*": Decimal("0"),
        **{name: Decimal(str(value)) for name, value in skill["trust"].items()},
    }


def fact_map(skill: Mapping[str, Any]) -> dict[str, Decimal]:
    """Highest p_win a fact call may carry per playbook, from its settled fact record."""
    return {
        "*": Decimal(str(FACT_PRIOR)),
        **{name: Decimal(str(value)) for name, value in skill["fact_accuracy"].items()},
    }
