from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from time import monotonic
from typing import Any

from playwright.async_api import BrowserContext, async_playwright

from .protocol import (
    UpstreamPayloadError,
    validate_device_poll_request,
    validate_device_poll_response,
    validate_device_request,
    validate_device_start_response,
)

_HOME_URL = "https://linux.do/"
_START_URL = "https://linux.do/user-api-key/device.json"
_POLL_URL = "https://linux.do/user-api-key/device/poll.json"
_MAX_JSON_BYTES = 65_536
_CF_MARKERS = (b"cf-chl-", b"just a moment", b"cloudflare challenge")


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(os.environ.get(name, str(default)))
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _read_request(path_value: str, *, mode: str) -> dict[str, str]:
    path = Path(path_value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError("device request file is invalid")
    metadata = path.stat()
    if metadata.st_size <= 0 or metadata.st_size > _MAX_JSON_BYTES:
        raise RuntimeError("device request file size is invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("device request file is not valid JSON") from exc
    validator = (
        validate_device_request
        if mode == "start"
        else validate_device_poll_request
    )
    return validator(payload)


def _write_response(path_value: str, payload: dict[str, Any]) -> None:
    path = Path(path_value)
    if not path.is_absolute() or not path.parent.is_dir() or path.parent.is_symlink():
        raise RuntimeError("device response path is invalid")
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    if len(encoded) > _MAX_JSON_BYTES:
        raise RuntimeError("device response is too large")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _is_cf_challenge(status: int, headers: dict[str, str], body: bytes) -> bool:
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    lowered = body[:16_384].lower()
    return status in {403, 429, 503} and any(
        marker in lowered for marker in _CF_MARKERS
    )


async def _post_json(
    context: BrowserContext,
    *,
    url: str,
    payload: dict[str, str],
    timeout_ms: int,
) -> tuple[int, dict[str, str], bytes]:
    response = await context.request.post(
        url,
        data=payload,
        headers={"Accept": "application/json"},
        fail_on_status_code=False,
        timeout=timeout_ms,
    )
    body = await response.body()
    if len(body) > _MAX_JSON_BYTES:
        raise RuntimeError("device endpoint response is too large")
    headers = {key.lower(): value for key, value in response.headers.items()}
    return response.status, headers, body


async def _run() -> None:
    mode = os.environ.get("LINUXDO_DEVICE_MODE", "").strip().lower()
    if mode not in {"start", "poll"}:
        raise RuntimeError("LINUXDO_DEVICE_MODE must be start or poll")
    request_payload = _read_request(
        os.environ.get("LINUXDO_DEVICE_REQUEST_FILE", ""),
        mode=mode,
    )
    response_file = os.environ.get("LINUXDO_DEVICE_RESPONSE_FILE", "")
    profile_dir = os.environ.get(
        "LINUXDO_BROWSER_PROFILE_DIR",
        "/var/lib/linuxdo-browser",
    )
    proxy_server = os.environ.get("LINUXDO_PROXY_SERVER", "").strip()
    timeout_seconds = _bounded_env_int(
        "LINUXDO_DEVICE_TIMEOUT_SECONDS",
        900,
        60,
        1800,
    )
    request_timeout_ms = _bounded_env_int(
        "LINUXDO_DEVICE_REQUEST_TIMEOUT_SECONDS",
        20,
        5,
        60,
    ) * 1000
    retry_seconds = _bounded_env_int(
        "LINUXDO_DEVICE_RETRY_SECONDS",
        10,
        5,
        30,
    )
    launch_options: dict[str, object] = {
        "headless": False,
        "viewport": {"width": 1280, "height": 900},
    }
    if proxy_server:
        launch_options["proxy"] = {"server": proxy_server}

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            profile_dir,
            **launch_options,
        )
        try:
            pages = context.pages
            page = pages[0] if pages else await context.new_page()
            try:
                await page.goto(
                    _HOME_URL,
                    wait_until="domcontentloaded",
                    timeout=request_timeout_ms,
                )
            except Exception:
                pass
            print(
                "浏览器已打开；如出现 Cloudflare 校验，请通过本机 noVNC 手动完成。",
                flush=True,
            )
            endpoint = _START_URL if mode == "start" else _POLL_URL
            deadline = monotonic() + timeout_seconds
            while monotonic() < deadline:
                status, headers, body = await _post_json(
                    context,
                    url=endpoint,
                    payload=request_payload,
                    timeout_ms=request_timeout_ms,
                )
                if _is_cf_challenge(status, headers, body):
                    await asyncio.sleep(retry_seconds)
                    continue
                if status != 200:
                    raise RuntimeError(f"device endpoint HTTP {status}")
                try:
                    parsed = json.loads(body.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError("device endpoint returned invalid JSON") from exc
                if mode == "start":
                    validated = validate_device_start_response(parsed)
                    _write_response(response_file, validated)
                    print("设备授权请求已创建；响应已安全写入挂载目录。", flush=True)
                    return
                validated = validate_device_poll_response(parsed)
                status_name = validated["status"]
                if status_name == "authorization_pending":
                    await asyncio.sleep(retry_seconds)
                    continue
                _write_response(response_file, validated)
                print("设备授权轮询已结束；响应已安全写入挂载目录。", flush=True)
                return
            raise RuntimeError("device authorization browser timeout")
        finally:
            await context.close()


def main() -> None:
    try:
        asyncio.run(_run())
    except (RuntimeError, UpstreamPayloadError) as exc:
        raise SystemExit(f"设备授权浏览器失败：{exc}") from exc


if __name__ == "__main__":
    main()
