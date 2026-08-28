from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from time import monotonic
from typing import Any

from .browser import BrowserSessionExpired, LinuxDoBrowser
from .protocol import UpstreamPayloadError, filter_first_post
from .security import bearer_is_valid, load_sidecar_secret, validate_topic_payload

MAX_REQUEST_BYTES = 1_024
MAX_RESPONSE_BYTES = 262_144
REQUESTS_PER_MINUTE = 3
_CHALLENGE_MARKERS = (b"cf-chl-", b"just a moment", b"cloudflare challenge")


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(os.environ.get(name, str(default)))
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))


class SidecarApp:
    def __init__(self) -> None:
        secret_file = os.environ.get(
            "LINUXDO_SECRET_FILE",
            "/run/secrets/astrbot_plugin_linuxdo_preview.json",
        )
        self.secret = load_sidecar_secret(secret_file)
        self.browser = LinuxDoBrowser(
            secret=self.secret,
            timeout_seconds=_bounded_env_int(
                "LINUXDO_BYPARR_TIMEOUT_SECONDS",
                40,
                30,
                330,
            ),
            request_timeout_seconds=_bounded_env_int(
                "LINUXDO_BROWSER_REQUEST_TIMEOUT_SECONDS",
                30,
                5,
                60,
            ),
            max_response_bytes=MAX_RESPONSE_BYTES,
            session_state_file=os.environ.get(
                "LINUXDO_SESSION_STATE_FILE",
                "",
            ),
        )
        self._requests: deque[float] = deque()
        self._rate_lock = asyncio.Lock()

    async def health(self) -> tuple[int, dict[str, str]]:
        return 200, {"status": "ok", "browser": "byparr"}

    async def topic(
        self,
        *,
        authorization: str,
        raw_body: bytes,
    ) -> tuple[int, dict[str, Any]]:
        if not bearer_is_valid(authorization, self.secret.sidecar_token):
            return 401, {"error": "unauthorized"}
        if not raw_body or len(raw_body) > MAX_REQUEST_BYTES:
            status = 413 if len(raw_body) > MAX_REQUEST_BYTES else 400
            error = "request_too_large" if status == 413 else "invalid_request"
            return status, {"error": error}
        try:
            topic_id = validate_topic_payload(json.loads(raw_body))
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return 400, {"error": "invalid_request"}
        async with self._rate_lock:
            now = monotonic()
            while self._requests and self._requests[0] <= now - 60:
                self._requests.popleft()
            if len(self._requests) >= REQUESTS_PER_MINUTE:
                return 429, {"error": "rate_limited"}
            self._requests.append(now)
        try:
            response = await self.browser.fetch_first_post(topic_id)
        except BrowserSessionExpired:
            return 401, {"error": "session_expired"}
        except Exception:
            return 503, {"error": "browser_unavailable"}
        lowered = response.body[:16_384].lower()
        if response.headers.get("cf-mitigated", "").lower() == "challenge" or (
            response.status in {403, 429, 503}
            and any(marker in lowered for marker in _CHALLENGE_MARKERS)
        ):
            return 409, {"error": "clearance_required"}
        if response.status in {401, 403, 404, 429}:
            return response.status, {"error": "upstream_rejected"}
        if response.status != 200:
            return 502, {"error": "upstream_unavailable"}
        try:
            filtered = filter_first_post(response.body, topic_id)
        except UpstreamPayloadError:
            return 502, {"error": "invalid_upstream_payload"}
        return 200, filtered


def create_app() -> Any:
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
    except ImportError as exc:
        raise RuntimeError("Byparr FastAPI runtime is unavailable") from exc

    service = SidecarApp()
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def health():
        status, payload = await service.health()
        return JSONResponse(payload, status_code=status)

    async def topic(request):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BYTES:
                    return JSONResponse(
                        {"error": "request_too_large"},
                        status_code=413,
                    )
            except ValueError:
                return JSONResponse({"error": "invalid_request"}, status_code=400)
        raw_body = await request.body()
        status, payload = await service.topic(
            authorization=request.headers.get("authorization", ""),
            raw_body=raw_body,
        )
        return JSONResponse(payload, status_code=status)

    topic.__annotations__["request"] = Request
    application.add_api_route("/healthz", health, methods=["GET"])
    application.add_api_route("/v1/topic", topic, methods=["POST"])
    return application


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Byparr Uvicorn runtime is unavailable") from exc
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=8787,
        access_log=False,
    )


if __name__ == "__main__":
    main()
