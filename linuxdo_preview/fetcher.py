from __future__ import annotations

import asyncio
import html
import json
import re
from collections import deque
from collections.abc import Mapping
from time import monotonic

import aiohttp

from .auth import SecretLoadError, load_user_api_credentials
from .models import FetchedTopic, FetchError, FetchErrorCode, TopicRef
from .settings import Settings

_READER_PREFIX = "https://r.jina.ai/"
_READER_MARKER = "Markdown Content:"
_READER_TITLE_RE = re.compile(r"(?m)^Title:\s*(?P<title>.*)$")
_READER_ORIGIN_ERROR_RE = re.compile(
    r"Target URL returned error\s+(?P<status>\d{3})", re.IGNORECASE
)
_RESTRICTED_PLACEHOLDERS = frozenset(
    {
        "oops! that page doesn't exist or is private",
        "oops! that page doesn’t exist or is private",
    }
)
_CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl-",
    "cloudflare challenge",
    "enable javascript and cookies to continue",
)
_READER_HEADERS = {
    "Accept": "text/plain",
    "X-No-Cache": "true",
    "X-Target-Selector": "#post_1 .cooked",
}
_AUTHENTICATED_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "AstrBot-LinuxDo-Preview/0.7 (read-only)",
}
_AUTHENTICATED_SIDECAR_URL = "http://linuxdo-auth-sidecar:8787/v1/topic"


def is_cloudflare_challenge(status: int, headers: Mapping[str, str], body: str) -> bool:
    mitigated = headers.get("cf-mitigated", "").lower()
    lowered = body[:16_384].lower()
    return mitigated == "challenge" or (
        status in {403, 429, 503}
        and any(marker in lowered for marker in _CHALLENGE_MARKERS)
    )


def unwrap_reader_response(body: str) -> str:
    normalized = body.replace("\r\n", "\n")
    head = normalized[:1200]
    if head.startswith("Title:") and "URL Source:" in head:
        marker_index = normalized.find(_READER_MARKER)
        if marker_index >= 0:
            return normalized[marker_index + len(_READER_MARKER) :].lstrip("\n")
    return normalized


def parse_reader_page_title(value: str, topic_id: int) -> tuple[str, str]:
    cleaned = html.unescape(value).strip()
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", cleaned)
    if not cleaned:
        return f"LINUX DO 帖子 #{topic_id}", ""

    parts = cleaned.rsplit(" - ", 2)
    if len(parts) == 3 and parts[-1].strip().casefold() == "linux do":
        title, category = parts[0].strip(), parts[1].strip()
    elif len(parts) == 2 and parts[-1].strip().casefold() == "linux do":
        title, category = parts[0].strip(), ""
    else:
        title, category = cleaned, ""

    title = title[:180].strip() or f"LINUX DO 帖子 #{topic_id}"
    return title, category[:80].strip()


def parse_reader_topic_response(body: str, topic_id: int) -> tuple[str, str, str]:
    title_match = _READER_TITLE_RE.search(body[:4000])
    page_title = title_match.group("title").strip() if title_match else ""
    title, category = parse_reader_page_title(page_title, topic_id)
    return title, category, unwrap_reader_response(body).strip()


def is_restricted_placeholder(body: str) -> bool:
    """Recognize Discourse's ambiguous private/not-found placeholder body."""
    normalized = re.sub(r"\s+", " ", body).strip(" #>*_`\t\r\n.").casefold()
    return normalized in _RESTRICTED_PLACEHOLDERS


def parse_authenticated_topic_response(body: str, topic_id: int) -> FetchedTopic:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FetchError(
            FetchErrorCode.UNAVAILABLE,
            "authenticated response was not valid JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise FetchError(
            FetchErrorCode.UNAVAILABLE,
            "authenticated response root was not an object",
        )

    post_stream = payload.get("post_stream")
    posts = post_stream.get("posts") if isinstance(post_stream, dict) else None
    if not isinstance(posts, list):
        posts = payload.get("posts")
    if not isinstance(posts, list):
        raise FetchError(
            FetchErrorCode.UNAVAILABLE,
            "authenticated response omitted posts",
        )

    first_post = next(
        (
            post
            for post in posts
            if isinstance(post, dict)
            and post.get("post_number") == 1
            and post.get("topic_id", topic_id) == topic_id
        ),
        None,
    )
    if first_post is None:
        raise FetchError(
            FetchErrorCode.UNAVAILABLE,
            "authenticated response omitted first post",
        )
    raw = first_post.get("raw")
    if not isinstance(raw, str) or not raw.strip():
        raise FetchError(
            FetchErrorCode.UNAVAILABLE,
            "authenticated first post omitted raw content",
        )

    title_value = payload.get("title") or first_post.get("topic_title") or ""
    title = str(title_value).strip()[:180] or f"LINUX DO 帖子 #{topic_id}"
    category_value = payload.get("category_name") or first_post.get("category_name")
    category = str(category_value).strip()[:80] if category_value else ""
    return FetchedTopic(
        title=title,
        category=category,
        content=raw.strip(),
        source="discourse-user-api",
    )


class LinuxDoFetcher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)
        self._reader_rate_lock = asyncio.Lock()
        self._reader_requests: deque[float] = deque()
        self._authenticated_rate_lock = asyncio.Lock()
        self._authenticated_requests: deque[float] = deque()

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def fetch_first_post(self, ref: TopicRef) -> FetchedTopic:
        return await self._fetch_reader(ref)

    async def fetch_authenticated_first_post(self, ref: TopicRef) -> FetchedTopic:
        if not self._settings.authenticated_enabled:
            raise FetchError(
                FetchErrorCode.AUTH_UNAVAILABLE,
                "authenticated channel is disabled",
            )
        try:
            credentials = load_user_api_credentials(
                self._settings.authenticated_secret_file
            )
        except SecretLoadError as exc:
            raise FetchError(
                FetchErrorCode.AUTH_UNAVAILABLE,
                type(exc).__name__,
            ) from exc

        await self._acquire_authenticated_slot()
        request_headers = {
            **_AUTHENTICATED_HEADERS,
            "User-Api-Key": credentials.user_api_key,
            "User-Api-Client-Id": credentials.user_api_client_id,
        }
        status, headers, body = await self._request(
            ref.authenticated_first_post_url,
            timeout_seconds=self._settings.authenticated_timeout_seconds,
            request_headers=request_headers,
            allow_redirects=False,
        )
        if is_cloudflare_challenge(status, headers, body):
            if not credentials.sidecar_token:
                raise FetchError(
                    FetchErrorCode.CHALLENGE,
                    "authenticated endpoint returned challenge",
                )
            status, headers, body = await self._request_sidecar(
                ref,
                credentials.sidecar_token,
            )
            if status == 409:
                raise FetchError(
                    FetchErrorCode.CHALLENGE,
                    "sidecar browser clearance is unavailable",
                )
            if status == 401:
                raise FetchError(
                    FetchErrorCode.AUTH_UNAVAILABLE,
                    "sidecar authentication failed",
                )
        if status == 401:
            raise FetchError(
                FetchErrorCode.AUTH_INVALID,
                "user API key was rejected",
            )
        if status in {403, 404}:
            raise FetchError(
                FetchErrorCode.AUTH_FORBIDDEN,
                "authorized account cannot access topic",
            )
        if status == 429:
            raise FetchError(
                FetchErrorCode.RATE_LIMITED,
                "authenticated endpoint rate limited",
            )
        if status >= 500:
            raise FetchError(
                FetchErrorCode.UNAVAILABLE,
                "authenticated endpoint unavailable",
            )
        if status >= 300:
            raise FetchError(
                FetchErrorCode.NETWORK,
                f"authenticated endpoint HTTP {status}",
            )
        return parse_authenticated_topic_response(body, ref.topic_id)

    async def _request_sidecar(
        self,
        ref: TopicRef,
        sidecar_token: str,
    ) -> tuple[int, dict[str, str], str]:
        session = self._get_session()
        timeout = aiohttp.ClientTimeout(
            total=self._settings.authenticated_timeout_seconds
        )
        try:
            async with self._semaphore:
                async with session.post(
                    _AUTHENTICATED_SIDECAR_URL,
                    json={"topic_id": ref.topic_id},
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {sidecar_token}",
                    },
                    timeout=timeout,
                    allow_redirects=False,
                ) as response:
                    payload = await response.content.read(
                        self._settings.max_response_bytes + 1
                    )
                    if len(payload) > self._settings.max_response_bytes:
                        raise FetchError(
                            FetchErrorCode.TOO_LARGE,
                            "sidecar response exceeded byte limit",
                        )
                    return (
                        response.status,
                        {key.lower(): value for key, value in response.headers.items()},
                        payload.decode("utf-8", errors="replace"),
                    )
        except FetchError:
            raise
        except TimeoutError as exc:
            raise FetchError(
                FetchErrorCode.NETWORK,
                "sidecar request timed out",
            ) from exc
        except aiohttp.ClientError as exc:
            raise FetchError(
                FetchErrorCode.AUTH_UNAVAILABLE,
                "sidecar request failed",
            ) from exc

    async def _fetch_reader(self, ref: TopicRef) -> FetchedTopic:
        await self._acquire_reader_slot()
        reader_url = f"{_READER_PREFIX}{ref.canonical_url}"
        status, headers, body = await self._request(
            reader_url,
            timeout_seconds=self._settings.reader_timeout_seconds,
            request_headers=_READER_HEADERS,
        )
        if status == 429:
            raise FetchError(FetchErrorCode.RATE_LIMITED, "reader rate limited")
        if status >= 500:
            raise FetchError(FetchErrorCode.UNAVAILABLE, "reader unavailable")
        if status >= 400:
            raise FetchError(FetchErrorCode.NETWORK, f"reader HTTP {status}")

        if is_cloudflare_challenge(status, headers, body):
            raise FetchError(FetchErrorCode.CHALLENGE, "reader returned challenge")

        title, category, content = parse_reader_topic_response(body, ref.topic_id)
        if is_restricted_placeholder(content):
            raise FetchError(
                FetchErrorCode.RESTRICTED,
                "reader returned private/not-found placeholder",
            )
        origin_error = _READER_ORIGIN_ERROR_RE.search(body[:4000])
        if origin_error:
            self._raise_for_origin_status(int(origin_error.group("status")))
        if not content:
            raise FetchError(FetchErrorCode.UNAVAILABLE, "empty reader response")
        return FetchedTopic(
            title=title,
            category=category,
            content=content,
            source="reader-html",
        )

    async def _acquire_reader_slot(self) -> None:
        async with self._reader_rate_lock:
            now = monotonic()
            cutoff = now - 60
            while self._reader_requests and self._reader_requests[0] <= cutoff:
                self._reader_requests.popleft()
            if len(self._reader_requests) >= self._settings.reader_requests_per_minute:
                raise FetchError(
                    FetchErrorCode.RATE_LIMITED,
                    "local reader requests-per-minute limit reached",
                )
            self._reader_requests.append(now)

    async def _acquire_authenticated_slot(self) -> None:
        async with self._authenticated_rate_lock:
            now = monotonic()
            cutoff = now - 60
            while (
                self._authenticated_requests
                and self._authenticated_requests[0] <= cutoff
            ):
                self._authenticated_requests.popleft()
            if len(self._authenticated_requests) >= (
                self._settings.authenticated_requests_per_minute
            ):
                raise FetchError(
                    FetchErrorCode.RATE_LIMITED,
                    "local authenticated requests-per-minute limit reached",
                )
            self._authenticated_requests.append(now)

    async def _request(
        self,
        url: str,
        timeout_seconds: int,
        request_headers: Mapping[str, str],
        allow_redirects: bool = True,
    ) -> tuple[int, dict[str, str], str]:
        session = self._get_session()
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        try:
            async with self._semaphore:
                async with session.get(
                    url,
                    headers=request_headers,
                    timeout=timeout,
                    proxy=self._settings.proxy_url,
                    allow_redirects=allow_redirects,
                ) as response:
                    payload = bytearray()
                    async for chunk in response.content.iter_chunked(16_384):
                        payload.extend(chunk)
                        if len(payload) > self._settings.max_response_bytes:
                            raise FetchError(
                                FetchErrorCode.TOO_LARGE,
                                "response exceeded configured byte limit",
                            )
                    encoding = response.charset or "utf-8"
                    try:
                        body = payload.decode(encoding, errors="replace")
                    except LookupError:
                        body = payload.decode("utf-8", errors="replace")
                    response_headers = {
                        key.lower(): value for key, value in response.headers.items()
                    }
                    return response.status, response_headers, body
        except FetchError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise FetchError(FetchErrorCode.NETWORK, type(exc).__name__) from exc

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(trust_env=False)
        return self._session

    @staticmethod
    def _raise_for_origin_status(status: int) -> None:
        if status == 404:
            raise FetchError(FetchErrorCode.NOT_FOUND, "origin not found")
        if status in {401, 403}:
            raise FetchError(FetchErrorCode.RESTRICTED, "origin requires access")
        if status == 429:
            raise FetchError(FetchErrorCode.RATE_LIMITED, "origin rate limited")
        if status >= 500:
            raise FetchError(FetchErrorCode.UNAVAILABLE, "origin unavailable")
        raise FetchError(FetchErrorCode.NETWORK, f"origin HTTP {status}")
