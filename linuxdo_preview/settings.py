from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


@dataclass(frozen=True, slots=True)
class Settings:
    enabled: bool = True
    group_allowlist: frozenset[str] = frozenset()
    fetch_mode: str = "reader-html"
    proxy_url: str | None = None
    max_links_per_message: int = 2
    cache_ttl_seconds: int = 1800
    dedup_ttl_seconds: int = 300
    reader_timeout_seconds: int = 45
    reader_requests_per_minute: int = 12
    authenticated_enabled: bool = False
    authenticated_sender_allowlist: frozenset[str] = frozenset()
    authenticated_allow_group_messages: bool = False
    authenticated_secret_file: str = (
        "/AstrBot/data/secrets/astrbot_plugin_linuxdo_preview.json"
    )
    authenticated_timeout_seconds: int = 45
    authenticated_requests_per_minute: int = 3
    authenticated_cache_ttl_seconds: int = 120
    max_response_bytes: int = 262_144
    max_content_chars: int = 12_000
    image_quality: int = 88
    max_images_per_topic: int = 6
    max_image_bytes: int = 2_000_000
    max_total_image_bytes: int = 6_000_000
    max_forward_image_bytes: int = 6_000_000
    max_total_forward_image_bytes: int = 12_000_000
    image_timeout_seconds: int = 15
    render_timeout_seconds: int = 90
    image_jpeg_quality: int = 82
    image_max_width: int = 1400
    image_max_height: int = 2400
    image_max_pixels: int = 20_000_000
    forward_image_jpeg_quality: int = 94
    forward_image_max_width: int = 4096
    forward_image_max_height: int = 8192
    max_cache_entries: int = 128
    max_concurrency: int = 2
    reply_on_error: bool = True

    def authenticated_subject_for(
        self,
        sender_id: str,
        group_id: str,
    ) -> str | None:
        normalized_sender = str(sender_id or "").strip()
        if (
            not self.authenticated_enabled
            or not normalized_sender
            or normalized_sender
            not in self.authenticated_sender_allowlist
        ):
            return None
        normalized_group = str(group_id or "").strip()
        if normalized_group:
            if not self.authenticated_allow_group_messages:
                return None
            return f"qq:{normalized_sender}:group:{normalized_group}"
        return f"qq:{normalized_sender}:private"

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any] | None) -> Settings:
        data = config or {}
        raw_proxy = str(data.get("proxy_url", "")).strip()
        raw_secret_file = str(data.get("authenticated_secret_file", "")).strip()

        raw_groups = data.get("group_allowlist", [])
        groups: set[str] = set()
        if isinstance(raw_groups, list | tuple | set | frozenset):
            groups = {str(value).strip() for value in raw_groups if str(value).strip()}

        raw_senders = data.get(
            "authenticated_sender_allowlist",
            data.get("authenticated_private_sender_allowlist", []),
        )
        authenticated_senders: set[str] = set()
        if isinstance(raw_senders, list | tuple | set | frozenset):
            authenticated_senders = {
                str(value).strip()
                for value in raw_senders
                if str(value).strip()
            }

        return cls(
            enabled=_as_bool(data.get("enabled"), True),
            group_allowlist=frozenset(groups),
            fetch_mode="reader-html",
            proxy_url=raw_proxy or None,
            max_links_per_message=_clamp_int(
                data.get("max_links_per_message"), 2, 1, 5
            ),
            cache_ttl_seconds=_clamp_int(
                data.get("cache_ttl_seconds"), 1800, 30, 86_400
            ),
            dedup_ttl_seconds=_clamp_int(data.get("dedup_ttl_seconds"), 300, 0, 3600),
            reader_timeout_seconds=_clamp_int(
                data.get("reader_timeout_seconds"), 45, 5, 90
            ),
            reader_requests_per_minute=_clamp_int(
                data.get("reader_requests_per_minute"), 12, 1, 18
            ),
            authenticated_enabled=_as_bool(
                data.get("authenticated_enabled"), False
            ),
            authenticated_sender_allowlist=frozenset(authenticated_senders),
            authenticated_allow_group_messages=_as_bool(
                data.get("authenticated_allow_group_messages"), False
            ),
            authenticated_secret_file=(
                raw_secret_file
                or "/AstrBot/data/secrets/astrbot_plugin_linuxdo_preview.json"
            ),
            authenticated_timeout_seconds=_clamp_int(
                data.get("authenticated_timeout_seconds"), 45, 5, 60
            ),
            authenticated_requests_per_minute=_clamp_int(
                data.get("authenticated_requests_per_minute"), 3, 1, 6
            ),
            authenticated_cache_ttl_seconds=_clamp_int(
                data.get("authenticated_cache_ttl_seconds"), 120, 30, 600
            ),
            max_content_chars=_clamp_int(
                data.get("max_content_chars"), 12_000, 500, 30_000
            ),
            image_quality=_clamp_int(data.get("image_quality"), 88, 60, 95),
            max_images_per_topic=_clamp_int(
                data.get("max_images_per_topic"), 6, 0, 12
            ),
            max_image_bytes=_clamp_int(
                data.get("max_image_bytes"), 2_000_000, 128_000, 8_000_000
            ),
            max_total_image_bytes=_clamp_int(
                data.get("max_total_image_bytes"),
                6_000_000,
                256_000,
                16_000_000,
            ),
            max_forward_image_bytes=_clamp_int(
                data.get("max_forward_image_bytes"),
                6_000_000,
                512_000,
                16_000_000,
            ),
            max_total_forward_image_bytes=_clamp_int(
                data.get("max_total_forward_image_bytes"),
                12_000_000,
                1_000_000,
                32_000_000,
            ),
            image_timeout_seconds=_clamp_int(
                data.get("image_timeout_seconds"), 15, 5, 45
            ),
            render_timeout_seconds=_clamp_int(
                data.get("render_timeout_seconds"), 90, 30, 180
            ),
            reply_on_error=_as_bool(data.get("reply_on_error"), True),
        )
