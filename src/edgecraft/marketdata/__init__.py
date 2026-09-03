"""Small public, read-only market-data adapters with an auditable disk cache."""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from edgecraft.paper_fund import AssetClass, BookLevel, FundQuote, QuoteStatus

USER_AGENT = "Edgecraft-paper-fund/1.0 public-market-data"


class MarketDataError(RuntimeError):
    """A public quote could not be fetched or parsed."""


class QuoteProvider(Protocol):
    def quote(self, instrument_id: str, *, observed_at: datetime | None = None) -> FundQuote: ...


def _get_json(url: str) -> Any:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise MarketDataError("market-data URLs must use HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _get_text(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise MarketDataError("market-data URLs must use HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
        return response.read().decode("utf-8")


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
class CoinbaseProvider:
    def quote(self, instrument_id: str, *, observed_at: datetime | None = None) -> FundQuote:
        now = _now(observed_at)
        url = (
            f"https://api.exchange.coinbase.com/products/{urllib.parse.quote(instrument_id)}/ticker"
        )
        payload = _get_json(url)
        timestamp = datetime.fromisoformat(str(payload["time"]).replace("Z", "+00:00"))
        return _quote(
            instrument_id=instrument_id,
            asset_class=AssetClass.CRYPTO,
            price=Decimal(str(payload["price"])),
            source_timestamp=timestamp.astimezone(UTC),
            observed_at=now,
            source_name="Coinbase Exchange public ticker",
            source_url=url,
        )


@dataclass(frozen=True)
class BinanceProvider:
    def quote(self, instrument_id: str, *, observed_at: datetime | None = None) -> FundQuote:
        now = _now(observed_at)
        base, _, quote_currency = instrument_id.partition("-")
        symbol = f"{base}{'USDT' if quote_currency == 'USD' else quote_currency}"
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={urllib.parse.quote(symbol)}"
        payload = _get_json(url)
        return _quote(
            instrument_id=instrument_id,
            asset_class=AssetClass.CRYPTO,
            price=Decimal(str(payload["price"])),
            source_timestamp=now,
            observed_at=now,
            source_name="Binance public ticker",
            source_url=url,
        )


@dataclass(frozen=True)
class StooqProvider:
    def quote(self, instrument_id: str, *, observed_at: datetime | None = None) -> FundQuote:
        now = _now(observed_at)
        symbol = urllib.parse.quote(f"{instrument_id.lower()}.us")
        url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
        rows = list(csv.DictReader(io.StringIO(_get_text(url))))
        if not rows or not rows[0].get("Close") or rows[0]["Close"] == "N/D":
            raise MarketDataError(f"Stooq returned no quote for {instrument_id}")
        row = rows[0]
        timestamp = datetime.fromisoformat(f"{row['Date']}T{row['Time']}").replace(tzinfo=UTC)
        return _quote(
            instrument_id=instrument_id,
            asset_class=AssetClass.STOCK,
            price=Decimal(row["Close"]),
            source_timestamp=timestamp,
            observed_at=now,
            source_name="Stooq public quote",
            source_url=url,
        )


@dataclass(frozen=True)
class YahooProvider:
    def quote(self, instrument_id: str, *, observed_at: datetime | None = None) -> FundQuote:
        now = _now(observed_at)
        symbol = urllib.parse.quote(instrument_id)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
        payload = _get_json(url)["chart"]["result"][0]
        timestamps = payload["timestamp"]
        closes = payload["indicators"]["quote"][0]["close"]
        observations = [
            (stamp, price) for stamp, price in zip(timestamps, closes, strict=True) if price
        ]
        if not observations:
            raise MarketDataError(f"Yahoo returned no quote for {instrument_id}")
        stamp, price = observations[-1]
        return _quote(
            instrument_id=instrument_id,
            asset_class=AssetClass.STOCK,
            price=Decimal(str(price)),
            source_timestamp=datetime.fromtimestamp(stamp, UTC),
            observed_at=now,
            source_name="Yahoo Finance chart API",
            source_url=url,
        )


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
        outcomes = (
            json.loads(market["outcomes"])
            if isinstance(market["outcomes"], str)
            else market["outcomes"]
        )
        tokens = (
            json.loads(market["clobTokenIds"])
            if isinstance(market["clobTokenIds"], str)
            else market["clobTokenIds"]
        )
        token_id = tokens[outcomes.index(outcome.title())]
        closed = bool(market.get("closed"))
        prices = (
            json.loads(market["outcomePrices"])
            if isinstance(market.get("outcomePrices"), str)
            else market.get("outcomePrices", [])
        )
        bids: tuple[BookLevel, ...] = ()
        asks: tuple[BookLevel, ...] = ()
        if closed and prices:
            price = Decimal(str(prices[outcomes.index(outcome.title())]))
            status = (
                QuoteStatus.SETTLED if price in {Decimal("0"), Decimal("1")} else QuoteStatus.OPEN
            )
            source_url = gamma_url
        else:
            source_url = f"https://clob.polymarket.com/book?token_id={token_id}"
            book = _get_json(source_url)
            bids = _book_levels(book.get("bids"))
            asks = _book_levels(book.get("asks"))
            mid = _get_json(f"https://clob.polymarket.com/price?token_id={token_id}&side=buy")
            price = Decimal(str(mid["price"]))
            status = QuoteStatus.OPEN
        return _quote(
            instrument_id=instrument_id,
            asset_class=AssetClass.PREDICTION,
            price=price,
            source_timestamp=now,
            observed_at=now,
            source_name="Polymarket CLOB public API",
            source_url=source_url,
            status=status,
            bids=bids,
            asks=asks,
        )


@dataclass
class MarketDataRouter:
    cache_dir: Path = Path("state/marks")

    def quote(self, instrument_id: str, asset_class: AssetClass) -> FundQuote:
        providers: list[QuoteProvider]
        if asset_class is AssetClass.CRYPTO:
            providers = [CoinbaseProvider(), BinanceProvider()]
        elif asset_class is AssetClass.STOCK:
            providers = [YahooProvider(), StooqProvider()]
        elif asset_class is AssetClass.PREDICTION:
            providers = [PolymarketProvider()]
        else:
            raise MarketDataError(f"unsupported asset class {asset_class}")
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

    def history(
        self,
        instrument_id: str,
        asset_class: AssetClass,
        *,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, Decimal]]:
        if asset_class is AssetClass.STOCK:
            symbol = urllib.parse.quote(instrument_id)
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                f"?interval=1d&period1={int(start.timestamp())}&period2={int(end.timestamp())}"
            )
            payload = _get_json(url)["chart"]["result"][0]
            closes = payload["indicators"]["quote"][0]["close"]
            rows = [
                (datetime.fromtimestamp(stamp, UTC), Decimal(str(price)))
                for stamp, price in zip(payload["timestamp"], closes, strict=True)
                if price is not None
            ]
        elif asset_class is AssetClass.CRYPTO:
            product = urllib.parse.quote(instrument_id)
            url = (
                f"https://api.exchange.coinbase.com/products/{product}/candles?granularity=86400"
                f"&start={urllib.parse.quote(start.isoformat())}&end={urllib.parse.quote(end.isoformat())}"
            )
            rows = [
                (datetime.fromtimestamp(item[0], UTC), Decimal(str(item[4])))
                for item in _get_json(url)
            ]
        elif asset_class is AssetClass.PREDICTION:
            match = re.fullmatch(r"polymarket:(\d+):(YES|NO)", instrument_id)
            if not match:
                raise MarketDataError("invalid Polymarket instrument ID")
            market_id, outcome = match.groups()
            market = _get_json(f"https://gamma-api.polymarket.com/markets/{market_id}")
            outcomes = (
                json.loads(market["outcomes"])
                if isinstance(market["outcomes"], str)
                else market["outcomes"]
            )
            tokens = (
                json.loads(market["clobTokenIds"])
                if isinstance(market["clobTokenIds"], str)
                else market["clobTokenIds"]
            )
            token = tokens[outcomes.index(outcome.title())]
            url = f"https://clob.polymarket.com/prices-history?market={token}&interval=max&fidelity=60"
            rows = [
                (datetime.fromtimestamp(item["t"], UTC), Decimal(str(item["p"])))
                for item in _get_json(url).get("history", [])
                if start.timestamp() <= item["t"] <= end.timestamp()
            ]
        else:
            raise MarketDataError(f"unsupported asset class {asset_class}")
        rows.sort(key=lambda item: item[0])
        self._cache_history(instrument_id, rows, start, end)
        return rows

    def _cache_history(
        self,
        instrument_id: str,
        rows: list[tuple[datetime, Decimal]],
        start: datetime,
        end: datetime,
    ) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", instrument_id)
        path = self.cache_dir / f"history-{safe}-{start:%Y%m%d}-{end:%Y%m%d}.json"
        payload = {
            "instrument_id": instrument_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "observations": [
                {"observed_at": at.isoformat(), "price": str(price)} for at, price in rows
            ],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def advisory_difference_bps(advisory: FundQuote, authoritative: FundQuote) -> Decimal:
    if authoritative.price == 0:
        return Decimal("0") if advisory.price == 0 else Decimal("Infinity")
    return abs(advisory.price - authoritative.price) / authoritative.price * Decimal("10000")
