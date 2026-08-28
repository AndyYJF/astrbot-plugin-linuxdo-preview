from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

_MAX_SECRET_BYTES = 16_384
_CLIENT_ID_RE = re.compile(r"[A-Za-z0-9._-]{8,128}")
_USER_API_KEY_RE = re.compile(r"[A-Za-z0-9+/=_-]{20,512}")
_SIDECAR_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")
_AUTH_MODE_USER_API = "user_api"
_AUTH_MODE_BROWSER_SESSION = "browser_session"


class SecretLoadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class UserApiCredentials:
    user_api_key: str
    user_api_client_id: str
    sidecar_token: str = ""
    auth_mode: str = _AUTH_MODE_USER_API
    browser_seed: int | None = None


def load_user_api_credentials(secret_file: str) -> UserApiCredentials:
    path = Path(secret_file)
    if not path.is_absolute():
        raise SecretLoadError("secret path must be absolute")
    try:
        if path.is_symlink() or not path.is_file():
            raise SecretLoadError("secret path is not a regular file")
        metadata = path.stat()
        if metadata.st_size <= 0 or metadata.st_size > _MAX_SECRET_BYTES:
            raise SecretLoadError("secret file size is invalid")
        if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise SecretLoadError("secret file permissions are too broad")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except SecretLoadError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SecretLoadError("secret file could not be loaded") from exc

    if not isinstance(payload, dict):
        raise SecretLoadError("secret payload must be an object")
    version = payload.get("version")
    if version not in {1, 2} or payload.get("site") != "https://linux.do":
        raise SecretLoadError("secret payload metadata is invalid")
    if version == 2:
        if payload.get("auth_mode") != _AUTH_MODE_BROWSER_SESSION:
            raise SecretLoadError("secret authentication mode is invalid")
        sidecar_token = payload.get("sidecar_token")
        browser_seed = payload.get("browser_seed")
        if not isinstance(sidecar_token, str) or not _SIDECAR_TOKEN_RE.fullmatch(
            sidecar_token
        ):
            raise SecretLoadError("sidecar token format is invalid")
        if (
            isinstance(browser_seed, bool)
            or not isinstance(browser_seed, int)
            or not 1 <= browser_seed <= 2_147_483_647
        ):
            raise SecretLoadError("browser seed is invalid")
        if "user_api_key" in payload or "user_api_client_id" in payload:
            raise SecretLoadError("browser session secret contains User API fields")
        return UserApiCredentials(
            user_api_key="",
            user_api_client_id="",
            sidecar_token=sidecar_token,
            auth_mode=_AUTH_MODE_BROWSER_SESSION,
            browser_seed=browser_seed,
        )

    user_api_key = payload.get("user_api_key")
    client_id = payload.get("user_api_client_id")
    if not isinstance(user_api_key, str) or not _USER_API_KEY_RE.fullmatch(
        user_api_key
    ):
        raise SecretLoadError("user API key format is invalid")
    if not isinstance(client_id, str) or not _CLIENT_ID_RE.fullmatch(client_id):
        raise SecretLoadError("user API client ID format is invalid")
    sidecar_token = payload.get("sidecar_token", "")
    if not isinstance(sidecar_token, str) or (
        sidecar_token and not _SIDECAR_TOKEN_RE.fullmatch(sidecar_token)
    ):
        raise SecretLoadError("sidecar token format is invalid")
    return UserApiCredentials(
        user_api_key=user_api_key,
        user_api_client_id=client_id,
        sidecar_token=sidecar_token,
        auth_mode=_AUTH_MODE_USER_API,
    )
