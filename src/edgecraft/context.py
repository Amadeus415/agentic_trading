from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, field_validator, model_validator

JsonTransport = Callable[[str, str, dict[str, str], dict[str, Any] | None, float], dict[str, Any]]


class ContextUnavailable(RuntimeError):
    """Raised when required external context cannot be collected safely."""


class WebContextPolicy(BaseModel):
    schema_version: str = "edgecraft.web-context-policy.v1"
    provider: Literal["browserbase"] = "browserbase"
    lookback_hours: int = Field(168, ge=1, le=720)
    cache_ttl_minutes: int = Field(30, ge=0, le=1_440)
    search_results_per_query: int = Field(8, ge=1, le=25)
    fetch_pages: int = Field(3, ge=0, le=10)
    social_results: int = Field(10, ge=0, le=50)
    max_excerpt_chars: int = Field(1_200, ge=200, le=4_000)
    min_sources: int = Field(4, ge=1, le=30)
    min_web_sources: int = Field(2, ge=1, le=20)
    min_fresh_sources: int = Field(2, ge=1, le=20)
    min_decision_citations: int = Field(2, ge=1, le=10)
    require_social: bool = True
    require_for_live: bool = True
    sec_ciks: dict[str, str] = Field(default_factory=dict)
    sec_user_agent: str | None = None

    @field_validator("sec_ciks")
    @classmethod
    def normalize_ciks(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for symbol, cik in value.items():
            clean_symbol = symbol.strip().upper()
            clean_cik = re.sub(r"\D", "", cik).zfill(10)
            if not clean_symbol or len(clean_cik) != 10:
                raise ValueError("SEC CIK mappings require a symbol and a 10-digit CIK")
            normalized[clean_symbol] = clean_cik
        return normalized

    @model_validator(mode="after")
    def sec_identity_is_explicit(self) -> WebContextPolicy:
        if self.sec_ciks and (not self.sec_user_agent or "@" not in self.sec_user_agent):
            raise ValueError("sec_ciks require sec_user_agent with an operator contact email")
        return self


class ContextSource(BaseModel):
    source_id: str
    channel: Literal["web", "social", "regulatory"]
    title: str
    url: str
    retrieved_at: datetime
    published_at: datetime | None = None
    author: str | None = None
    excerpt: str = ""
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("retrieved_at", "published_at")
    @classmethod
    def timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("context timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("url")
    @classmethod
    def public_https_url(cls, value: str) -> str:
        _validate_public_https_url(value)
        return value


class ContextSnapshot(BaseModel):
    schema_version: str = "edgecraft.context-snapshot.v1"
    collected_at: datetime
    provider: str
    symbols: list[str]
    queries: list[str]
    sources: list[ContextSource]
    fresh_source_count: int = 0
    complete: bool = False
    warnings: list[str] = Field(default_factory=list)
    cache_hit: bool = False

    @field_validator("collected_at")
    @classmethod
    def collected_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("collected_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def unique_sources(self) -> ContextSnapshot:
        ids = [source.source_id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("context source IDs must be unique")
        return self


class ContextCollector(Protocol):
    def collect(self, symbols: list[str], *, now: datetime | None = None) -> ContextSnapshot: ...


class BrowserbaseClient:
    endpoint = "https://api.browserbase.com/v1"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: JsonTransport | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        self.api_key = (api_key or browserbase_api_key()).strip()
        self.transport = transport or _json_request
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, *, num_results: int) -> list[dict[str, Any]]:
        if not self.configured:
            raise ContextUnavailable(
                "BROWSERBASE_API_KEY is not set; create a free Browserbase project and export its API key"
            )
        payload = self._request(
            "POST",
            f"{self.endpoint}/search",
            {"query": query, "numResults": num_results},
        )
        results = payload.get("results")
        if not isinstance(results, list):
            raise ContextUnavailable("Browserbase Search returned no results array")
        return [item for item in results if isinstance(item, dict)]

    def fetch(self, url: str) -> dict[str, Any]:
        _validate_public_https_url(url)
        return self._request(
            "POST",
            f"{self.endpoint}/fetch",
            {
                "url": url,
                "allowRedirects": True,
                "allowInsecureSsl": False,
                "proxies": False,
            },
        )

    def _request(self, method: str, url: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"x-bb-api-key": self.api_key, "Content-Type": "application/json"}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return self.transport(method, url, headers, body, self.timeout_seconds)
            except ContextUnavailable as exc:
                last_error = exc
                if "status=429" not in str(exc) and "status=503" not in str(exc):
                    break
                time.sleep(0.25 * (2**attempt))
        raise ContextUnavailable(str(last_error or "Browserbase request failed"))


class BlueskyClient:
    endpoint = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"

    def __init__(
        self, *, transport: JsonTransport | None = None, timeout_seconds: float = 15
    ) -> None:
        self.transport = transport or _json_request
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        url = f"{self.endpoint}?q={quote(query)}&limit={limit}&sort=latest"
        payload = self.transport("GET", url, {}, None, self.timeout_seconds)
        posts = payload.get("posts")
        return [item for item in posts or [] if isinstance(item, dict)]


class SecEdgarClient:
    endpoint = "https://data.sec.gov/submissions"

    def __init__(
        self,
        *,
        user_agent: str,
        transport: JsonTransport | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        self.user_agent = user_agent
        self.transport = transport or _json_request
        self.timeout_seconds = timeout_seconds

    def recent_filings(self, symbol: str, cik: str, *, limit: int = 5) -> list[dict[str, Any]]:
        payload = self.transport(
            "GET",
            f"{self.endpoint}/CIK{cik}.json",
            {"User-Agent": self.user_agent},
            None,
            self.timeout_seconds,
        )
        recent = payload.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accepted = recent.get("acceptanceDateTime", [])
        filed = recent.get("filingDate", [])
        accession = recent.get("accessionNumber", [])
        primary = recent.get("primaryDocument", [])
        output = []
        wanted = {"8-K", "10-Q", "10-K", "6-K", "20-F", "40-F", "N-CSR"}
        for index, form in enumerate(forms):
            if form not in wanted:
                continue
            accession_clean = accession[index].replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{accession_clean}/{primary[index]}"
            )
            output.append(
                {
                    "symbol": symbol,
                    "form": form,
                    "accepted": accepted[index] if index < len(accepted) else None,
                    "filed": filed[index] if index < len(filed) else None,
                    "url": url,
                }
            )
            if len(output) >= limit:
                break
        return output


class ExternalContextService:
    def __init__(
        self,
        policy: WebContextPolicy,
        *,
        browserbase: BrowserbaseClient | None = None,
        bluesky: BlueskyClient | None = None,
        sec: SecEdgarClient | None = None,
        cache_directory: Path | None = None,
    ) -> None:
        self.policy = policy
        self.browserbase = browserbase or BrowserbaseClient()
        self.bluesky = bluesky or BlueskyClient()
        self.sec = sec or SecEdgarClient(user_agent=policy.sec_user_agent or "")
        self.cache_directory = cache_directory

    def collect(self, symbols: list[str], *, now: datetime | None = None) -> ContextSnapshot:
        collected_at = (now or datetime.now(UTC)).astimezone(UTC)
        clean_symbols = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol))
        if not clean_symbols:
            raise ValueError("at least one context symbol is required")
        cached = self._read_cache(clean_symbols, collected_at)
        if cached is not None:
            return cached.model_copy(update={"cache_hit": True})

        since = (collected_at - timedelta(hours=self.policy.lookback_hours)).date().isoformat()
        symbol_text = " ".join(clean_symbols)
        queries = [
            _bounded_query(f"{symbol_text} market news earnings catalysts since {since}"),
            _bounded_query(f"site:sec.gov {symbol_text} filing 8-K 10-Q 10-K since {since}"),
        ]
        warnings: list[str] = []
        sources: list[ContextSource] = []
        for query in queries:
            for result in self.browserbase.search(
                query, num_results=self.policy.search_results_per_query
            ):
                source = _web_source(result, collected_at)
                if source is not None:
                    sources.append(source)

        fetch_failures = 0
        fetched = 0
        for source in _diverse_web_sources(sources):
            if fetched >= self.policy.fetch_pages:
                break
            try:
                response = self.browserbase.fetch(source.url)
                if int(response.get("statusCode", 0)) != 200:
                    raise ContextUnavailable(
                        f"fetch returned target status {response.get('statusCode')}"
                    )
                excerpt = _content_excerpt(
                    str(response.get("content", "")), self.policy.max_excerpt_chars
                )
                if excerpt:
                    source.excerpt = excerpt
                    fetched += 1
            except ContextUnavailable:
                fetch_failures += 1
        if fetch_failures:
            warnings.append(f"Browserbase Fetch failed for {fetch_failures} selected result(s)")

        if self.policy.social_results:
            try:
                per_symbol = max(1, self.policy.social_results // len(clean_symbols))
                for symbol in clean_symbols:
                    posts = self.bluesky.search(f"${symbol} OR {symbol}", limit=per_symbol)
                    sources.extend(
                        _bluesky_sources(posts, collected_at, self.policy.max_excerpt_chars)
                    )
            except ContextUnavailable as exc:
                warnings.append(f"Bluesky unavailable: {exc}")

        for symbol, cik in self.policy.sec_ciks.items():
            if symbol not in clean_symbols:
                continue
            try:
                filings = self.sec.recent_filings(symbol, cik)
                sources.extend(_sec_sources(filings, collected_at))
            except ContextUnavailable as exc:
                warnings.append(f"SEC EDGAR unavailable for {symbol}: {exc}")

        sources = _deduplicate_sources(sources)
        cutoff = collected_at - timedelta(hours=self.policy.lookback_hours)
        fresh_count = sum(
            source.published_at is not None and source.published_at >= cutoff for source in sources
        )
        channels = {source.channel for source in sources}
        web_count = sum(source.channel == "web" for source in sources)
        complete = (
            len(sources) >= self.policy.min_sources
            and web_count >= self.policy.min_web_sources
            and fresh_count >= self.policy.min_fresh_sources
            and "web" in channels
            and (not self.policy.require_social or "social" in channels)
        )
        if not complete:
            warnings.append(
                "context did not meet configured source, freshness, and channel requirements"
            )
        snapshot = ContextSnapshot(
            collected_at=collected_at,
            provider="browserbase+public-apis",
            symbols=clean_symbols,
            queries=queries,
            sources=sources,
            fresh_source_count=fresh_count,
            complete=complete,
            warnings=warnings,
        )
        self._write_cache(clean_symbols, snapshot)
        return snapshot

    def _cache_path(self, symbols: list[str]) -> Path | None:
        if self.cache_directory is None:
            return None
        key = json.dumps(
            {"symbols": symbols, "policy": self.policy.model_dump(mode="json")},
            sort_keys=True,
        )
        digest = hashlib.sha256(key.encode()).hexdigest()[:20]
        return self.cache_directory / f"{digest}.json"

    def _read_cache(self, symbols: list[str], now: datetime) -> ContextSnapshot | None:
        path = self._cache_path(symbols)
        if path is None or self.policy.cache_ttl_minutes == 0 or not path.exists():
            return None
        try:
            snapshot = ContextSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        age = now - snapshot.collected_at
        if age < timedelta(0) or age > timedelta(minutes=self.policy.cache_ttl_minutes):
            return None
        return snapshot

    def _write_cache(self, symbols: list[str], snapshot: ContextSnapshot) -> None:
        path = self._cache_path(symbols)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)


def load_context_service(
    repository: Path, policy_path: str | Path, *, api_key: str | None = None
) -> ExternalContextService:
    configured_path = Path(policy_path)
    resolved = configured_path if configured_path.is_absolute() else repository / configured_path
    policy = WebContextPolicy.model_validate_json(resolved.read_text(encoding="utf-8"))
    return ExternalContextService(
        policy,
        browserbase=BrowserbaseClient(api_key),
        cache_directory=repository / "state" / "context-cache",
    )


def browserbase_api_key() -> str:
    direct = os.environ.get("BROWSERBASE_API_KEY", "").strip()
    if direct:
        return direct
    configured_file = os.environ.get("BROWSERBASE_API_KEY_FILE", "").strip()
    if not configured_file:
        return ""
    path = Path(configured_file).expanduser()
    try:
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            raise ContextUnavailable("BROWSERBASE_API_KEY_FILE must not be group/world accessible")
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ContextUnavailable(f"unable to read BROWSERBASE_API_KEY_FILE: {exc}") from exc


def _json_request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    _validate_public_https_url(url)
    data = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=data, headers=headers, method=method)
    try:
        # URL validation above rejects non-HTTPS and private literal addresses.
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            raw = response.read()
    except HTTPError as exc:
        raise ContextUnavailable(
            f"request failed status={exc.code} host={urlparse(url).hostname}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise ContextUnavailable(f"request failed host={urlparse(url).hostname}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContextUnavailable(f"non-JSON response from {urlparse(url).hostname}") from exc
    if not isinstance(payload, dict):
        raise ContextUnavailable(f"unexpected response from {urlparse(url).hostname}")
    return payload


def _validate_public_https_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("context URLs must be public HTTPS URLs without credentials")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".local"):
        raise ValueError("local context URLs are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("private or reserved context IP addresses are not allowed")


def _bounded_query(value: str) -> str:
    return value[:200].rstrip()


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    clean = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(clean)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{clean}T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _source_id(channel: str, url: str) -> str:
    return f"{channel}-{hashlib.sha256(url.encode()).hexdigest()[:12]}"


def _web_source(result: dict[str, Any], now: datetime) -> ContextSource | None:
    url = str(result.get("url", ""))
    try:
        _validate_public_https_url(url)
    except ValueError:
        return None
    title = str(result.get("title") or urlparse(url).hostname or "Untitled source")[:500]
    return ContextSource(
        source_id=_source_id("web", url),
        channel="web",
        title=title,
        url=url,
        retrieved_at=now,
        published_at=_parse_datetime(result.get("publishedDate")),
        author=str(result["author"])[:200] if result.get("author") else None,
        metadata={"search_result_id": str(result.get("id", ""))[:200]},
    )


def _diverse_web_sources(sources: list[ContextSource]) -> list[ContextSource]:
    seen_hosts: set[str] = set()
    output: list[ContextSource] = []
    for source in sources:
        host = urlparse(source.url).hostname or ""
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        output.append(source)
    return output


def _content_excerpt(content: str, limit: int) -> str:
    without_scripts = re.sub(r"(?is)<(script|style|noscript|svg).*?>.*?</\1>", " ", content)
    text = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _bluesky_sources(
    posts: list[dict[str, Any]], now: datetime, max_excerpt_chars: int
) -> list[ContextSource]:
    sources = []
    for post in posts:
        author = post.get("author") or {}
        record = post.get("record") or {}
        uri = str(post.get("uri", ""))
        handle = str(author.get("handle", ""))
        rkey = uri.rsplit("/", 1)[-1] if "/" in uri else ""
        if not handle or not rkey:
            continue
        url = f"https://bsky.app/profile/{handle}/post/{rkey}"
        excerpt = re.sub(r"\s+", " ", str(record.get("text", ""))).strip()
        sources.append(
            ContextSource(
                source_id=_source_id("social", url),
                channel="social",
                title=f"Bluesky post by @{handle}",
                url=url,
                retrieved_at=now,
                published_at=_parse_datetime(record.get("createdAt") or post.get("indexedAt")),
                author=handle,
                excerpt=excerpt[:max_excerpt_chars],
                metadata={
                    "like_count": int(post.get("likeCount", 0)),
                    "repost_count": int(post.get("repostCount", 0)),
                    "reply_count": int(post.get("replyCount", 0)),
                },
            )
        )
    return sources


def _sec_sources(filings: list[dict[str, Any]], now: datetime) -> list[ContextSource]:
    sources = []
    for filing in filings:
        url = str(filing["url"])
        symbol = str(filing["symbol"])
        form = str(filing["form"])
        sources.append(
            ContextSource(
                source_id=_source_id("regulatory", url),
                channel="regulatory",
                title=f"{symbol} SEC {form} filing",
                url=url,
                retrieved_at=now,
                published_at=_parse_datetime(filing.get("accepted") or filing.get("filed")),
                author="U.S. Securities and Exchange Commission",
                metadata={"symbol": symbol, "form": form},
            )
        )
    return sources


def _deduplicate_sources(sources: list[ContextSource]) -> list[ContextSource]:
    output: list[ContextSource] = []
    by_url: dict[str, ContextSource] = {}
    for source in sources:
        existing = by_url.get(source.url)
        if existing is None:
            by_url[source.url] = source
            output.append(source)
        elif not existing.excerpt and source.excerpt:
            existing.excerpt = source.excerpt
    return output
