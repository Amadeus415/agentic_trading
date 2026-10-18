"""Bounded public discovery aimed where an edge can exist and compound quickly.

Rank favors contracts that resolve soon (capital turns over) and that few
traders watch (prices adjust slowly). Liquidity is a constraint, not the goal:
a market needs only enough displayed depth to fill this fund's size. Rank is
a research priority, never evidence of alpha.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlencode

from edgecraft.forecasts import favorite_bias_probability
from edgecraft.marketdata import (
    KALSHI_API,
    MarketDataError,
    MarketDataRouter,
    _get_json,
    fetch_quotes,
)
from edgecraft.paper_fund import FundMandate, execution_fee
from edgecraft.policy import TradingPolicy

# Exclude price-direction speculation until a separately validated reference
# model exists. This conservative screen is followed by semantic rule review.
PRICE_BET = re.compile(
    r"\b(bitcoin|btc|ethereum|eth|solana|xrp|dogecoin|crypto|stock|share price|s&p|"
    r"nasdaq|dow jones|up or down)\b",
    re.I,
)
# Discovery splits the horizon so near-dated contracts cannot crowd out the rest.
WINDOWS_HOURS = ((1, 24), (24, 72), (72, 168), (168, 24 * 365))
MAX_SPREAD = Decimal("0.10")
MAX_BASKET_SUM = Decimal("1.25")


def _hours(end: str | None, now: datetime) -> Decimal | None:
    try:
        moment = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return Decimal(str(round((moment - now).total_seconds() / 3600, 4)))


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _polymarket_rows(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for market in markets:
        labels = market.get("outcomes") or []
        if isinstance(labels, str):
            labels = json.loads(labels)
        if [str(label).lower() for label in labels] != ["yes", "no"]:
            continue  # Team-labelled and multi-outcome contracts need another schema.
        event = (market.get("events") or [{}])[0]
        rows.append(
            dict(
                venue="polymarket",
                market_id=str(market["id"]),
                event_id=f"polymarket:{event.get('id', market['id'])}",
                event_title=event.get("title", ""),
                mutually_exclusive=bool(event.get("negRisk")),
                question=market.get("question", ""),
                rules=market.get("description", ""),
                end_at=market.get("endDate"),
                yes_bid=_dec(market.get("bestBid")),
                yes_ask=_dec(market.get("bestAsk")),
                yes_bid_size=None,
                yes_ask_size=None,
                volume_24h=_dec(market.get("volume24hr")) or Decimal("0"),
                source_url=f"https://gamma-api.polymarket.com/markets/{market['id']}",
            )
        )
    return rows


def _kalshi_rows(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for market in markets:
        if market.get("market_type", "binary") != "binary":
            continue
        yes_bid, yes_ask = _dec(market.get("yes_bid_dollars")), _dec(market.get("yes_ask_dollars"))
        rows.append(
            dict(
                venue="kalshi",
                market_id=market["ticker"],
                event_id=f"kalshi:{market['event_ticker']}",
                event_title=market.get("title", ""),
                mutually_exclusive=None,  # Known only from the event; checked on demand.
                question=" ".join(filter(None, [market.get("title"), market.get("yes_sub_title")])),
                rules="\n".join(
                    filter(None, [market.get("rules_primary"), market.get("rules_secondary")])
                ),
                end_at=market.get("expected_expiration_time") or market.get("close_time"),
                yes_bid=yes_bid,
                yes_ask=yes_ask,
                yes_bid_size=_dec(market.get("yes_bid_size_fp")),
                yes_ask_size=_dec(market.get("yes_ask_size_fp")),
                volume_24h=_dec(market.get("volume_24h_fp")) or Decimal("0"),
                source_url=f"{KALSHI_API}/markets/{market['ticker']}",
            )
        )
    return rows


def _polymarket_window(start: datetime, end: datetime, pages: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(pages):
        params = urlencode(
            dict(
                active="true",
                closed="false",
                limit=100,
                offset=page * 100,
                end_date_min=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                end_date_max=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                order="volume24hr",
                ascending="false",
            )
        )
        markets = _get_json(f"https://gamma-api.polymarket.com/markets?{params}")
        rows.extend(_polymarket_rows(markets))
        if len(markets) < 100:
            break
    return rows


def _kalshi_window(start: datetime, end: datetime, pages: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = ""
    for _ in range(pages):
        params = urlencode(
            dict(
                status="open",
                limit=200,  # Rules text makes Kalshi pages heavy; keep each read short.
                cursor=cursor,
                mve_filter="exclude",
                min_close_ts=int(start.timestamp()),
                max_close_ts=int(end.timestamp()),
            )
        )
        payload = _get_json(f"{KALSHI_API}/markets?{params}")
        rows.extend(_kalshi_rows(payload["markets"]))
        cursor = payload.get("cursor", "")
        if not cursor:
            break
    return rows


def discover_markets(
    *, now: datetime | None = None, max_days: int = 365, pages: int = 2
) -> list[dict[str, Any]]:
    """List open binary markets from both venues, a few pages per horizon window.

    Windows and venues are independent requests, so they run concurrently.
    Any listing failure propagates: a partial universe is not a scan.
    """
    now = now or datetime.now(UTC)
    tasks = []
    for low, high in WINDOWS_HOURS:
        if low >= max_days * 24:
            break
        start, end = now + timedelta(hours=low), now + timedelta(hours=min(high, max_days * 24))
        tasks += [(_polymarket_window, start, end), (_kalshi_window, start, end)]
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        batches = list(pool.map(lambda task: task[0](task[1], task[2], pages), tasks))
    unique = {(row["venue"], row["market_id"]): row for batch in batches for row in batch}
    for row in unique.values():
        bid, ask = row["yes_bid"], row["yes_ask"]
        row["listing_mid"] = (
            (bid + ask) / 2 if bid is not None and ask is not None and 0 < bid <= ask < 1 else None
        )
    return list(unique.values())


def _attention(volume_24h: Decimal) -> Decimal:
    """1.0 for an unwatched market, falling slowly as daily volume grows."""
    return Decimal(str(round(1 / (1 + math.log10(1 + float(volume_24h) / 1000)), 6)))


def prerank(
    markets: list[dict[str, Any]],
    mandate: FundMandate,
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Score every eligible side from listing data before spending book requests."""
    now = now or datetime.now(UTC)
    sides, excluded = [], defaultdict(int)
    for market in markets:
        reason = None
        bid, ask = market["yes_bid"], market["yes_ask"]
        hours = _hours(market["end_at"], now)
        if PRICE_BET.search(market["question"]) or PRICE_BET.search(market["event_title"]):
            reason = "asset_price_bet_requires_reference_model"
        elif hours is None:
            reason = "missing_resolution_time"
        elif not 0 < hours <= mandate.scheduled_horizon_hours:
            reason = "outside_resolution_window"
        elif bid is None or ask is None or not 0 < bid <= ask < 1 or ask - bid > MAX_SPREAD:
            reason = "listing_has_no_usable_book"
        if reason:
            excluded[reason] += 1
            continue
        days = max(hours / 24, Decimal("0.25"))
        score = _attention(market["volume_24h"]) / days
        for side, side_ask, side_bid in (("YES", ask, bid), ("NO", 1 - bid, 1 - ask)):
            sides.append(
                {
                    **market,
                    "instrument_id": f"{market['venue']}:{market['market_id']}:{side}",
                    "side": side,
                    "indicative_ask": side_ask,
                    "indicative_bid": side_bid,
                    "hours_to_resolution": hours,
                    "score": score,
                }
            )
    sides.sort(key=lambda row: (row["score"], row["indicative_ask"]), reverse=True)
    return sides, dict(excluded)


def book_metrics(
    row: dict[str, Any], quote: Any, mandate: FundMandate, policy: TradingPolicy, gamma: Decimal
) -> dict[str, Any] | None:
    """Executable terms for one side, or None when the book cannot fill this fund."""
    if not quote.bids or not quote.asks:
        return None
    bid, ask = max(q.price for q in quote.bids), min(q.price for q in quote.asks)
    depth = sum(q.price * q.size for q in quote.asks if q.price == ask)
    if ask - bid > MAX_SPREAD or depth < policy.min_depth_usd:
        return None
    fee = execution_fee(mandate, quote, ask, Decimal("100")) / 100
    days = max(row["hours_to_resolution"] / 24, Decimal("0.01"))
    cost = ask + fee
    gain_if_wins = (1 - cost) / cost
    bias_p = favorite_bias_probability(quote.price, gamma)
    return {
        "instrument_id": row["instrument_id"],
        "venue": row["venue"],
        "market_id": row["market_id"],
        "event_id": row["event_id"],
        "event_title": row["event_title"],
        "question": row["question"],
        "rules": row["rules"][:1500],
        "end_at": row["end_at"],
        "hours_to_resolution": str(row["hours_to_resolution"]),
        "volume_24h": str(row["volume_24h"]),
        "score": str(row["score"]),
        "bid": str(bid),
        "ask": str(ask),
        "mid": str(quote.price),
        "spread": str(ask - bid),
        "best_ask_depth_usd": str(depth),
        "entry_fee_per_share": str(fee),
        "return_if_wins": str(round(gain_if_wins, 6)),
        "annualized_if_wins": str(round(gain_if_wins * 365 / days, 4)),
        "favorite_bias_p": str(bias_p),
        "favorite_bias_edge": str(round(bias_p - cost, 6)),
        "quote": quote.model_dump(mode="json"),
    }


def shortlist(
    markets: list[dict[str, Any]],
    router: MarketDataRouter,
    mandate: FundMandate,
    policy: TradingPolicy,
    *,
    now: datetime | None = None,
    limit: int = 25,
    max_books: int = 40,
    gamma: Decimal | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    gamma = gamma or policy.baseline_gamma
    sides, excluded = prerank(markets, mandate, now=now)
    attempted: list[str] = []
    for row in sides:
        market_key = f"{row['venue']}:{row['market_id']}"
        if market_key not in attempted and len(attempted) < max_books:
            attempted.append(market_key)
    chosen = [row for row in sides if f"{row['venue']}:{row['market_id']}" in attempted]
    quotes, failures = fetch_quotes(router, [row["instrument_id"] for row in chosen])
    candidates = []
    for row in chosen:
        quote = quotes.get(row["instrument_id"])
        if quote is None:
            continue
        metrics = book_metrics(row, quote, mandate, policy, gamma)
        if metrics is None:
            excluded["spread_or_depth"] = excluded.get("spread_or_depth", 0) + 1
            continue
        candidates.append(metrics)
    catalysts = sorted(
        (row for row in candidates if Decimal(row["hours_to_resolution"]) <= 48),
        key=lambda row: Decimal(row["hours_to_resolution"]),
    )
    return {
        "schema_version": "edgecraft.scan.v2",
        "paper_only": True,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "candidates": candidates[:limit],
        "catalysts": [
            {key: row[key] for key in ("instrument_id", "question", "end_at", "ask")}
            for row in catalysts[:20]
        ],
        "event_flags": event_flags(markets, mandate, now=now),
        "cross_venue_flags": cross_venue_flags(candidates),
        "failures": failures,
        "excluded": excluded,
        "coverage": {
            "listed_markets": len(markets),
            "eligible_sides": len(sides),
            "book_markets_attempted": len(attempted),
            "book_limit": max_books,
            "bounded": True,
        },
        "interpretation": "Rank favors soon-resolving, lightly traded contracts with enough "
        "depth to fill; it is research priority, not alpha. annualized_if_wins is the return "
        "only if the side settles at $1. favorite_bias_p applies the fitted favorite-longshot "
        "curve to the midpoint. Flags are unverified until the exact rules are read. Failed "
        "access is not evidence for a cash hold.",
    }


def _kalshi_exclusive(event_id: str) -> bool | None:
    try:
        event = _get_json(f"{KALSHI_API}/events/{event_id.split(':', 1)[1]}")["event"]
        return bool(event.get("mutually_exclusive"))
    except Exception:
        return None


def event_flags(
    markets: list[dict[str, Any]], mandate: FundMandate, *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Mutually exclusive outcomes whose YES bids sum above $1.

    If at most one outcome can win, buying NO on every listed outcome pays at
    least n - 1 for a cost of n - sum(YES bids): positive whenever the bids
    sum above 1 after fees, whether or not the list is exhaustive. Sums far
    above $1 are threshold ladders (cumulative strikes), not exclusive
    outcomes, so they are skipped without an event lookup.
    """
    now = now or datetime.now(UTC)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in markets:
        if (
            row["yes_bid"] is not None
            and row["yes_ask"] is not None
            and not PRICE_BET.search(row["question"])
        ):
            groups[row["event_id"]].append(row)
    candidates = {
        event_id: rows
        for event_id, rows in groups.items()
        if len(rows) >= 2
        and Decimal("1.01") < sum((row["yes_bid"] for row in rows), Decimal("0")) <= MAX_BASKET_SUM
    }
    unknown = [
        event_id for event_id, rows in candidates.items() if rows[0]["mutually_exclusive"] is None
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        looked_up = dict(zip(unknown, pool.map(_kalshi_exclusive, unknown), strict=True))
    flags = []
    for event_id, rows in candidates.items():
        exclusive = rows[0]["mutually_exclusive"]
        if exclusive is None:
            exclusive = looked_up.get(event_id)
        if not exclusive:
            continue
        bid_sum = sum((row["yes_bid"] for row in rows), Decimal("0"))
        hours = _hours(rows[0]["end_at"], now)
        flags.append(
            {
                "kind": "exclusive_no_basket",
                "event_id": event_id,
                "event_title": rows[0]["event_title"],
                "legs": [f"{row['venue']}:{row['market_id']}:NO" for row in rows],
                "yes_bid_sum": str(bid_sum),
                "listing_edge_per_basket": str(bid_sum - 1),
                "hours_to_resolution": str(hours) if hours is not None else None,
                "semantics_verified": False,
            }
        )
    flags.sort(key=lambda row: Decimal(row["listing_edge_per_basket"]), reverse=True)
    return flags[:20]


def cross_venue_flags(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Similar YES questions across venues whose books do not overlap."""
    flags = []
    yes = [row for row in candidates if row["instrument_id"].endswith(":YES")]
    for index, left in enumerate(yes):
        for right in yes[index + 1 :]:
            if left["venue"] == right["venue"]:
                continue
            similarity = SequenceMatcher(
                None, left["question"].lower(), right["question"].lower()
            ).ratio()
            gap = max(
                Decimal(left["bid"]) - Decimal(right["ask"]),
                Decimal(right["bid"]) - Decimal(left["ask"]),
            )
            if similarity >= 0.85 and gap > 0:
                flags.append(
                    {
                        "kind": "cross_venue_rule_review",
                        "instruments": [left["instrument_id"], right["instrument_id"]],
                        "raw_price_gap": str(gap),
                        "semantics_verified": False,
                    }
                )
    return flags


def scan_markets(
    router: MarketDataRouter,
    mandate: FundMandate,
    policy: TradingPolicy,
    *,
    pages: int = 2,
    limit: int = 25,
    max_books: int = 40,
    gamma: Decimal | None = None,
) -> dict[str, Any]:
    markets = discover_markets(pages=pages)  # Any venue listing failure is terminal.
    report = shortlist(
        markets, router, mandate, policy, limit=limit, max_books=max_books, gamma=gamma
    )
    if not report["candidates"] and report["failures"]:
        raise MarketDataError(
            "scanner could not obtain candidate books: " + str(report["failures"][:5])
        )
    return report
