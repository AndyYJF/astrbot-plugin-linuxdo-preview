from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class TopicRef:
    topic_id: int
    original_url: str

    @property
    def canonical_url(self) -> str:
        return f"https://linux.do/t/topic/{self.topic_id}"

    @property
    def raw_first_post_url(self) -> str:
        return f"https://linux.do/raw/{self.topic_id}/1"


@dataclass(frozen=True, slots=True)
class FetchedTopic:
    title: str
    category: str
    content: str
    source: str


@dataclass(frozen=True, slots=True)
class TopicImage:
    position: int
    alt: str
    source_url: str
    preview_url: str | None = None

    @property
    def marker(self) -> str:
        suffix = f"：{self.alt}" if self.alt else ""
        return f"[帖子图片#{self.position}{suffix}]"


@dataclass(frozen=True, slots=True)
class EmbeddedTopicImage:
    position: int
    alt: str
    data_uri: str
    width: int
    height: int
    byte_size: int
    forward_data_uri: str | None = None
    forward_width: int = 0
    forward_height: int = 0
    forward_byte_size: int = 0


@dataclass(frozen=True, slots=True)
class CleanedTopicContent:
    text: str
    truncated: bool
    images: tuple[TopicImage, ...]
    total_image_count: int


@dataclass(frozen=True, slots=True)
class TopicPreview:
    topic_id: int
    title: str
    category: str
    content: str
    canonical_url: str
    fetch_source: str
    truncated: bool = False
    images: tuple[TopicImage, ...] = ()
    total_image_count: int = 0


class FetchErrorCode(StrEnum):
    CHALLENGE = "challenge"
    NETWORK = "network"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    RESTRICTED = "restricted"
    TOO_LARGE = "too_large"
    UNAVAILABLE = "unavailable"


class FetchError(RuntimeError):
    def __init__(self, code: FetchErrorCode, detail: str = "") -> None:
        super().__init__(detail or code.value)
        self.code = code
        self.detail = detail
