from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .security import SidecarSecret

_BOOTSTRAP_URL = "https://linux.do/about.json"
_DEVICE_START_URL = "https://linux.do/user-api-key/device.json"
_DEVICE_POLL_URL = "https://linux.do/user-api-key/device/poll.json"
_TOPIC_URL_PREFIX = "https://linux.do/posts/by_number/"
_TOPIC_URL_SUFFIX = "/1.json?include_raw=true"
_MAX_HEADERS = 8
_MAX_HEADER_BYTES = 8_192

_BROWSER_FETCH_SCRIPT = """
async ({ action, url, payload, userApiKey, userApiClientId, timeoutMs, maxBytes }) => {
  const actions = {
    topic: {
      method: "GET",
      headers: {
        "Accept": "application/json",
        "User-Api-Key": userApiKey,
        "User-Api-Client-Id": userApiClientId
      }
    },
    device_start: {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json"
      }
    },
    device_poll: {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json"
      }
    }
  };
  const selected = actions[action];
  if (!selected) {
    throw new Error("unsupported fixed browser action");
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const options = {
      method: selected.method,
      headers: selected.headers,
      credentials: "include",
      cache: "no-store",
      redirect: "error",
      signal: controller.signal
    };
    if (selected.method === "POST") {
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(url, options);
    const body = await response.text();
    const bodyBytes = new TextEncoder().encode(body).byteLength;
    return {
      status: response.status,
      url: response.url,
      headers: {
        "content-type": response.headers.get("content-type") || "",
        "cf-mitigated": response.headers.get("cf-mitigated") || ""
      },
      body,
      tooLarge: bodyBytes > maxBytes
    };
  } finally {
    clearTimeout(timer);
  }
}
"""


@dataclass(frozen=True, slots=True)
class BrowserResponse:
    status: int
    headers: dict[str, str]
    body: bytes


@asynccontextmanager
async def _open_byparr_browser() -> AsyncIterator[Any]:
    try:
        from src.utils import get_browser
    except ImportError as exc:
        raise RuntimeError("Byparr runtime is unavailable") from exc

    generator = get_browser(None, None, None)
    try:
        dependency = await anext(generator)
    except StopAsyncIteration as exc:
        raise RuntimeError("Byparr browser provider returned no browser") from exc
    try:
        yield dependency
    finally:
        await generator.aclose()


async def _prepare_linuxdo_page(dependency: Any, timeout_seconds: int) -> int:
    try:
        from src.challenge import challenge_present, solve_challenge
        from src.utils import TimeoutTimer, remaining_ms
    except ImportError as exc:
        raise RuntimeError("Byparr challenge runtime is unavailable") from exc

    timer = TimeoutTimer(duration=timeout_seconds)
    await dependency.page.goto(
        _BOOTSTRAP_URL,
        timeout=remaining_ms(timer),
    )
    await dependency.page.wait_for_load_state(
        "domcontentloaded",
        timeout=remaining_ms(timer),
    )
    if await challenge_present(dependency.page):
        await solve_challenge(dependency.page, timer)
    parts = urlsplit(str(dependency.page.url))
    if parts.scheme != "https" or parts.hostname != "linux.do":
        raise RuntimeError("Byparr bootstrap escaped fixed Linux.do origin")
    return int(remaining_ms(timer))


def _validate_fixed_action(action: str, url: str) -> None:
    if action == "topic":
        if not url.startswith(_TOPIC_URL_PREFIX) or not url.endswith(
            _TOPIC_URL_SUFFIX
        ):
            raise RuntimeError("topic browser URL is not fixed")
        topic_part = url[len(_TOPIC_URL_PREFIX) : -len(_TOPIC_URL_SUFFIX)]
        if not topic_part.isascii() or not topic_part.isdigit():
            raise RuntimeError("topic browser URL is invalid")
        return
    expected = {
        "device_start": _DEVICE_START_URL,
        "device_poll": _DEVICE_POLL_URL,
    }.get(action)
    if expected is None or url != expected:
        raise RuntimeError("device browser URL is not fixed")


def _parse_browser_result(
    result: Any,
    *,
    expected_url: str,
    max_response_bytes: int,
) -> BrowserResponse:
    if not isinstance(result, dict) or result.get("tooLarge") is True:
        raise RuntimeError("Byparr browser response is invalid or too large")
    status = result.get("status")
    final_url = result.get("url")
    raw_headers = result.get("headers")
    raw_body = result.get("body")
    if (
        isinstance(status, bool)
        or not isinstance(status, int)
        or status < 100
        or status > 599
        or final_url != expected_url
        or not isinstance(raw_headers, dict)
        or len(raw_headers) > _MAX_HEADERS
        or not isinstance(raw_body, str)
    ):
        raise RuntimeError("Byparr browser response fields are invalid")
    headers: dict[str, str] = {}
    for key, value in raw_headers.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or len(key.encode("utf-8")) > 256
            or len(value.encode("utf-8")) > _MAX_HEADER_BYTES
        ):
            raise RuntimeError("Byparr browser response headers are invalid")
        headers[key.lower()] = value
    body = raw_body.encode("utf-8")
    if len(body) > max_response_bytes:
        raise RuntimeError("Byparr browser response exceeded byte limit")
    return BrowserResponse(status=status, headers=headers, body=body)


class LinuxDoBrowser:
    def __init__(
        self,
        *,
        secret: SidecarSecret | None,
        timeout_seconds: int,
        request_timeout_seconds: int,
        max_response_bytes: int,
    ) -> None:
        self._secret = secret
        self._timeout_seconds = max(30, min(330, int(timeout_seconds)))
        self._request_timeout_ms = (
            max(5, min(60, int(request_timeout_seconds))) * 1000
        )
        self._max_response_bytes = max_response_bytes
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def fetch_first_post(self, topic_id: int) -> BrowserResponse:
        if self._secret is None:
            raise RuntimeError("User API secret is unavailable")
        if isinstance(topic_id, bool) or not 1 <= topic_id <= 2_147_483_647:
            raise RuntimeError("topic ID is invalid")
        url = f"{_TOPIC_URL_PREFIX}{topic_id}{_TOPIC_URL_SUFFIX}"
        return await self._request(
            action="topic",
            url=url,
            payload=None,
            user_api_key=self._secret.user_api_key,
            user_api_client_id=self._secret.user_api_client_id,
        )

    async def post_device(
        self,
        mode: str,
        payload: dict[str, str],
    ) -> BrowserResponse:
        action_urls = {
            "start": ("device_start", _DEVICE_START_URL),
            "poll": ("device_poll", _DEVICE_POLL_URL),
        }
        selected = action_urls.get(mode)
        if selected is None:
            raise RuntimeError("device mode is invalid")
        action, url = selected
        return await self._request(
            action=action,
            url=url,
            payload=payload,
            user_api_key="",
            user_api_client_id="",
        )

    async def _request(
        self,
        *,
        action: str,
        url: str,
        payload: dict[str, str] | None,
        user_api_key: str,
        user_api_client_id: str,
    ) -> BrowserResponse:
        _validate_fixed_action(action, url)
        async with self._lock, _open_byparr_browser() as dependency:
            remaining = await _prepare_linuxdo_page(
                dependency,
                self._timeout_seconds,
            )
            if remaining <= 0:
                raise RuntimeError("Byparr request budget was exhausted")
            result = await dependency.page.evaluate(
                _BROWSER_FETCH_SCRIPT,
                {
                    "action": action,
                    "url": url,
                    "payload": payload or {},
                    "userApiKey": user_api_key,
                    "userApiClientId": user_api_client_id,
                    "timeoutMs": min(self._request_timeout_ms, remaining),
                    "maxBytes": self._max_response_bytes,
                },
            )
            return _parse_browser_result(
                result,
                expected_url=url,
                max_response_bytes=self._max_response_bytes,
            )
