import json

import pytest

from linuxdo_preview.auth import SecretLoadError, load_user_api_credentials


def test_loads_versioned_linuxdo_user_api_secret(tmp_path):
    secret = tmp_path / "linuxdo-user-api.json"
    secret.write_text(
        json.dumps(
            {
                "version": 1,
                "site": "https://linux.do",
                "user_api_key": "A" * 40,
                "user_api_client_id": "client-id-123456",
                "sidecar_token": "s" * 43,
            }
        ),
        encoding="utf-8",
    )

    loaded = load_user_api_credentials(str(secret))

    assert loaded.user_api_key == "A" * 40
    assert loaded.user_api_client_id == "client-id-123456"
    assert loaded.sidecar_token == "s" * 43
    assert loaded.auth_mode == "user_api"


def test_loads_versioned_browser_session_secret_without_user_api_key(tmp_path):
    secret = tmp_path / "linuxdo-browser-session.json"
    secret.write_text(
        json.dumps(
            {
                "version": 2,
                "site": "https://linux.do",
                "auth_mode": "browser_session",
                "sidecar_token": "s" * 43,
                "browser_seed": 123456789,
            }
        ),
        encoding="utf-8",
    )

    loaded = load_user_api_credentials(str(secret))

    assert loaded.auth_mode == "browser_session"
    assert loaded.user_api_key == ""
    assert loaded.user_api_client_id == ""
    assert loaded.sidecar_token == "s" * 43
    assert loaded.browser_seed == 123456789


def test_browser_session_secret_rejects_user_api_fields(tmp_path):
    secret = tmp_path / "mixed-secret.json"
    secret.write_text(
        json.dumps(
            {
                "version": 2,
                "site": "https://linux.do",
                "auth_mode": "browser_session",
                "sidecar_token": "s" * 43,
                "browser_seed": 123456789,
                "user_api_key": "A" * 40,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SecretLoadError, match="User API"):
        load_user_api_credentials(str(secret))


def test_rejects_relative_or_wrong_site_secret(tmp_path):
    with pytest.raises(SecretLoadError, match="absolute"):
        load_user_api_credentials("relative-secret.json")

    secret = tmp_path / "wrong-site.json"
    secret.write_text(
        json.dumps(
            {
                "version": 1,
                "site": "https://example.com",
                "user_api_key": "A" * 40,
                "user_api_client_id": "client-id-123456",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SecretLoadError, match="metadata"):
        load_user_api_credentials(str(secret))


def test_rejects_symlink_secret_when_supported(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable in this environment")

    with pytest.raises(SecretLoadError, match="regular file"):
        load_user_api_credentials(str(link))
