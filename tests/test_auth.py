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
            }
        ),
        encoding="utf-8",
    )

    loaded = load_user_api_credentials(str(secret))

    assert loaded.user_api_key == "A" * 40
    assert loaded.user_api_client_id == "client-id-123456"


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
