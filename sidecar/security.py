from __future__ import annotations

import hmac
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MAX_SECRET_BYTES = 16_384
_CLIENT_ID_RE = re.compile(r"[A-Za-z0-9._-]{8,128}")
_USER_API_KEY_RE = re.compile(r"[A-Za-z0-9+/=_-]{20,512}")
_SIDECAR_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")
_ALLOWED_CF_COOKIES = frozenset({"cf_clearance", "__cf_bm", "_cfuvid"})
_COOKIE_FIELDS = (
    "name",
    "value",
    "url",
    "domain",
    "path",
    "expires",
    "httpOnly",
    "secure",
    "sameSite",
    "partitionKey",
)


class SidecarConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SidecarSecret:
    user_api_key: str
    user_api_client_id: str
    sidecar_token: str


def load_sidecar_secret(secret_file: str) -> SidecarSecret:
    path = Path(secret_file)
    if not path.is_absolute():
        raise SidecarConfigError("secret path must be absolute")
    try:
        if path.is_symlink() or not path.is_file():
            raise SidecarConfigError("secret path is not a regular file")
        metadata = path.stat()
        if metadata.st_size <= 0 or metadata.st_size > _MAX_SECRET_BYTES:
            raise SidecarConfigError("secret file size is invalid")
        if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise SidecarConfigError("secret permissions are too broad")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except SidecarConfigError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SidecarConfigError("secret file could not be loaded") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 1
        or payload.get("site") != "https://linux.do"
    ):
        raise SidecarConfigError("secret metadata is invalid")
    key = payload.get("user_api_key")
    client_id = payload.get("user_api_client_id")
    token = payload.get("sidecar_token")
    if not isinstance(key, str) or not _USER_API_KEY_RE.fullmatch(key):
        raise SidecarConfigError("user API key format is invalid")
    if not isinstance(client_id, str) or not _CLIENT_ID_RE.fullmatch(client_id):
        raise SidecarConfigError("client ID format is invalid")
    if not isinstance(token, str) or not _SIDECAR_TOKEN_RE.fullmatch(token):
        raise SidecarConfigError("sidecar token format is invalid")
    return SidecarSecret(key, client_id, token)


def bearer_is_valid(header: str, expected_token: str) -> bool:
    prefix = "Bearer "
    if not isinstance(header, str) or not header.startswith(prefix):
        return False
    candidate = header[len(prefix) :]
    return hmac.compare_digest(candidate, expected_token)


def validate_topic_payload(payload: Any) -> int:
    if not isinstance(payload, dict) or set(payload) != {"topic_id"}:
        raise ValueError("request must contain only topic_id")
    topic_id = payload.get("topic_id")
    if isinstance(topic_id, bool) or not isinstance(topic_id, int):
        raise ValueError("topic_id must be an integer")
    if topic_id < 1 or topic_id > 2_147_483_647:
        raise ValueError("topic_id is out of range")
    return topic_id


def keep_only_cf_cookies(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for cookie in cookies:
        if cookie.get("name") not in _ALLOWED_CF_COOKIES:
            continue
        domain = str(cookie.get("domain", "")).lower().lstrip(".")
        if domain != "linux.do" and not domain.endswith(".linux.do"):
            continue
        kept.append({key: cookie[key] for key in _COOKIE_FIELDS if key in cookie})
    return kept
