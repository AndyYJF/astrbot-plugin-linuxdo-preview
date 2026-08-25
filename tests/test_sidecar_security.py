import pytest

from sidecar.protocol import (
    UpstreamPayloadError,
    filter_first_post,
    validate_device_poll_request,
    validate_device_poll_response,
    validate_device_request,
    validate_device_start_response,
)
from sidecar.security import (
    bearer_is_valid,
    keep_only_cf_cookies,
    validate_topic_payload,
)


def test_sidecar_request_accepts_only_one_numeric_topic_id():
    assert validate_topic_payload({"topic_id": 123}) == 123
    for payload in (
        {"topic_id": "123"},
        {"topic_id": 123, "url": "https://example.com"},
        {"url": "https://linux.do/t/123"},
    ):
        with pytest.raises(ValueError):
            validate_topic_payload(payload)


def test_sidecar_bearer_and_cookie_filter_are_fail_closed():
    token = "s" * 43
    assert bearer_is_valid(f"Bearer {token}", token) is True
    assert bearer_is_valid("Bearer wrong", token) is False
    cookies = keep_only_cf_cookies(
        [
            {"name": "cf_clearance", "value": "clear", "domain": ".linux.do"},
            {"name": "_forum_session", "value": "session", "domain": "linux.do"},
            {"name": "cf_clearance", "value": "foreign", "domain": "example.com"},
        ]
    )
    assert cookies == [
        {"name": "cf_clearance", "value": "clear", "domain": ".linux.do"}
    ]


def test_sidecar_filters_to_exact_first_post():
    result = filter_first_post(
        b'{"title":"Title","posts":['
        b'{"post_number":2,"topic_id":123,"raw":"reply"},'
        b'{"post_number":1,"topic_id":123,"raw":"owner"}]}',
        123,
    )
    assert result["posts"] == [
        {
            "post_number": 1,
            "topic_id": 123,
            "topic_title": "Title",
            "category_name": "",
            "raw": "owner",
        }
    ]
    with pytest.raises(UpstreamPayloadError):
        filter_first_post(b'{"posts":[]}', 123)


def test_sidecar_accepts_only_matching_single_post_payload():
    result = filter_first_post(
        b'{"post_number":1,"topic_id":123,"raw":"owner"}',
        123,
    )
    assert result["posts"][0]["raw"] == "owner"
    with pytest.raises(UpstreamPayloadError):
        filter_first_post(
            b'{"post_number":1,"topic_id":999,"raw":"foreign"}',
            123,
        )


def test_sidecar_device_bootstrap_accepts_only_fixed_read_protocol():
    public_key = (
        "-----BEGIN PUBLIC KEY-----\n"
        + "A" * 300
        + "\n-----END PUBLIC KEY-----\n"
    )
    request = {
        "application_name": "AstrBot Linux.do Preview",
        "client_id": "a" * 64,
        "scopes": "read",
        "public_key": public_key,
        "nonce": "nonce-value-123456",
        "padding": "oaep",
    }
    assert validate_device_request(request) == request
    with pytest.raises(UpstreamPayloadError):
        validate_device_request({**request, "scopes": "read,write"})
    with pytest.raises(UpstreamPayloadError):
        validate_device_request({**request, "url": "https://example.com"})


def test_sidecar_device_bootstrap_validates_start_and_poll_contracts():
    start_response = {
        "device_code": "b" * 64,
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://linux.do/user-api-key/activate",
        "verification_uri_with_request": (
            "https://linux.do/user-api-key/activate?request=opaque"
        ),
        "expires_in": 600,
        "interval": 5,
    }
    assert validate_device_start_response(start_response) is start_response
    assert validate_device_poll_request({"device_code": "b" * 64}) == {
        "device_code": "b" * 64
    }
    pending = {"status": "authorization_pending"}
    authorized = {"status": "authorized", "payload": "A" * 32}
    assert validate_device_poll_response(pending) is pending
    assert validate_device_poll_response(authorized) is authorized
    with pytest.raises(UpstreamPayloadError):
        validate_device_poll_response({"status": "authorized", "payload": "short"})
