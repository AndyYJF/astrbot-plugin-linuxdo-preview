from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from sidecar import browser as browser_module
from sidecar.browser import (
    LinuxDoBrowser,
    _parse_browser_result,
    _validate_fixed_action,
)
from sidecar.security import SidecarSecret


class _FakePage:
    def __init__(self, result):
        self.result = result
        self.script = None
        self.argument = None

    async def evaluate(self, script, argument):
        self.script = script
        self.argument = argument
        return self.result


def test_byparr_action_validator_rejects_arbitrary_urls():
    _validate_fixed_action(
        "topic",
        "https://linux.do/posts/by_number/123/1.json?include_raw=true",
    )
    _validate_fixed_action(
        "device_start",
        "https://linux.do/user-api-key/device.json",
    )
    with pytest.raises(RuntimeError):
        _validate_fixed_action("topic", "https://example.com/123")
    with pytest.raises(RuntimeError):
        _validate_fixed_action("delete", "https://linux.do/")


def test_byparr_result_rejects_redirects_and_oversized_payloads():
    result = {
        "status": 200,
        "url": "https://linux.do/fixed.json",
        "headers": {"content-type": "application/json"},
        "body": '{"ok":true}',
        "tooLarge": False,
    }
    parsed = _parse_browser_result(
        result,
        expected_url="https://linux.do/fixed.json",
        max_response_bytes=128,
    )
    assert parsed.body == b'{"ok":true}'
    with pytest.raises(RuntimeError, match="fields"):
        _parse_browser_result(
            {**result, "url": "https://example.com/redirect"},
            expected_url="https://linux.do/fixed.json",
            max_response_bytes=128,
        )
    with pytest.raises(RuntimeError, match="too large"):
        _parse_browser_result(
            {**result, "tooLarge": True},
            expected_url="https://linux.do/fixed.json",
            max_response_bytes=128,
        )


@pytest.mark.asyncio
async def test_topic_request_stays_in_byparr_page_with_fixed_headers(monkeypatch):
    fixed_url = "https://linux.do/posts/by_number/123/1.json?include_raw=true"
    page = _FakePage(
        {
            "status": 200,
            "url": fixed_url,
            "headers": {"content-type": "application/json"},
            "body": '{"post_number":1,"topic_id":123,"raw":"正文"}',
            "tooLarge": False,
        }
    )

    @asynccontextmanager
    async def fake_browser_provider():
        yield SimpleNamespace(page=page)

    async def fake_prepare(_dependency, _timeout_seconds):
        return 50_000

    monkeypatch.setattr(
        browser_module,
        "_open_byparr_browser",
        fake_browser_provider,
    )
    monkeypatch.setattr(
        browser_module,
        "_prepare_linuxdo_page",
        fake_prepare,
    )
    browser = LinuxDoBrowser(
        secret=SidecarSecret("A" * 40, "client-id-123456", "s" * 43),
        timeout_seconds=120,
        request_timeout_seconds=30,
        max_response_bytes=262_144,
    )

    response = await browser.fetch_first_post(123)

    assert response.status == 200
    assert page.argument == {
        "action": "topic",
        "url": fixed_url,
        "payload": {},
        "userApiKey": "A" * 40,
        "userApiClientId": "client-id-123456",
        "timeoutMs": 30_000,
        "maxBytes": 262_144,
    }
    assert 'redirect: "error"' in page.script
    assert 'method: "GET"' in page.script
    assert 'method: "POST"' in page.script
