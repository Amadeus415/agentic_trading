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
            return {
                "requestId": f"request-{query_number}",
                "query": body["query"],
                "results": [
                    {
                        "id": f"result-{query_number}",
                        "url": f"https://source{query_number}.example/story",
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
        fetch_pages=2,
    )
    service = ExternalContextService(
        policy,
        browserbase=BrowserbaseClient("test-key", transport=transport),
        bluesky=BlueskyClient(transport=transport),
        sec=SecEdgarClient(transport=transport),
        cache_directory=tmp_path,
    )

    snapshot = service.collect(["vti", "vxus"], now=NOW)

    assert snapshot.complete
    assert snapshot.fresh_source_count == 4
    assert {source.channel for source in snapshot.sources} == {"web", "social", "regulatory"}
    assert any(source.excerpt == "Current sourced facts." for source in snapshot.sources)
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
