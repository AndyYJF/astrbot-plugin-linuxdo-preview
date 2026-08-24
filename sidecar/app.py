from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from time import monotonic

from aiohttp import web

from .browser import LinuxDoBrowser
from .protocol import UpstreamPayloadError, filter_first_post
from .security import bearer_is_valid, load_sidecar_secret, validate_topic_payload

MAX_REQUEST_BYTES = 1_024
MAX_RESPONSE_BYTES = 262_144
REQUESTS_PER_MINUTE = 3
_CHALLENGE_MARKERS = (b"cf-chl-", b"just a moment", b"cloudflare challenge")


class SidecarApp:
    def __init__(self) -> None:
        secret_file = os.environ.get(
            "LINUXDO_SECRET_FILE",
            "/run/secrets/astrbot_plugin_linuxdo_preview.json",
        )
        self.secret = load_sidecar_secret(secret_file)
        self.browser = LinuxDoBrowser(
            secret=self.secret,
            profile_dir=os.environ.get(
                "LINUXDO_BROWSER_PROFILE_DIR",
                "/var/lib/linuxdo-browser",
            ),
            proxy_server=os.environ.get("LINUXDO_PROXY_SERVER", ""),
            timeout_seconds=20,
            max_response_bytes=MAX_RESPONSE_BYTES,
        )
        self._requests: deque[float] = deque()
        self._rate_lock = asyncio.Lock()

    async def startup(self, _application: web.Application) -> None:
        await self.browser.start()

    async def cleanup(self, _application: web.Application) -> None:
        await self.browser.close()

    async def health(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "browser": "ready"})

    async def topic(self, request: web.Request) -> web.Response:
        if not bearer_is_valid(
            request.headers.get("Authorization", ""),
            self.secret.sidecar_token,
        ):
            return web.json_response({"error": "unauthorized"}, status=401)
        if (
            request.content_length is not None
            and request.content_length > MAX_REQUEST_BYTES
        ):
            return web.json_response({"error": "request_too_large"}, status=413)
        try:
            topic_id = validate_topic_payload(await request.json())
        except (ValueError, json.JSONDecodeError):
            return web.json_response({"error": "invalid_request"}, status=400)
        async with self._rate_lock:
            now = monotonic()
            while self._requests and self._requests[0] <= now - 60:
                self._requests.popleft()
            if len(self._requests) >= REQUESTS_PER_MINUTE:
                return web.json_response({"error": "rate_limited"}, status=429)
            self._requests.append(now)
        try:
            response = await self.browser.fetch_first_post(topic_id)
        except Exception:
            return web.json_response({"error": "browser_unavailable"}, status=503)
        lowered = response.body[:16_384].lower()
        if response.headers.get("cf-mitigated", "").lower() == "challenge" or (
            response.status in {403, 429, 503}
            and any(marker in lowered for marker in _CHALLENGE_MARKERS)
        ):
            return web.json_response({"error": "clearance_required"}, status=409)
        if response.status in {401, 403, 404, 429}:
            return web.json_response(
                {"error": "upstream_rejected"},
                status=response.status,
            )
        if response.status != 200:
            return web.json_response({"error": "upstream_unavailable"}, status=502)
        try:
            filtered = filter_first_post(response.body, topic_id)
        except UpstreamPayloadError:
            return web.json_response({"error": "invalid_upstream_payload"}, status=502)
        return web.json_response(filtered)


def create_app() -> web.Application:
    service = SidecarApp()
    application = web.Application(client_max_size=MAX_REQUEST_BYTES)
    application["service"] = service
    application.router.add_get("/healthz", service.health)
    application.router.add_post("/v1/topic", service.topic)
    application.on_startup.append(service.startup)
    application.on_cleanup.append(service.cleanup)
    return application


def main() -> None:
    web.run_app(create_app(), host="0.0.0.0", port=8787, access_log=None)


if __name__ == "__main__":
    main()
