import base64
from urllib.parse import parse_qs, urlparse

import pytest

from tools.user_api_authorize import (
    PROJECT_ROOT,
    AuthorizationError,
    _build_authorization_url,
    _decode_payload,
    _parse_redirect_payload,
    _require_outside_project,
)


def test_authorization_url_requests_only_read_and_oaep():
    url = _build_authorization_url(
        public_key="PUBLIC KEY",
        client_id="client-123",
        nonce="nonce-123",
        auth_redirect="discourse://auth_redirect",
    )
    parsed = urlparse(url)
    values = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://linux.do/user-api-key/new"
    )
    assert values["scopes"] == ["read"]
    assert values["padding"] == ["oaep"]
    assert values["client_id"] == ["client-123"]
    assert values["nonce"] == ["nonce-123"]


def test_redirect_parser_accepts_only_expected_destination_and_one_payload():
    encrypted = b"encrypted-user-api-key"
    encoded = base64.b64encode(encrypted).decode("ascii")

    assert _parse_redirect_payload(
        f"discourse://auth_redirect?payload={encoded}",
        "discourse://auth_redirect",
    ) == encrypted

    with pytest.raises(AuthorizationError, match="destination"):
        _parse_redirect_payload(
            f"https://example.com/callback?payload={encoded}",
            "discourse://auth_redirect",
        )
    with pytest.raises(AuthorizationError, match="one payload"):
        _parse_redirect_payload(
            "discourse://auth_redirect?payload=a&payload=b",
            "discourse://auth_redirect",
        )


def test_payload_decoder_accepts_urlsafe_base64_without_padding():
    encoded = base64.urlsafe_b64encode(b"payload-data").decode("ascii").rstrip("=")
    assert _decode_payload(encoded) == b"payload-data"


def test_secret_work_paths_must_stay_outside_git_project(tmp_path):
    with pytest.raises(AuthorizationError, match="outside the Git project"):
        _require_outside_project(PROJECT_ROOT / "secret.json", label="secret")
    _require_outside_project(tmp_path / "secret.json", label="secret")
