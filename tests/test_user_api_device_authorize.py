import argparse
import json

import pytest

from tools.user_api_authorize import AuthorizationError
from tools.user_api_device_authorize import (
    _record_browser,
    _validate_device_response,
    _validate_proxy,
)


def test_validates_device_response_contract():
    payload = {
        "device_code": "a" * 64,
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://linux.do/user-api-key/activate",
        "verification_uri_with_request": (
            "https://linux.do/user-api-key/activate?request=abcdefgh"
        ),
        "expires_in": 600,
        "interval": 5,
    }
    assert _validate_device_response(payload) is payload

    with pytest.raises(AuthorizationError, match="fields"):
        _validate_device_response({**payload, "interval": 0})
    with pytest.raises(AuthorizationError, match="fields"):
        _validate_device_response(
            {**payload, "verification_uri": "https://example.com/activate"}
        )


def test_proxy_rejects_credentials_and_non_http_schemes():
    assert _validate_proxy("") == ""
    assert _validate_proxy("http://127.0.0.1:7890") == (
        "http://127.0.0.1:7890"
    )
    with pytest.raises(AuthorizationError, match="without credentials"):
        _validate_proxy("http://user:password@127.0.0.1:7890")
    with pytest.raises(AuthorizationError, match="HTTP"):
        _validate_proxy("socks5://127.0.0.1:7890")


def test_record_browser_response_file_creates_minimal_poll_request(tmp_path):
    session_dir = tmp_path / "device-browser-test"
    session_dir.mkdir()
    private_key = session_dir / "private-key.pem"
    private_key.write_text("test-private-key", encoding="ascii")
    (session_dir / "state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "flow": "device-browser-prepared",
                "site": "https://linux.do",
                "client_id": "a" * 64,
                "nonce": "nonce-value-123456",
                "private_key_file": str(private_key),
            }
        ),
        encoding="utf-8",
    )
    response_file = session_dir / "device-response.json"
    response_file.write_text(
        json.dumps(
            {
                "device_code": "b" * 64,
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://linux.do/user-api-key/activate",
                "verification_uri_with_request": (
                    "https://linux.do/user-api-key/activate?request=opaque"
                ),
                "expires_in": 600,
                "interval": 5,
            }
        ),
        encoding="utf-8",
    )

    _record_browser(
        argparse.Namespace(
            session_dir=str(session_dir),
            response_file=str(response_file),
        )
    )

    state = json.loads((session_dir / "state.json").read_text(encoding="utf-8"))
    poll_request = json.loads(
        (session_dir / "poll-request.json").read_text(encoding="utf-8")
    )
    assert state["flow"] == "device-browser"
    assert state["device_code"] == "b" * 64
    assert poll_request == {"device_code": "b" * 64}
    assert not response_file.exists()
