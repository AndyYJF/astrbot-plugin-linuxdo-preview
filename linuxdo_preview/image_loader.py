from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
from collections.abc import Sequence
from urllib.parse import urlparse

import aiohttp
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import EmbeddedTopicImage, TopicImage
from .settings import Settings

logger = logging.getLogger(__name__)

_ALLOWED_CONTENT_TYPES = {
    "image/avif",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}
_IMAGE_ACCEPT = "image/avif,image/webp,image/png,image/jpeg,image/*"
_ALLOWED_HOST_SUFFIXES = ("linux.do", "ldstatic.com")


class ImageLoadError(RuntimeError):
    pass


def is_allowed_image_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return False
    if port not in (None, 443):
        return False
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in _ALLOWED_HOST_SUFFIXES
    )


def _encode_bounded_jpeg(
    image: Image.Image,
    *,
    quality: int,
    max_bytes: int,
) -> tuple[bytes, int, int]:
    current = image
    for _attempt in range(5):
        for candidate_quality in (quality, 74, 66, 58):
            output = io.BytesIO()
            current.save(
                output,
                format="JPEG",
                quality=min(90, max(45, candidate_quality)),
                optimize=True,
            )
            payload = output.getvalue()
            if len(payload) <= max_bytes:
                return payload, current.width, current.height
        scale = min(0.85, math.sqrt(max_bytes / max(1, len(payload))) * 0.95)
        new_size = (
            max(1, round(current.width * scale)),
            max(1, round(current.height * scale)),
        )
        if new_size == current.size:
            break
        current = current.resize(new_size, Image.Resampling.LANCZOS)
    raise ImageLoadError("processed image exceeds byte limit")


def transcode_image(
    source: TopicImage,
    payload: bytes,
    settings: Settings,
) -> EmbeddedTopicImage:
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            if opened.width * opened.height > settings.image_max_pixels:
                raise ImageLoadError("image pixel limit exceeded")
            opened.seek(0)
            oriented = ImageOps.exif_transpose(opened)
            oriented.thumbnail(
                (settings.image_max_width, settings.image_max_height),
                Image.Resampling.LANCZOS,
            )
            if oriented.mode in {"RGBA", "LA"} or (
                oriented.mode == "P" and "transparency" in oriented.info
            ):
                rgba = oriented.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
            else:
                rgb = oriented.convert("RGB")
            encoded, width, height = _encode_bounded_jpeg(
                rgb,
                quality=settings.image_jpeg_quality,
                max_bytes=settings.max_image_bytes,
            )
    except (ImageLoadError, UnidentifiedImageError):
        raise
    except (OSError, ValueError) as exc:
        raise ImageLoadError("invalid image payload") from exc

    data = base64.b64encode(encoded).decode("ascii")
    return EmbeddedTopicImage(
        position=source.position,
        alt=source.alt,
        data_uri=f"data:image/jpeg;base64,{data}",
        width=width,
        height=height,
        byte_size=len(encoded),
    )


class TopicImageLoader:
    def __init__(
        self,
        settings: Settings,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.settings = settings
        self._session = session
        self._owns_session = session is None
        self._semaphore = asyncio.Semaphore(min(3, settings.max_concurrency + 1))

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(
                    total=self.settings.image_timeout_seconds
                ),
                trust_env=False,
            )
            self._owns_session = True
        return self._session

    async def _download_one(self, source: TopicImage) -> EmbeddedTopicImage | None:
        if not is_allowed_image_url(source.source_url):
            return None
        try:
            async with self._semaphore:
                session = await self._get_session()
                async with session.get(
                    source.source_url,
                    headers={"Accept": _IMAGE_ACCEPT},
                    proxy=self.settings.proxy_url,
                    allow_redirects=True,
                    max_redirects=3,
                ) as response:
                    if response.status != 200:
                        raise ImageLoadError(f"image HTTP {response.status}")
                    if not is_allowed_image_url(str(response.url)):
                        raise ImageLoadError("image redirect host is not allowed")
                    content_type = response.headers.get("content-type", "")
                    content_type = content_type.split(";", 1)[0].strip().lower()
                    if content_type not in _ALLOWED_CONTENT_TYPES:
                        raise ImageLoadError("unsupported image content type")
                    content_length = response.headers.get("content-length")
                    if (
                        content_length
                        and int(content_length) > self.settings.max_image_bytes
                    ):
                        raise ImageLoadError("image content-length exceeds limit")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.content.iter_chunked(65_536):
                        size += len(chunk)
                        if size > self.settings.max_image_bytes:
                            raise ImageLoadError("image body exceeds limit")
                        chunks.append(chunk)
            return await asyncio.to_thread(
                transcode_image,
                source,
                b"".join(chunks),
                self.settings,
            )
        except (aiohttp.ClientError, TimeoutError, ImageLoadError, ValueError) as exc:
            logger.warning(
                "LINUX DO image skipped: position=%s error=%s",
                source.position,
                type(exc).__name__,
            )
            return None

    async def load(
        self,
        images: Sequence[TopicImage],
    ) -> tuple[EmbeddedTopicImage, ...]:
        selected = tuple(images[: self.settings.max_images_per_topic])
        if not selected:
            return ()
        candidates = await asyncio.gather(
            *(self._download_one(image) for image in selected)
        )
        loaded: list[EmbeddedTopicImage] = []
        total_bytes = 0
        for candidate in candidates:
            if candidate is None:
                continue
            if total_bytes + candidate.byte_size > self.settings.max_total_image_bytes:
                continue
            total_bytes += candidate.byte_size
            loaded.append(candidate)
        return tuple(loaded)
