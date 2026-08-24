from __future__ import annotations

import asyncio
from dataclasses import dataclass

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from .security import SidecarSecret, keep_only_cf_cookies

_HOME_URL = "https://linux.do/"


@dataclass(frozen=True, slots=True)
class BrowserResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class LinuxDoBrowser:
    def __init__(
        self,
        *,
        secret: SidecarSecret,
        profile_dir: str,
        proxy_server: str,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> None:
        self._secret = secret
        self._profile_dir = profile_dir
        self._proxy_server = proxy_server
        self._timeout_ms = timeout_seconds * 1000
        self._max_response_bytes = max_response_bytes
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        launch_options: dict[str, object] = {
            "headless": False,
            "viewport": {"width": 1280, "height": 900},
        }
        if self._proxy_server:
            launch_options["proxy"] = {"server": self._proxy_server}
        self._context = await self._playwright.chromium.launch_persistent_context(
            self._profile_dir,
            **launch_options,
        )
        cookies = keep_only_cf_cookies(await self._context.cookies())
        await self._context.clear_cookies()
        if cookies:
            await self._context.add_cookies(cookies)
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        try:
            await self._page.goto(
                _HOME_URL,
                wait_until="domcontentloaded",
                timeout=self._timeout_ms,
            )
        except Exception:
            # The visible browser remains available for manual CF clearance.
            pass

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def fetch_first_post(self, topic_id: int) -> BrowserResponse:
        if self._page is None:
            raise RuntimeError("browser is not ready")
        url = (
            f"https://linux.do/t/{topic_id}/posts.json"
            "?post_number=1&include_raw=true"
        )
        async with self._lock:
            page = self._page

            async def route_request(route) -> None:
                request = route.request
                if request.url != url or not request.is_navigation_request():
                    await route.abort("blockedbyclient")
                    return
                headers = {
                    **request.headers,
                    "accept": "application/json",
                    "user-api-key": self._secret.user_api_key,
                    "user-api-client-id": self._secret.user_api_client_id,
                }
                await route.continue_(headers=headers)

            await page.route("**/*", route_request)
            try:
                response = await page.goto(
                    url,
                    wait_until="commit",
                    timeout=self._timeout_ms,
                )
                if response is None or response.url != url:
                    raise RuntimeError("browser navigation did not stay on fixed URL")
                await response.finished()
                body = await response.body()
                if len(body) > self._max_response_bytes:
                    raise RuntimeError("browser response exceeded byte limit")
                return BrowserResponse(
                    status=response.status,
                    headers={
                        key.lower(): value
                        for key, value in response.headers.items()
                    },
                    body=body,
                )
            finally:
                await page.unroute("**/*", route_request)
