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


def test_a_stalled_read_is_retried_once_but_access_errors_are_not(monkeypatch) -> None:
    import io
    import urllib.error

    import pytest

    from edgecraft import marketdata

    calls = []

    def stalled_then_ok(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise TimeoutError("The read operation timed out")
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(marketdata.urllib.request, "urlopen", stalled_then_ok)
    assert marketdata._get_json("https://example.test/a") == {"ok": True}
    assert len(calls) == 2

    def denied(request, timeout):
        calls.append(request.full_url)
        raise urllib.error.URLError("certificate verify failed")

    calls.clear()
    monkeypatch.setattr(marketdata.urllib.request, "urlopen", denied)
    with pytest.raises(urllib.error.URLError):
        marketdata._get_json("https://example.test/b")
    assert len(calls) == 1
