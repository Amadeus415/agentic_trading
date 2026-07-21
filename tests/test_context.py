from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from edgecraft.autonomy_models import Mandate
from edgecraft.context import (
    BlueskyClient,
    BrowserbaseClient,
    ContextSource,
    ExternalContextService,
    SecEdgarClient,
    WebContextPolicy,
    browserbase_api_key,
)

NOW = datetime(2026, 7, 20, 22, 0, tzinfo=UTC)


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method, url, headers, body, timeout):
        del headers, timeout
        self.calls.append((method, url, body))
        if url.endswith("/v1/search"):
            query_number = sum(call[1].endswith("/v1/search") for call in self.calls)
            is_social = "site:stocktwits.com" in body["query"]
            return {
                "requestId": f"request-{query_number}",
                "query": body["query"],
                "results": [
                    {
                        "id": f"result-{query_number}",
                        "url": (
                            "https://stocktwits.com/symbol/VTI"
                            if is_social
                            else (
                                "https://www.sec.gov/Archives/edgar/data/1/filing.htm"
                                if "site:sec.gov" in body["query"]
                                else f"https://source{query_number}.example/story"
                            )
                        ),
                        "title": f"Current market source {query_number}",
                        "publishedDate": "2026-07-20T20:00:00Z",
                    },
                    {
                        "id": f"old-{query_number}",
                        "url": f"https://archive{query_number}.example/story",
                        "title": "Older background source",
                        "publishedDate": "2025-01-01T00:00:00Z",
                    },
                ],
            }
        if url.endswith("/v1/fetch"):
            return {
                "statusCode": 200,
                "content": "<html><script>ignore me</script><body>Current sourced facts.</body></html>",
                "contentType": "text/html",
                "encoding": "utf-8",
            }
        if "searchPosts" in url:
            return {
                "posts": [
                    {
                        "uri": "at://did:plc:test/app.bsky.feed.post/post123",
                        "author": {"handle": "markets.example"},
                        "record": {
                            "text": "Public discussion of VTI and VXUS.",
                            "createdAt": "2026-07-20T21:00:00Z",
                        },
                        "likeCount": 4,
                        "repostCount": 2,
                        "replyCount": 1,
                    }
                ]
            }
        if "data.sec.gov/submissions" in url:
            return {
                "filings": {
                    "recent": {
                        "form": ["8-K"],
                        "acceptanceDateTime": ["2026-07-20T19:00:00Z"],
                        "filingDate": ["2026-07-20"],
                        "accessionNumber": ["0000000001-26-000001"],
                        "primaryDocument": ["filing.htm"],
                    }
                }
            }
        raise AssertionError(f"unexpected request: {method} {url}")


def test_context_collection_is_diverse_fresh_cached_and_bounded(tmp_path):
    transport = FakeTransport()
    policy = WebContextPolicy(
        min_sources=4,
        min_fresh_sources=3,
        sec_ciks={"VTI": "1"},
        sec_user_agent="Edgecraft tests test@example.com",
        fetch_pages=2,
    )
    service = ExternalContextService(
        policy,
        browserbase=BrowserbaseClient("test-key", transport=transport),
        bluesky=BlueskyClient(transport=transport),
        sec=SecEdgarClient(user_agent="Edgecraft tests test@example.com", transport=transport),
        cache_directory=tmp_path,
    )

    snapshot = service.collect(["vti", "vxus"], now=NOW)

    assert snapshot.complete
    assert snapshot.fresh_source_count >= 4
    assert {source.channel for source in snapshot.sources} == {"web", "social", "regulatory"}
    assert any(source.excerpt == "Current sourced facts." for source in snapshot.sources)
    fetched_source = next(
        source for source in snapshot.sources if source.metadata.get("content_sha256")
    )
    assert fetched_source.metadata["discovery_query"] in snapshot.queries
    assert len(fetched_source.metadata["content_sha256"]) == 64
    filing = next(source for source in snapshot.sources if source.metadata.get("form") == "8-K")
    assert filing.metadata["form"] == "8-K"
    assert filing.metadata["accession_number"] == "0000000001-26-000001"
    assert all(len(query) <= 200 for query in snapshot.queries)
    call_count = len(transport.calls)

    cached = service.collect(["VTI", "VXUS"], now=NOW)
    assert cached.cache_hit
    assert len(transport.calls) == call_count
    cache_payload = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert "test-key" not in json.dumps(cache_payload)


def test_context_source_rejects_private_network_urls():
    with pytest.raises(ValueError, match="private or reserved"):
        ContextSource(
            source_id="bad",
            channel="web",
            title="bad",
            url="https://127.0.0.1/secrets",
            retrieved_at=NOW,
        )


def test_large_universe_respects_query_and_social_budgets():
    transport = FakeTransport()
    policy = WebContextPolicy(
        symbols_per_query=4,
        max_search_queries=6,
        social_results=3,
        fetch_pages=0,
        max_total_sources=20,
        min_sources=1,
        min_web_sources=1,
        min_fresh_sources=1,
    )
    service = ExternalContextService(
        policy,
        browserbase=BrowserbaseClient("test-key", transport=transport),
        bluesky=BlueskyClient(transport=transport),
    )
    symbols = [f"S{index:02d}" for index in range(25)]

    snapshot = service.collect(symbols, now=NOW)

    search_calls = [call for call in transport.calls if call[1].endswith("/v1/search")]
    social_calls = [call for call in transport.calls if "searchPosts" in call[1]]
    assert len(search_calls) == 6
    assert len(snapshot.queries) == 6
    assert all(any(symbol in query for query in snapshot.queries) for symbol in symbols)
    assert len(social_calls) <= 3
    assert sum(source.channel == "social" for source in snapshot.sources) <= 3
    assert len(snapshot.sources) <= 20


def test_browserbase_key_file_must_be_private(tmp_path, monkeypatch):
    key_file = tmp_path / "browserbase-key"
    key_file.write_text("test-secret\n")
    key_file.chmod(0o600)
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    monkeypatch.setenv("BROWSERBASE_API_KEY_FILE", str(key_file))
    assert browserbase_api_key() == "test-secret"

    key_file.chmod(0o644)
    with pytest.raises(RuntimeError, match="must not be group/world accessible"):
        browserbase_api_key()


def test_live_mandate_requires_external_context_policy():
    with pytest.raises(ValueError, match="external_context_path"):
        Mandate(
            mandate_id="live_context_test",
            goal="Invest a bounded weekly contribution into diversified index funds.",
            mode="live",
            weekly_budget="10",
            universe=["VTI"],
            strategic_weights={"VTI": "1"},
            policy_path="policy.json",
        )
