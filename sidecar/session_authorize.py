from __future__ import annotations

import asyncio
import os
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from .browser import (
    _open_byparr_browser,
    _prepare_linuxdo_page,
    _session_is_authenticated,
)
from .security import (
    AUTH_MODE_BROWSER_SESSION,
    load_sidecar_secret,
)
from .session_state import (
    SessionStateError,
    load_session_state,
    write_session_state,
)

_HOME_URL = "https://linux.do/"
_EXPECTED_LOGIN_LAYOUT = {
    "innerWidth": 1920,
    "innerHeight": 995,
    "devicePixelRatio": 1,
}
_LOGIN_GEOMETRY_FIELDS = (
    "innerWidth",
    "innerHeight",
    "outerWidth",
    "outerHeight",
    "screenWidth",
    "screenHeight",
    "devicePixelRatio",
)


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(os.environ.get(name, str(default)))
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _optional_existing_state(path_value: str):
    path = Path(path_value)
    if not path.exists():
        return None
    return load_session_state(path_value)


async def _verify_login_viewport(page) -> str:
    geometry = await page.evaluate(
        """() => ({
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight,
            screenWidth: window.screen.width,
            screenHeight: window.screen.height,
            devicePixelRatio: window.devicePixelRatio,
        })"""
    )
    if not isinstance(geometry, dict):
        raise RuntimeError("unexpected login viewport geometry")
    for field in _LOGIN_GEOMETRY_FIELDS:
        value = geometry.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError("unexpected login viewport geometry")
        if value <= 0:
            raise RuntimeError("unexpected login viewport geometry")
    for field, expected in _EXPECTED_LOGIN_LAYOUT.items():
        value = geometry[field]
        if value != expected:
            raise RuntimeError(
                "unexpected login viewport geometry: "
                f"{field}={value}, expected={expected}"
            )
    return (
        f"viewport={geometry['innerWidth']}x{geometry['innerHeight']} "
        f"outer={geometry['outerWidth']}x{geometry['outerHeight']} "
        f"screen={geometry['screenWidth']}x{geometry['screenHeight']} "
        f"dpr={geometry['devicePixelRatio']}"
    )


async def _find_authenticated_page(context, timeout_ms: int):
    for page in reversed(context.pages):
        parts = urlsplit(str(page.url))
        if parts.scheme != "https" or parts.hostname != "linux.do":
            continue
        try:
            if await _session_is_authenticated(page, timeout_ms):
                return page
        except Exception:
            continue
    return None


async def _goto_home_with_retry(
    page,
    *,
    timeout_ms: int,
    attempts: int = 3,
    retry_delay_seconds: float = 1,
) -> None:
    for attempt in range(attempts):
        try:
            await page.goto(
                _HOME_URL,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            return
        except Exception:
            if attempt + 1 >= attempts:
                raise
            await asyncio.sleep(retry_delay_seconds)


async def _run() -> None:
    secret_file = os.environ.get(
        "LINUXDO_SECRET_FILE",
        "/run/secrets/astrbot_plugin_linuxdo_preview.json",
    )
    secret = load_sidecar_secret(secret_file)
    if (
        secret.auth_mode != AUTH_MODE_BROWSER_SESSION
        or secret.browser_seed is None
    ):
        raise RuntimeError("session login requires a version-2 browser secret")
    state_file = os.environ.get("LINUXDO_SESSION_STATE_FILE", "")
    if not state_file:
        raise RuntimeError("LINUXDO_SESSION_STATE_FILE is required")
    existing_state = _optional_existing_state(state_file)
    timeout_seconds = _bounded_env_int(
        "LINUXDO_SESSION_LOGIN_TIMEOUT_SECONDS",
        1800,
        300,
        3600,
    )
    check_timeout_ms = (
        _bounded_env_int(
            "LINUXDO_BROWSER_REQUEST_TIMEOUT_SECONDS",
            15,
            5,
            30,
        )
        * 1000
    )
    async with _open_byparr_browser(
        storage_state=existing_state,
        browser_seed=secret.browser_seed,
        headless=False,
    ) as dependency:
        geometry_summary = await _verify_login_viewport(dependency.page)
        print(
            f"隔离登录浏览器视口自检通过：{geometry_summary}",
            flush=True,
        )
        await _prepare_linuxdo_page(
            dependency,
            _bounded_env_int(
                "LINUXDO_BYPARR_TIMEOUT_SECONDS",
                180,
                30,
                330,
            ),
        )
        await _goto_home_with_retry(
            dependency.page,
            timeout_ms=check_timeout_ms,
        )
        print(
            "隔离登录浏览器已启动。请只在本机回环 noVNC 页面中完成 Linux.do 登录；"
            "程序不会读取或打印密码、MFA、Cookie。",
            flush=True,
        )
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            page = await _find_authenticated_page(
                dependency.context,
                check_timeout_ms,
            )
            if page is not None:
                state = await dependency.context.storage_state()
                write_session_state(state_file, state)
                print(
                    "Linux.do 登录已确认；隔离会话状态已按私有文件保存。",
                    flush=True,
                )
                return
            await asyncio.sleep(3)
        raise RuntimeError("interactive Linux.do login timed out")


def main() -> None:
    try:
        asyncio.run(_run())
    except (RuntimeError, SessionStateError) as exc:
        raise SystemExit(f"Linux.do 隔离登录失败：{exc}") from exc


if __name__ == "__main__":
    main()
