from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from linuxdo_preview.image_loader import (
    ImageLoadError,
    TopicImageLoader,
    is_allowed_image_url,
    transcode_image,
)
from linuxdo_preview.models import TopicImage
from linuxdo_preview.settings import Settings


class FakeContent:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def iter_chunked(self, _size: int):
        yield self.payload


class FakeResponse:
    def __init__(self, url: str, payload: bytes, content_type: str = "image/png"):
        self.url = url
        self.status = 200
        self.headers = {
            "content-type": content_type,
            "content-length": str(len(payload)),
        }
        self.content = FakeContent(payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class FakeSession:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.closed = False
        self.calls: list[str] = []

    def get(self, url: str, **_kwargs):
        self.calls.append(url)
        return FakeResponse(url, self.payload)


def make_png(width: int = 120, height: int = 80) -> bytes:
    image = Image.new("RGBA", (width, height), (16, 146, 220, 180))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_image_url_allowlist_is_https_and_domain_bounded():
    assert is_allowed_image_url("https://cdn3.ldstatic.com/a.png") is True
    assert is_allowed_image_url("https://linux.do/uploads/a.png") is True
    assert is_allowed_image_url("http://cdn.ldstatic.com/a.png") is False
    assert is_allowed_image_url("https://ldstatic.com.example.org/a.png") is False
    assert is_allowed_image_url("https://127.0.0.1/a.png") is False


async def test_loader_downloads_only_the_configured_count_and_embeds_jpeg():
    session = FakeSession(make_png())
    settings = Settings(
        max_images_per_topic=1,
        max_image_bytes=200_000,
        max_total_image_bytes=200_000,
    )
    loader = TopicImageLoader(settings, session=session)  # type: ignore[arg-type]
    images = (
        TopicImage(1, "第一张", "https://cdn.ldstatic.com/1.png"),
        TopicImage(2, "第二张", "https://cdn.ldstatic.com/2.png"),
    )

    loaded = await loader.load(images)

    assert session.calls == ["https://cdn.ldstatic.com/1.png"]
    assert len(loaded) == 1
    assert loaded[0].data_uri.startswith("data:image/jpeg;base64,")
    payload = base64.b64decode(loaded[0].data_uri.split(",", 1)[1])
    assert payload.startswith(b"\xff\xd8\xff")
    assert loaded[0].width == 120
    assert loaded[0].height == 80


async def test_loader_drops_processed_images_after_total_byte_limit():
    session = FakeSession(make_png())
    settings = Settings(
        max_images_per_topic=1,
        max_image_bytes=200_000,
        max_total_image_bytes=1,
    )
    loader = TopicImageLoader(settings, session=session)  # type: ignore[arg-type]

    loaded = await loader.load(
        (TopicImage(1, "图片", "https://cdn.ldstatic.com/1.png"),)
    )

    assert loaded == ()


def test_transcoder_rejects_pixel_bombs_before_decode():
    source = TopicImage(1, "大图", "https://cdn.ldstatic.com/large.png")
    settings = Settings(image_max_pixels=100)

    with pytest.raises(ImageLoadError, match="pixel limit"):
        transcode_image(source, make_png(20, 20), settings)
