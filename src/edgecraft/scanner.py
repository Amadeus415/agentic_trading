"""Bounded public discovery; rank research opportunities, never fabricate alpha."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from difflib import SequenceMatcher
from itertools import zip_longest
from typing import Any
from urllib.parse import urlencode

from edgecraft.marketdata import KALSHI_API, MarketDataError, MarketDataRouter, _get_json
from edgecraft.paper_fund import AssetClass, FundMandate, execution_fee

# Exclude price-direction speculation until a separately validated reference
# model exists. This conservative screen is followed by semantic rule review.
PRICE_BET = re.compile(r"\b(bitcoin|btc|ethereum|eth|stock|share price|s&p|nasdaq|crypto)\b", re.I)


def discover_markets(*, pages: int = 2) -> list[dict[str, Any]]:
    rows = []
    cursor = ""
    for page in range(pages):
        params = urlencode(
            dict(
                active="true",
                closed="false",
                limit=100,
                offset=page * 100,
                order="volume24hr",
                ascending="false",
            )
        )
        markets = _get_json(f"https://gamma-api.polymarket.com/markets?{params}")
        for market in markets:
            rows.append(
                dict(
                    venue="polymarket",
                    market_id=str(market["id"]),
                    question=market.get("question", ""),
                    rules=market.get("description", ""),
                    end_at=market.get("endDate"),
                    source_url=f"https://gamma-api.polymarket.com/markets/{market['id']}",
                )
            )
        if len(markets) < 100:
            break
    for _ in range(pages):
        params = urlencode(dict(status="open", limit=100, cursor=cursor, mve_filter="exclude"))
        payload = _get_json(f"{KALSHI_API}/markets?{params}")
        for market in payload["markets"]:
            rows.append(
                dict(
                    venue="kalshi",
                    market_id=market["ticker"],
                    question=market.get("title", ""),
                    rules="\n".join(
                        filter(None, [market.get("rules_primary"), market.get("rules_secondary")])
                    ),
                    end_at=market.get("expected_expiration_time") or market.get("close_time"),
                    source_url=f"{KALSHI_API}/markets/{market['ticker']}",
                )
            )
        cursor = payload.get("cursor", "")
        if not cursor:
            break
    return rows


def shortlist(
    markets: list[dict[str, Any]],
    router: MarketDataRouter,
    mandate: FundMandate,
    *,
    now: datetime | None = None,
    limit: int = 20,
    max_books: int = 40,
) -> dict:
    moment = now or datetime.now(UTC)
    candidates, failures, excluded = [], [], []
    books = 0
    venues = sorted({row["venue"] for row in markets})
    interleaved = [
        row
        for group in zip_longest(
            *[[row for row in markets if row["venue"] == venue] for venue in venues]
        )
        for row in group
        if row is not None
    ]
    for market in interleaved:
        reason = None
        if PRICE_BET.search(market["question"]):
            reason = "asset_price_bet_requires_reference_model"
        try:
            end = datetime.fromisoformat(str(market["end_at"]).replace("Z", "+00:00"))
            hours = Decimal(str((end - moment).total_seconds() / 3600))
            if not 0 < hours <= mandate.scheduled_horizon_hours:
                reason = reason or "outside_resolution_window"
        except (ValueError, TypeError):
            reason = reason or "missing_resolution_time"
        if reason:
            excluded.append({"market_id": market["market_id"], "reason": reason})
            continue
        if books >= max_books:
            continue
        books += 1
        for outcome in ("YES", "NO"):
            instrument = f"{market['venue']}:{market['market_id']}:{outcome}"
            try:
                quote = router.quote(instrument, AssetClass.PREDICTION)
                bid, ask = max(q.price for q in quote.bids), min(q.price for q in quote.asks)
                spread = ask - bid
                depth = sum(q.price * q.size for q in quote.asks if q.price == ask)
                if spread > Decimal("0.10") or depth < Decimal("10"):
                    excluded.append({"instrument_id": instrument, "reason": "spread_or_depth"})
                    continue
                fee = execution_fee(mandate, quote, ask, Decimal("100")) / 100
                candidates.append(
                    {
                        **market,
                        "instrument_id": instrument,
                        "hours_to_resolution": str(hours),
                        "bid": str(bid),
                        "ask": str(ask),
                        "spread": str(spread),
                        "best_ask_depth_usd": str(depth),
                        "entry_fee_per_share": str(fee),
                        "research_rank": str(depth / (spread + Decimal("0.01"))),
                        "quote": quote.model_dump(mode="json"),
                    }
                )
            except Exception as exc:
                failures.append({"instrument_id": instrument, "detail": str(exc)})
    candidates.sort(key=lambda row: Decimal(row["research_rank"]), reverse=True)
    flags = consistency_flags(candidates)
    return {
        "schema_version": "edgecraft.scan.v1",
        "paper_only": True,
        "candidates": candidates[:limit],
        "consistency_flags": flags,
        "failures": failures,
        "excluded": excluded,
        "coverage": {
            "listed_markets": len(markets),
            "book_markets_attempted": books,
            "book_limit": max_books,
            "bounded": True,
        },
        "interpretation": "Rank measures displayed liquidity versus spread, not expected alpha. "
        "Rules and evidence require research. Flags are unverified comparisons, "
        "not executable arbitrage. Failed access is not evidence for a cash hold.",
    }


def consistency_flags(candidates: list[dict]) -> list[dict]:
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
    groups: dict[str, list[dict]] = {}
    for row in candidates:
        groups.setdefault(row["instrument_id"].rsplit(":", 1)[0], []).append(row)
    for group in groups.values():
        if len(group) != 2:
            continue
        cost = sum(
            (Decimal(r["ask"]) + Decimal(r["entry_fee_per_share"]) for r in group), Decimal(0)
        )
        if cost < 1:
            flags.append(
                {
                    "kind": "complementary_outcomes",
                    "instruments": [r["instrument_id"] for r in group],
                    "cost_per_pair": str(cost),
                    "semantics_verified": False,
                }
            )
    return flags


def scan_markets(
    router: MarketDataRouter,
    mandate: FundMandate,
    *,
    pages: int = 2,
    limit: int = 20,
    max_books: int = 40,
) -> dict:
    markets = discover_markets(pages=pages)  # Any venue listing failure is terminal.
    report = shortlist(markets, router, mandate, limit=limit, max_books=max_books)
    if not report["candidates"] and report["failures"]:
        raise MarketDataError(
            "scanner could not obtain candidate books: " + str(report["failures"])
        )
    return report
