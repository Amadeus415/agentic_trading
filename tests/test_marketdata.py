from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from edgecraft.marketdata import MarketDataRouter, advisory_difference_bps
from edgecraft.paper_fund import AssetClass, FundQuote


def _quote(price: str, observed_at: datetime) -> FundQuote:
    return FundQuote(
        quote_id=f"quote-{price}",
        instrument_id="AAPL",
        asset_class=AssetClass.STOCK,
        price=price,
        observed_at=observed_at,
        source_timestamp=observed_at,
        source_name="test",
        source_url="https://example.test/aapl",
    )


def test_cache_returns_latest_quote_at_or_before_cutoff(tmp_path) -> None:
    router = MarketDataRouter(cache_dir=tmp_path)
    first_at = datetime(2026, 9, 3, 16, tzinfo=UTC)
    second_at = first_at + timedelta(minutes=5)
    router._cache(_quote("100", first_at))
    router._cache(_quote("101", second_at))

    selected = router.latest_cached_quote("AAPL", at_or_before=first_at + timedelta(minutes=1))

    assert selected.price == Decimal("100")


def test_advisory_difference_is_measured_in_basis_points() -> None:
    now = datetime(2026, 9, 3, 16, tzinfo=UTC)

    assert advisory_difference_bps(_quote("101", now), _quote("100", now)) == Decimal("100")
