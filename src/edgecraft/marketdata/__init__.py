"""Small public, read-only market-data adapters with an auditable disk cache."""

from __future__ import annotations

import functools
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from edgecraft.paper_fund import AssetClass, BookLevel, FundQuote, QuoteStatus

USER_AGENT = "Edgecraft-paper-fund/2.0 public-market-data"


class MarketDataError(RuntimeError):
    """A public quote could not be fetched or parsed."""


class QuoteProvider(Protocol):
    def quote(self, instrument_id: str, *, observed_at: datetime | None = None) -> FundQuote: ...


def _timed_out(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or (
        isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)
    )


def _get_json(url: str, *, attempts: int = 2) -> Any:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise MarketDataError("market-data URLs must use HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            # Retry only a stalled read; HTTP, TLS, and access errors fail closed at once.
            if attempt == attempts or not _timed_out(exc):
                raise
    raise AssertionError("unreachable")


def _now(value: datetime | None) -> datetime:
    return (value or datetime.now(UTC)).astimezone(UTC)


def _quote(
    *,
    instrument_id: str,
    asset_class: AssetClass,
    price: Decimal,
    source_timestamp: datetime,
    observed_at: datetime,
    source_name: str,
    source_url: str,
    status: QuoteStatus = QuoteStatus.OPEN,
    bids: tuple[BookLevel, ...] = (),
    asks: tuple[BookLevel, ...] = (),
    fee_rate: Decimal | None = None,
    fee_exponent: int | None = None,
    fee_quantum: Decimal | None = None,
) -> FundQuote:
    return FundQuote(
        quote_id=f"code-{uuid.uuid4()}",
        instrument_id=instrument_id,
        asset_class=asset_class,
        price=price,
        observed_at=observed_at,
        source_timestamp=source_timestamp,
        source_name=source_name,
        source_url=source_url,
        status=status,
        bids=bids,
        asks=asks,
        fee_rate=fee_rate,
        fee_exponent=fee_exponent,
        fee_quantum=fee_quantum,
    )


def _book_levels(rows: Any) -> tuple[BookLevel, ...]:
    levels: list[BookLevel] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        price = row.get("price")
        size = row.get("size")
        if price is None or size is None:
            continue
        try:
            level = BookLevel(price=Decimal(str(price)), size=Decimal(str(size)))
        except Exception:
            continue
        levels.append(level)
    return tuple(levels)


@dataclass(frozen=True)
class PolymarketProvider:
    def quote(self, instrument_id: str, *, observed_at: datetime | None = None) -> FundQuote:
        now = _now(observed_at)
        match = re.fullmatch(r"polymarket:(\d+):(YES|NO)", instrument_id)
        if not match:
            raise MarketDataError("Polymarket IDs must be polymarket:<market-id>:YES|NO")
        market_id, outcome = match.groups()
        gamma_url = f"https://gamma-api.polymarket.com/markets/{market_id}"
        market = _get_json(gamma_url)
        outcomes = [str(label).upper() for label in _array(market["outcomes"])]
        if set(outcomes) != {"YES", "NO"} or len(outcomes) != 2:
            raise MarketDataError("only binary YES/NO markets are supported")
        closed = bool(market.get("closed"))
        prices = (
            json.loads(market["outcomePrices"])
            if isinstance(market.get("outcomePrices"), str)
            else market.get("outcomePrices", [])
        )
        bids: tuple[BookLevel, ...] = ()
        asks: tuple[BookLevel, ...] = ()
        fee_rate, exponent = None, None
        source_timestamp = now
        if closed and prices:
            if market.get("umaResolutionStatus") != "resolved":
                raise MarketDataError("closed Polymarket market is not confirmed resolved")
            price = Decimal(str(prices[outcomes.index(outcome)]))
            status = (
                QuoteStatus.SETTLED if price in {Decimal("0"), Decimal("1")} else QuoteStatus.OPEN
            )
            source_url = gamma_url
        else:
            version = market.get("version", "v1")
            if version not in ("v1", "v2"):
                raise MarketDataError("unsupported Polymarket protocol")
            tokens = _array(market["positionIds"] if version == "v2" else market["clobTokenIds"])
            token_id = tokens[outcomes.index(outcome)]
            fee_rate, exponent = _polymarket_fees(market)
            source_url = f"https://clob.polymarket.com/book?token_id={token_id}"
            if not market.get("acceptingOrders"):
                raise MarketDataError("Polymarket market is not accepting orders")
            book = _get_json(source_url)
            bids = _book_levels(book.get("bids"))
            asks = _book_levels(book.get("asks"))
            price = book_mid(bids, asks)
            if book.get("timestamp"):
                source_timestamp = datetime.fromtimestamp(float(book["timestamp"]) / 1000, UTC)
            status = QuoteStatus.OPEN
        return _quote(
            instrument_id=instrument_id,
            asset_class=AssetClass.PREDICTION,
            price=price,
            source_timestamp=source_timestamp,
            observed_at=now,
            source_name="Polymarket CLOB public API",
            source_url=source_url,
            status=status,
            bids=bids,
            asks=asks,
            fee_rate=fee_rate,
            fee_exponent=exponent,
            fee_quantum=Decimal("0.00001"),
        )


def _array(value: Any) -> list:
    return json.loads(value) if isinstance(value, str) else value


def book_mid(bids: tuple[BookLevel, ...], asks: tuple[BookLevel, ...]) -> Decimal:
    if not bids or not asks:
        raise MarketDataError("a two-sided book is required")
    bid = max(level.price for level in bids)
    ask = min(level.price for level in asks)
    if not Decimal("0") < bid <= ask < Decimal("1"):
        raise MarketDataError("crossed or invalid prediction book")
    return (bid + ask) / 2


def _polymarket_fees(market: dict) -> tuple[Decimal, int]:
    if market.get("feesEnabled") is False:
        return Decimal("0"), 1
    schedule = market.get("feeSchedule") or {}
    if market.get("feesEnabled") is not True or "rate" not in schedule:
        raise MarketDataError("Polymarket fee schedule unavailable")
    exponent = schedule.get("exponent")
    if exponent not in (1, 2):
        raise MarketDataError("unsupported Polymarket fee exponent")
    return Decimal(str(schedule["rate"])), int(exponent)


# Kalshi's documented production host; it serves every market category.
KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"


@functools.lru_cache(maxsize=512)
def _kalshi_series(series_ticker: str) -> dict[str, Any]:
    """Fee schedules are static within one run; fetch each series once."""
    return _get_json(f"{KALSHI_API}/series/{urllib.parse.quote(series_ticker, safe='')}")["series"]


@dataclass(frozen=True)
class KalshiProvider:
    def quote(self, instrument_id: str, *, observed_at: datetime | None = None) -> FundQuote:
        match = re.fullmatch(r"kalshi:([A-Za-z0-9_.-]+):(YES|NO)", instrument_id)
        if not match:
            raise MarketDataError("Kalshi IDs must be kalshi:<ticker>:YES|NO")
        ticker, outcome = match.groups()
        url = f"{KALSHI_API}/markets/{urllib.parse.quote(ticker, safe='')}"
        market = _get_json(url)["market"]
        now = _now(observed_at)
        if market.get("status") == "settled" and market.get("result") in ("yes", "no"):
            return _quote(
                instrument_id=instrument_id,
                asset_class=AssetClass.PREDICTION,
                price=Decimal(int(market["result"].upper() == outcome)),
                source_timestamp=now,
                observed_at=now,
                source_name="Kalshi public API",
                source_url=url,
                status=QuoteStatus.SETTLED,
            )
        if market.get("status") != "active":
            raise MarketDataError("Kalshi market is not active or finally settled")
        series_ticker = market.get("series_ticker") or str(market["event_ticker"]).split("-")[0]
        series = _kalshi_series(series_ticker)
        if (
            series.get("fee_type") not in {"quadratic", "quadratic_with_maker_fees"}
            or series.get("fee_multiplier") is None
        ):
            raise MarketDataError("unsupported or missing Kalshi fee schedule")
        book_url = url + "/orderbook"
        book = _get_json(book_url)["orderbook_fp"]
        side, other = ("yes", "no") if outcome == "YES" else ("no", "yes")
        bids = tuple(BookLevel(price=p, size=q) for p, q in book.get(side + "_dollars", []))
        asks = tuple(
            BookLevel(price=1 - Decimal(p), size=q) for p, q in book.get(other + "_dollars", [])
        )
        return _quote(
            instrument_id=instrument_id,
            asset_class=AssetClass.PREDICTION,
            price=book_mid(bids, asks),
            source_timestamp=now,
            observed_at=now,
            source_name="Kalshi public API",
            source_url=book_url,
            bids=bids,
            asks=asks,
            fee_rate=Decimal("0.07") * Decimal(str(series["fee_multiplier"])),
            fee_exponent=1,
            fee_quantum=Decimal("0.01"),
        )


@dataclass
class MarketDataRouter:
    cache_dir: Path = Path("state/marks")

    def quote(self, instrument_id: str, asset_class: AssetClass) -> FundQuote:
        providers: list[QuoteProvider]
        if asset_class is not AssetClass.PREDICTION:
            raise MarketDataError("stock and crypto trading were retired in v2")
        if instrument_id.startswith("polymarket:"):
            providers = [PolymarketProvider()]
        elif instrument_id.startswith("kalshi:"):
            providers = [KalshiProvider()]
        else:
            raise MarketDataError("prediction instrument must name Polymarket or Kalshi")
        errors: list[str] = []
        for provider in providers:
            try:
                quote = provider.quote(instrument_id)
                self._cache(quote)
                return quote
            except Exception as exc:
                errors.append(f"{type(provider).__name__}: {exc}")
        raise MarketDataError(
            f"all quote providers failed for {instrument_id}: {'; '.join(errors)}"
        )

    def _cache(self, quote: FundQuote) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", quote.instrument_id)
        stamp = quote.observed_at.strftime("%Y%m%dT%H%M%S%fZ")
        path = self.cache_dir / f"{safe}-{stamp}.json"
        path.write_text(quote.model_dump_json(indent=2) + "\n", encoding="utf-8")

    def latest_cached_quote(
        self,
        instrument_id: str,
        *,
        at_or_before: datetime | None = None,
    ) -> FundQuote:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", instrument_id)
        candidates: list[FundQuote] = []
        for path in self.cache_dir.glob(f"{safe}-*.json"):
            try:
                quote = FundQuote.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if at_or_before is None or quote.observed_at <= at_or_before.astimezone(UTC):
                candidates.append(quote)
        if not candidates:
            raise MarketDataError(f"no code-owned cached quote for {instrument_id}")
        return max(candidates, key=lambda quote: quote.observed_at)


def fetch_quotes(
    router: MarketDataRouter, instrument_ids: list[str], *, workers: int = 8
) -> tuple[dict[str, FundQuote], list[dict[str, str]]]:
    """Fetch many prediction quotes concurrently; each request is latency-bound."""
    from concurrent.futures import ThreadPoolExecutor

    unique = list(dict.fromkeys(instrument_ids))

    def one(instrument_id: str) -> FundQuote | Exception:
        try:
            return router.quote(instrument_id, AssetClass.PREDICTION)
        except Exception as exc:
            return exc

    quotes: dict[str, FundQuote] = {}
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for instrument_id, result in zip(unique, pool.map(one, unique), strict=True):
            if isinstance(result, Exception):
                failures.append({"instrument_id": instrument_id, "detail": str(result)[:300]})
            else:
                quotes[instrument_id] = result
    return quotes, failures


def advisory_difference_bps(advisory: FundQuote, authoritative: FundQuote) -> Decimal:
    if authoritative.price == 0:
        return Decimal("0") if advisory.price == 0 else Decimal("Infinity")
    return abs(advisory.price - authoritative.price) / authoritative.price * Decimal("10000")
