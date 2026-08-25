from __future__ import annotations

import pytest

from sidecar import app as app_module
from sidecar.app import SidecarApp
from sidecar.browser import BrowserResponse
from sidecar.security import SidecarSecret


class _FakeBrowser:
    def __init__(self, response: BrowserResponse) -> None:
        self.response = response
        self.topic_ids: list[int] = []

    async def fetch_first_post(self, topic_id: int) -> BrowserResponse:
        self.topic_ids.append(topic_id)
        return self.response


def _service(monkeypatch, response: BrowserResponse) -> SidecarApp:
    monkeypatch.setattr(
        app_module,
        "load_sidecar_secret",
        lambda _path: SidecarSecret(
            "A" * 40,
            "client-id-123456",
            "s" * 43,
        ),
    )
    service = SidecarApp()
    service.browser = _FakeBrowser(response)
    return service


@pytest.mark.asyncio
async def test_sidecar_topic_requires_bearer_before_browser(monkeypatch):
    service = _service(
        monkeypatch,
        BrowserResponse(200, {}, b"{}"),
    )

    status, payload = await service.topic(
        authorization="Bearer wrong",
        raw_body=b'{"topic_id":123}',
    )

    assert (status, payload) == (401, {"error": "unauthorized"})
    assert service.browser.topic_ids == []


@pytest.mark.asyncio
async def test_sidecar_topic_filters_single_byparr_post(monkeypatch):
    service = _service(
        monkeypatch,
        BrowserResponse(
            200,
            {"content-type": "application/json"},
            b'{"post_number":1,"topic_id":123,"raw":"owner"}',
        ),
    )

    status, payload = await service.topic(
        authorization=f"Bearer {'s' * 43}",
        raw_body=b'{"topic_id":123}',
    )

    assert status == 200
    assert payload["posts"][0]["raw"] == "owner"
    assert service.browser.topic_ids == [123]


@pytest.mark.asyncio
async def test_sidecar_topic_maps_browser_challenge_without_body_leak(monkeypatch):
    service = _service(
        monkeypatch,
        BrowserResponse(
            403,
            {"cf-mitigated": "challenge"},
            b"private challenge body",
        ),
    )

    status, payload = await service.topic(
        authorization=f"Bearer {'s' * 43}",
        raw_body=b'{"topic_id":123}',
    )

    assert (status, payload) == (409, {"error": "clearance_required"})
    assert "private" not in str(payload)
