from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from sidecar import browser as browser_module
from sidecar.browser import (
    _SESSION_CURRENT_SCRIPT,
    LinuxDoBrowser,
    _browser_context_options,
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


class _FakeContext:
    def __init__(self, state):
        self.state = state

    async def storage_state(self):
        return self.state


def test_headful_login_context_follows_the_real_browser_window():
    state = {"cookies": [], "origins": []}

    options = _browser_context_options(storage_state=state, headless=False)

    assert options == {
        "storage_state": state,
        "viewport": {"width": 1920, "height": 995},
        "screen": {"width": 1920, "height": 1080},
    }


def test_headless_fetch_context_keeps_the_fingerprint_viewport():
    state = {"cookies": [], "origins": []}

    options = _browser_context_options(storage_state=state, headless=True)

    assert options == {"storage_state": state}


def test_session_check_accepts_discourse_wrapped_current_user_shape():
    # The live Linux.do response wraps the user as {"current_user": {...}};
    # the bare root {"id": ...} shape is kept as an accepted fallback.
    assert "payload.current_user" in _SESSION_CURRENT_SCRIPT
    assert "Number.isInteger(currentUser.id)" in _SESSION_CURRENT_SCRIPT
    assert "Number.isInteger(payload.id)" in _SESSION_CURRENT_SCRIPT


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
    async def fake_browser_provider(**_kwargs):
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


@pytest.mark.asyncio
async def test_session_topic_loads_state_checks_login_and_omits_user_api_headers(
    monkeypatch,
    tmp_path,
):
    fixed_url = "https://linux.do/posts/by_number/123/1.json?include_raw=true"
    state = {
        "cookies": [
            {
                "name": "_forum_session",
                "value": "opaque",
                "domain": ".linux.do",
                "path": "/",
                "expires": -1,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }
    state_file = tmp_path / "linuxdo-storage-state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")

    class SessionPage(_FakePage):
        async def evaluate(self, script, argument):
            if "session/current.json" in script:
                return {"ok": True, "authenticated": True}
            return await super().evaluate(script, argument)

    page = SessionPage(
        {
            "status": 200,
            "url": fixed_url,
            "headers": {"content-type": "application/json"},
            "body": '{"post_number":1,"topic_id":123,"raw":"正文"}',
            "tooLarge": False,
        }
    )
    captured = {}

    @asynccontextmanager
    async def fake_browser_provider(**kwargs):
        captured.update(kwargs)
        yield SimpleNamespace(page=page, context=_FakeContext(state))

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
        secret=SidecarSecret(
            "",
            "",
            "s" * 43,
            "browser_session",
            246813579,
        ),
        timeout_seconds=120,
        request_timeout_seconds=30,
        max_response_bytes=262_144,
        session_state_file=str(state_file),
    )

    response = await browser.fetch_first_post(123)

    assert response.status == 200
    assert captured["storage_state"] == state
    assert captured["browser_seed"] == 246813579
    assert page.argument["userApiKey"] == ""
    assert page.argument["userApiClientId"] == ""
