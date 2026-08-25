from __future__ import annotations

import pytest

from sidecar.browser import BrowserResponse
from sidecar.device_authorize import (
    _POLL_URL,
    _START_URL,
    _is_cf_challenge,
    _post_json,
)


class _FakeBrowser:
    def __init__(self) -> None:
        self.calls = []

    async def post_device(self, mode, payload):
        self.calls.append((mode, payload))
        return BrowserResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=b'{"ok":true}',
        )


@pytest.mark.asyncio
async def test_device_post_uses_only_fixed_byparr_actions():
    browser = _FakeBrowser()
    start = await _post_json(
        browser,
        url=_START_URL,
        payload={"scopes": "read"},
    )
    poll = await _post_json(
        browser,
        url=_POLL_URL,
        payload={"device_code": "a" * 64},
    )

    assert browser.calls == [
        ("start", {"scopes": "read"}),
        ("poll", {"device_code": "a" * 64}),
    ]
    assert start == poll == (
        200,
        {"content-type": "application/json"},
        b'{"ok":true}',
    )


@pytest.mark.asyncio
async def test_device_post_rejects_nonfixed_url():
    with pytest.raises(RuntimeError, match="not allowed"):
        await _post_json(
            _FakeBrowser(),
            url="https://example.com/device.json",
            payload={"scopes": "read"},
        )


def test_device_challenge_detection_is_bounded_and_explicit():
    assert _is_cf_challenge(403, {"cf-mitigated": "challenge"}, b"") is True
    assert _is_cf_challenge(503, {}, b"<title>Just a moment</title>") is True
    assert _is_cf_challenge(200, {}, b"challenge-platform") is False
