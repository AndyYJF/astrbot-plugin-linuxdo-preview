from __future__ import annotations

import pytest

from sidecar import session_authorize


class _FlakyPage:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls: list[tuple[str, str, int]] = []

    async def goto(
        self,
        url: str,
        *,
        wait_until: str,
        timeout: int,  # noqa: ASYNC109 - mirrors Playwright's public signature
    ) -> None:
        self.calls.append((url, wait_until, timeout))
        if len(self.calls) <= self.failures:
            raise RuntimeError("NS_ERROR_NET_INTERRUPT")


class _GeometryPage:
    def __init__(self, result) -> None:
        self.result = result
        self.script = ""

    async def evaluate(self, script):
        self.script = script
        return self.result


@pytest.mark.asyncio
async def test_login_viewport_self_check_reports_only_safe_dimensions():
    page = _GeometryPage(
        {
            "innerWidth": 1920,
            "innerHeight": 995,
            "outerWidth": 2560,
            "outerHeight": 1392,
            "screenWidth": 2560,
            "screenHeight": 1440,
            "devicePixelRatio": 1,
        }
    )

    summary = await session_authorize._verify_login_viewport(page)

    assert summary == (
        "viewport=1920x995 outer=2560x1392 screen=2560x1440 dpr=1"
    )
    assert "document" not in page.script
    assert "cookie" not in page.script
    assert "localStorage" not in page.script
    assert "location" not in page.script


@pytest.mark.asyncio
async def test_login_viewport_self_check_rejects_clipped_fingerprint_geometry():
    page = _GeometryPage(
        {
            "innerWidth": 2560,
            "innerHeight": 1307,
            "outerWidth": 2560,
            "outerHeight": 1392,
            "screenWidth": 2560,
            "screenHeight": 1440,
            "devicePixelRatio": 1,
        }
    )

    with pytest.raises(RuntimeError, match="unexpected login viewport geometry"):
        await session_authorize._verify_login_viewport(page)


@pytest.mark.asyncio
async def test_home_navigation_retries_transient_failures_then_succeeds():
    page = _FlakyPage(failures=2)

    await session_authorize._goto_home_with_retry(
        page,
        timeout_ms=15_000,
        attempts=3,
        retry_delay_seconds=0,
    )

    assert page.calls == [
        ("https://linux.do/", "domcontentloaded", 15_000),
        ("https://linux.do/", "domcontentloaded", 15_000),
        ("https://linux.do/", "domcontentloaded", 15_000),
    ]


@pytest.mark.asyncio
async def test_home_navigation_stops_after_bounded_attempts():
    page = _FlakyPage(failures=3)

    with pytest.raises(RuntimeError, match="NS_ERROR_NET_INTERRUPT"):
        await session_authorize._goto_home_with_retry(
            page,
            timeout_ms=15_000,
            attempts=3,
            retry_delay_seconds=0,
        )

    assert len(page.calls) == 3
