from __future__ import annotations

import re

from .models import TopicRef

_LINUXDO_URL_RE = re.compile(
    r"(?<![\w.-])"
    r"(?P<url>(?:https?://)?(?:www\.)?linux\.do/"
    r"(?:t/(?:[^/\s?#]+/)?|raw/)"
    r"(?P<topic_id>[1-9]\d{0,11})"
    r"(?:/\d+)?(?:[?#][^\s<>]*)?)",
    flags=re.IGNORECASE,
)


def extract_topic_refs(message: str, limit: int = 2) -> list[TopicRef]:
    """Extract unique, fixed-origin LINUX DO topic references in message order."""
    if not message or limit <= 0:
        return []

    refs: list[TopicRef] = []
    seen: set[int] = set()
    for match in _LINUXDO_URL_RE.finditer(message):
        topic_id = int(match.group("topic_id"))
        if topic_id in seen:
            continue
        seen.add(topic_id)
        original = match.group("url").rstrip(".,;:!?，。；：！？、)]}）】》'")
        if not original.lower().startswith(("http://", "https://")):
            original = f"https://{original}"
        refs.append(TopicRef(topic_id=topic_id, original_url=original))
        if len(refs) >= limit:
            break
    return refs
