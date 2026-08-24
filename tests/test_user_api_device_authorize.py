import pytest

from tools.user_api_authorize import AuthorizationError
from tools.user_api_device_authorize import (
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
