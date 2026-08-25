from __future__ import annotations

import json
import re
from typing import Any

_HEX_64_RE = re.compile(r"[0-9a-fA-F]{64}")
_USER_CODE_RE = re.compile(r"[A-Za-z0-9-]{4,32}")
_DEVICE_REQUEST_FIELDS = frozenset(
    {
        "application_name",
        "client_id",
        "scopes",
        "public_key",
        "nonce",
        "padding",
    }
)


class UpstreamPayloadError(RuntimeError):
    pass


def validate_device_request(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != _DEVICE_REQUEST_FIELDS:
        raise UpstreamPayloadError("device request fields are invalid")
    values = {key: payload.get(key) for key in _DEVICE_REQUEST_FIELDS}
    if (
        not all(isinstance(value, str) for value in values.values())
        or not 1 <= len(values["application_name"]) <= 80
        or not _HEX_64_RE.fullmatch(values["client_id"])
        or values["scopes"] != "read"
        or not 8 <= len(values["nonce"]) <= 128
        or values["padding"] != "oaep"
        or not 256 <= len(values["public_key"]) <= 8192
        or not values["public_key"].startswith("-----BEGIN PUBLIC KEY-----\n")
        or not values["public_key"].rstrip().endswith("-----END PUBLIC KEY-----")
    ):
        raise UpstreamPayloadError("device request values are invalid")
    return {key: str(values[key]) for key in _DEVICE_REQUEST_FIELDS}


def validate_device_poll_request(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != {"device_code"}:
        raise UpstreamPayloadError("device poll request fields are invalid")
    device_code = payload.get("device_code")
    if not isinstance(device_code, str) or not _HEX_64_RE.fullmatch(device_code):
        raise UpstreamPayloadError("device poll code is invalid")
    return {"device_code": device_code}


def validate_device_start_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise UpstreamPayloadError("device response root is invalid")
    device_code = payload.get("device_code")
    user_code = payload.get("user_code")
    verification_uri = payload.get("verification_uri")
    verification_with_request = payload.get("verification_uri_with_request")
    expires_in = payload.get("expires_in")
    interval = payload.get("interval")
    if (
        not isinstance(device_code, str)
        or not _HEX_64_RE.fullmatch(device_code)
        or not isinstance(user_code, str)
        or not _USER_CODE_RE.fullmatch(user_code)
        or verification_uri != "https://linux.do/user-api-key/activate"
        or not isinstance(verification_with_request, str)
        or not verification_with_request.startswith(
            "https://linux.do/user-api-key/activate?request="
        )
        or not isinstance(expires_in, int)
        or not 60 <= expires_in <= 3600
        or not isinstance(interval, int)
        or not 1 <= interval <= 30
    ):
        raise UpstreamPayloadError("device response fields are invalid")
    return payload


def validate_device_poll_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise UpstreamPayloadError("device poll response root is invalid")
    status = payload.get("status")
    if status not in {
        "authorization_pending",
        "access_denied",
        "expired_token",
        "authorized",
    }:
        raise UpstreamPayloadError("device poll status is invalid")
    encrypted = payload.get("payload")
    if status == "authorized" and (
        not isinstance(encrypted, str) or not 16 <= len(encrypted) <= 16_384
    ):
        raise UpstreamPayloadError("authorized device payload is invalid")
    return payload


def filter_first_post(body: bytes, topic_id: int) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpstreamPayloadError("upstream response is not JSON") from exc
    if not isinstance(payload, dict):
        raise UpstreamPayloadError("upstream response root is invalid")
    first: dict[str, Any] | None = None
    if (
        payload.get("post_number") == 1
        and payload.get("topic_id") == topic_id
    ):
        first = payload
    else:
        post_stream = payload.get("post_stream")
        posts = post_stream.get("posts") if isinstance(post_stream, dict) else None
        if not isinstance(posts, list):
            posts = payload.get("posts")
        if not isinstance(posts, list):
            raise UpstreamPayloadError("upstream response omitted posts")
        first = next(
            (
                post
                for post in posts
                if isinstance(post, dict)
                and post.get("post_number") == 1
                and post.get("topic_id", topic_id) == topic_id
            ),
            None,
        )
    if first is None or not isinstance(first.get("raw"), str):
        raise UpstreamPayloadError("upstream response omitted first post raw")
    title = payload.get("title") or first.get("topic_title") or ""
    category = payload.get("category_name") or first.get("category_name") or ""
    return {
        "title": str(title)[:180],
        "category_name": str(category)[:80],
        "posts": [
            {
                "post_number": 1,
                "topic_id": topic_id,
                "topic_title": str(title)[:180],
                "category_name": str(category)[:80],
                "raw": first["raw"],
            }
        ],
    }
