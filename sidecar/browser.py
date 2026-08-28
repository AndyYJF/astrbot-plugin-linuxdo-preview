from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

from .security import AUTH_MODE_BROWSER_SESSION, SidecarSecret
from .session_state import load_session_state, write_session_state

_BOOTSTRAP_URL = "https://linux.do/about.json"
_DEVICE_START_URL = "https://linux.do/user-api-key/device.json"
_DEVICE_POLL_URL = "https://linux.do/user-api-key/device/poll.json"
_TOPIC_URL_PREFIX = "https://linux.do/posts/by_number/"
_TOPIC_URL_SUFFIX = "/1.json?include_raw=true"
_MAX_HEADERS = 8
_MAX_HEADER_BYTES = 8_192


class BrowserSessionExpired(RuntimeError):
    pass

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
  if (action === "topic" && (!userApiKey || !userApiClientId)) {
    selected.headers = {"Accept": "application/json"};
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

_SESSION_CURRENT_SCRIPT = """
async ({ timeoutMs }) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch("https://linux.do/session/current.json", {
      method: "GET",
      headers: {"Accept": "application/json"},
      credentials: "include",
      cache: "no-store",
      redirect: "error",
      signal: controller.signal
    });
    if (response.status !== 200 ||
        response.url !== "https://linux.do/session/current.json") {
      return {ok: false, authenticated: false};
    }
    const payload = await response.json();
    const currentUser =
      payload && typeof payload === "object" ? payload.current_user : null;
    return {
      ok: true,
      authenticated: Boolean(
        payload &&
        typeof payload === "object" &&
        (Number.isInteger(payload.id) ||
          (currentUser !== null &&
            typeof currentUser === "object" &&
            Number.isInteger(currentUser.id)))
      )
    };
  } catch (_error) {
    return {ok: false, authenticated: false};
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


def _browser_context_options(
    *,
    storage_state: dict[str, Any] | None,
    headless: bool,
) -> dict[str, Any]:
    options: dict[str, Any] = {"storage_state": storage_state}
    if not headless:
        options["viewport"] = {"width": 1920, "height": 995}
        options["screen"] = {"width": 1920, "height": 1080}
    return options


@asynccontextmanager
async def _open_byparr_browser(
    *,
    storage_state: dict[str, Any] | None = None,
    browser_seed: int | None = None,
    headless: bool = True,
) -> AsyncIterator[Any]:
    try:
        from invisible_playwright.async_api import InvisiblePlaywright
        from src.consts import (
            BROWSER_LOCALE,
            PROXY_PASSWORD,
            PROXY_SERVER,
            PROXY_USERNAME,
        )
    except ImportError as exc:
        raise RuntimeError("Byparr runtime is unavailable") from exc

    proxy_config = None
    if PROXY_SERVER:
        proxy_config = {
            "server": PROXY_SERVER,
            "username": PROXY_USERNAME,
            "password": PROXY_PASSWORD,
        }
    browser_options: dict[str, Any] = {
        "headless": headless,
        "proxy": proxy_config,
        "humanize": True,
        "locale": BROWSER_LOCALE or "auto",
        "extra_prefs": {
            "devtools.jsonview.enabled": False,
            "browser.tabs.remote.useCrossOriginOpenerPolicy": False,
            "browser.tabs.remote.useCrossOriginEmbedderPolicy": False,
        },
    }
    if browser_seed is not None:
        browser_options["seed"] = browser_seed
    async with InvisiblePlaywright(**browser_options) as browser:
        context = await browser.new_context(
            **_browser_context_options(
                storage_state=storage_state,
                headless=headless,
            )
        )
        try:
            page = await context.new_page()
            yield SimpleNamespace(page=page, context=context)
        finally:
            await context.close()


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


async def _session_is_authenticated(page: Any, timeout_ms: int) -> bool:
    result = await page.evaluate(
        _SESSION_CURRENT_SCRIPT,
        {"timeoutMs": timeout_ms},
    )
    if (
        not isinstance(result, dict)
        or result.get("ok") is not True
        or not isinstance(result.get("authenticated"), bool)
    ):
        raise RuntimeError("Linux.do session check is unavailable")
    return result["authenticated"]


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
        session_state_file: str = "",
    ) -> None:
        self._secret = secret
        self._timeout_seconds = max(30, min(330, int(timeout_seconds)))
        self._request_timeout_ms = (
            max(5, min(60, int(request_timeout_seconds))) * 1000
        )
        self._max_response_bytes = max_response_bytes
        self._session_state_file = session_state_file
        self._lock = asyncio.Lock()
        if (
            secret is not None
            and secret.auth_mode == AUTH_MODE_BROWSER_SESSION
            and (not session_state_file or secret.browser_seed is None)
        ):
            raise RuntimeError(
                "browser session mode requires state file and browser seed"
            )
        if secret is not None and secret.auth_mode == AUTH_MODE_BROWSER_SESSION:
            load_session_state(session_state_file)

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def fetch_first_post(self, topic_id: int) -> BrowserResponse:
        if self._secret is None:
            raise RuntimeError("authenticated secret is unavailable")
        if isinstance(topic_id, bool) or not 1 <= topic_id <= 2_147_483_647:
            raise RuntimeError("topic ID is invalid")
        url = f"{_TOPIC_URL_PREFIX}{topic_id}{_TOPIC_URL_SUFFIX}"
        user_api_key = ""
        user_api_client_id = ""
        if self._secret.auth_mode != AUTH_MODE_BROWSER_SESSION:
            user_api_key = self._secret.user_api_key
            user_api_client_id = self._secret.user_api_client_id
        return await self._request(
            action="topic",
            url=url,
            payload=None,
            user_api_key=user_api_key,
            user_api_client_id=user_api_client_id,
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
        session_mode = (
            self._secret is not None
            and self._secret.auth_mode == AUTH_MODE_BROWSER_SESSION
        )
        async with self._lock:
            storage_state = (
                load_session_state(self._session_state_file)
                if session_mode
                else None
            )
            browser_seed = (
                self._secret.browser_seed
                if session_mode and self._secret is not None
                else None
            )
            async with _open_byparr_browser(
                storage_state=storage_state,
                browser_seed=browser_seed,
            ) as dependency:
                authenticated_session = False
                try:
                    remaining = await _prepare_linuxdo_page(
                        dependency,
                        self._timeout_seconds,
                    )
                    if remaining <= 0:
                        raise RuntimeError("Byparr request budget was exhausted")
                    if session_mode:
                        authenticated_session = await _session_is_authenticated(
                            dependency.page,
                            min(self._request_timeout_ms, remaining),
                        )
                        if not authenticated_session:
                            raise BrowserSessionExpired(
                                "Linux.do browser session is not authenticated"
                            )
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
                finally:
                    if authenticated_session:
                        refreshed = await dependency.context.storage_state()
                        write_session_state(
                            self._session_state_file,
                            refreshed,
                        )
