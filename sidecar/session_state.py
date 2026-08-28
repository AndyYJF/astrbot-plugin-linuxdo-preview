from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

MAX_SESSION_STATE_BYTES = 524_288
_LINUXDO_HOST = "linux.do"
_LINUXDO_ORIGIN = "https://linux.do"
_COOKIE_REQUIRED_KEYS = frozenset(
    {
        "name",
        "value",
        "domain",
        "path",
        "expires",
        "httpOnly",
        "secure",
        "sameSite",
    }
)
_COOKIE_OPTIONAL_KEYS = frozenset({"partitionKey"})


class SessionStateError(RuntimeError):
    pass


def _session_path(path_value: str, *, must_exist: bool) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        raise SessionStateError("session state path must be absolute")
    if path.is_symlink():
        raise SessionStateError("session state path must not be a symlink")
    if must_exist:
        if not path.is_file():
            raise SessionStateError("session state path is not a regular file")
        metadata = path.stat()
        if metadata.st_size <= 0 or metadata.st_size > MAX_SESSION_STATE_BYTES:
            raise SessionStateError("session state file size is invalid")
        if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise SessionStateError("session state permissions are too broad")
    elif (
        not path.parent.is_absolute()
        or not path.parent.is_dir()
        or path.parent.is_symlink()
    ):
        raise SessionStateError("session state parent directory is invalid")
    elif path.exists() and not path.is_file():
        raise SessionStateError("session state target is not a regular file")
    return path


def _validate_cookie(cookie: Any) -> dict[str, Any]:
    if not isinstance(cookie, dict):
        raise SessionStateError("session state cookie is invalid")
    keys = set(cookie)
    if not _COOKIE_REQUIRED_KEYS.issubset(keys) or not keys.issubset(
        _COOKIE_REQUIRED_KEYS | _COOKIE_OPTIONAL_KEYS
    ):
        raise SessionStateError("session state cookie fields are invalid")
    for key in ("name", "value", "domain", "path", "sameSite"):
        if not isinstance(cookie.get(key), str):
            raise SessionStateError("session state cookie value is invalid")
    for key in ("httpOnly", "secure"):
        if not isinstance(cookie.get(key), bool):
            raise SessionStateError("session state cookie flag is invalid")
    expires = cookie.get("expires")
    if isinstance(expires, bool) or not isinstance(expires, int | float):
        raise SessionStateError("session state cookie expiry is invalid")
    domain = str(cookie["domain"]).lstrip(".").casefold()
    if domain != _LINUXDO_HOST:
        raise SessionStateError("session state cookie origin is not allowed")
    if cookie["sameSite"] not in {"Strict", "Lax", "None"}:
        raise SessionStateError("session state cookie sameSite is invalid")
    if "partitionKey" in cookie and not isinstance(cookie["partitionKey"], str):
        raise SessionStateError("session state partition key is invalid")
    return dict(cookie)


def _validate_origin(origin: Any) -> dict[str, Any]:
    if (
        not isinstance(origin, dict)
        or set(origin) != {"origin", "localStorage"}
        or origin.get("origin") != _LINUXDO_ORIGIN
        or not isinstance(origin.get("localStorage"), list)
    ):
        raise SessionStateError("session state origin is invalid")
    items: list[dict[str, str]] = []
    for item in origin["localStorage"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "value"}
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("value"), str)
        ):
            raise SessionStateError("session local storage is invalid")
        items.append({"name": item["name"], "value": item["value"]})
    return {"origin": _LINUXDO_ORIGIN, "localStorage": items}


def _validate_collections(payload: Any) -> tuple[list[Any], list[Any]]:
    if not isinstance(payload, dict) or set(payload) != {"cookies", "origins"}:
        raise SessionStateError("session state root is invalid")
    raw_cookies = payload.get("cookies")
    raw_origins = payload.get("origins")
    if not isinstance(raw_cookies, list) or not isinstance(raw_origins, list):
        raise SessionStateError("session state collections are invalid")
    return raw_cookies, raw_origins


def _finalize_state(
    cookies: list[dict[str, Any]],
    origins: list[dict[str, Any]],
) -> dict[str, Any]:
    if not cookies:
        raise SessionStateError("session state contains no Linux.do cookies")
    normalized = {"cookies": cookies, "origins": origins}
    encoded = json.dumps(normalized, ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_SESSION_STATE_BYTES:
        raise SessionStateError("session state payload is too large")
    return normalized


def validate_session_state(payload: Any) -> dict[str, Any]:
    raw_cookies, raw_origins = _validate_collections(payload)
    cookies = [_validate_cookie(cookie) for cookie in raw_cookies]
    origins = [_validate_origin(origin) for origin in raw_origins]
    return _finalize_state(cookies, origins)


def sanitize_session_state(payload: Any) -> dict[str, Any]:
    raw_cookies, raw_origins = _validate_collections(payload)
    cookies: list[dict[str, Any]] = []
    for cookie in raw_cookies:
        if not isinstance(cookie, dict) or not isinstance(cookie.get("domain"), str):
            raise SessionStateError("session state cookie is invalid")
        if cookie["domain"].lstrip(".").casefold() == _LINUXDO_HOST:
            cookies.append(_validate_cookie(cookie))
    origins: list[dict[str, Any]] = []
    for origin in raw_origins:
        if not isinstance(origin, dict) or not isinstance(origin.get("origin"), str):
            raise SessionStateError("session state origin is invalid")
        if origin["origin"] == _LINUXDO_ORIGIN:
            origins.append(_validate_origin(origin))
    return _finalize_state(cookies, origins)


def load_session_state(path_value: str) -> dict[str, Any]:
    path = _session_path(path_value, must_exist=True)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SessionStateError("session state file could not be loaded") from exc
    return validate_session_state(payload)


def write_session_state(path_value: str, payload: Any) -> None:
    path = _session_path(path_value, must_exist=False)
    normalized = sanitize_session_state(payload)
    encoded = (
        json.dumps(normalized, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        else:
            os.chmod(temporary_path, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception as exc:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
        raise SessionStateError("session state file could not be written") from exc
