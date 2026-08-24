from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
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


@dataclass(frozen=True, slots=True)
class _DownloadedImage:
    payload: bytes
    content_type: str


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
                quality=min(95, max(45, candidate_quality)),
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


def _transcode_payload(
    payload: bytes,
    *,
    max_pixels: int,
    max_width: int,
    max_height: int,
    quality: int,
    max_bytes: int,
) -> tuple[bytes, int, int]:
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            if opened.width * opened.height > max_pixels:
                raise ImageLoadError("image pixel limit exceeded")
            opened.seek(0)
            oriented = ImageOps.exif_transpose(opened)
            oriented.thumbnail(
                (max_width, max_height),
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
                quality=quality,
                max_bytes=max_bytes,
            )
    except (ImageLoadError, UnidentifiedImageError):
        raise
    except (OSError, ValueError) as exc:
        raise ImageLoadError("invalid image payload") from exc
    return encoded, width, height


def _validated_original_metadata(
    payload: bytes,
    *,
    max_pixels: int,
) -> tuple[int, int, int]:
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            if opened.width * opened.height > max_pixels:
                raise ImageLoadError("image pixel limit exceeded")
            width, height = opened.size
            opened.verify()
        with Image.open(io.BytesIO(payload)) as opened:
            orientation = int(opened.getexif().get(274, 1) or 1)
    except (ImageLoadError, UnidentifiedImageError):
        raise
    except (OSError, ValueError) as exc:
        raise ImageLoadError("invalid image payload") from exc
    return width, height, orientation


def transcode_image(
    source: TopicImage,
    payload: bytes,
    settings: Settings,
) -> EmbeddedTopicImage:
    encoded, width, height = _transcode_payload(
        payload,
        max_pixels=settings.image_max_pixels,
        max_width=settings.image_max_width,
        max_height=settings.image_max_height,
        quality=settings.image_jpeg_quality,
        max_bytes=settings.max_image_bytes,
    )

    data = base64.b64encode(encoded).decode("ascii")
    return EmbeddedTopicImage(
        position=source.position,
        alt=source.alt,
        data_uri=f"data:image/jpeg;base64,{data}",
        width=width,
        height=height,
        byte_size=len(encoded),
    )


def prepare_forward_image(
    payload: bytes,
    content_type: str,
    settings: Settings,
) -> tuple[str, int, int, int]:
    width, height, orientation = _validated_original_metadata(
        payload,
        max_pixels=settings.image_max_pixels,
    )
    if content_type in {"image/jpeg", "image/png"} and orientation == 1:
        encoded = payload
        media_type = content_type
    else:
        encoded, width, height = _transcode_payload(
            payload,
            max_pixels=settings.image_max_pixels,
            max_width=settings.forward_image_max_width,
            max_height=settings.forward_image_max_height,
            quality=settings.forward_image_jpeg_quality,
            max_bytes=settings.max_forward_image_bytes,
        )
        media_type = "image/jpeg"
    if len(encoded) > settings.max_forward_image_bytes:
        raise ImageLoadError("forward image exceeds byte limit")
    data = base64.b64encode(encoded).decode("ascii")
    return f"data:{media_type};base64,{data}", width, height, len(encoded)


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

    async def _download(
        self,
        url: str,
        *,
        max_bytes: int,
    ) -> _DownloadedImage:
        if not is_allowed_image_url(url):
            raise ImageLoadError("image host is not allowed")
        async with self._semaphore:
            session = await self._get_session()
            async with session.get(
                    url,
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
                if content_length and int(content_length) > max_bytes:
                    raise ImageLoadError("image content-length exceeds limit")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.content.iter_chunked(65_536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ImageLoadError("image body exceeds limit")
                    chunks.append(chunk)
        return _DownloadedImage(b"".join(chunks), content_type)

    async def _try_download(
        self,
        source: TopicImage,
        url: str,
        *,
        max_bytes: int,
        kind: str,
    ) -> _DownloadedImage | None:
        try:
            return await self._download(url, max_bytes=max_bytes)
        except (aiohttp.ClientError, TimeoutError, ImageLoadError, ValueError) as exc:
            logger.warning(
                "LINUX DO image %s skipped: position=%s error=%s",
                kind,
                source.position,
                type(exc).__name__,
            )
            return None

    async def _download_one(self, source: TopicImage) -> EmbeddedTopicImage | None:
        preview_url = source.preview_url or source.source_url
        if preview_url == source.source_url:
            original = await self._try_download(
                source,
                source.source_url,
                max_bytes=self.settings.max_forward_image_bytes,
                kind="original",
            )
            preview = original
        else:
            original, preview = await asyncio.gather(
                self._try_download(
                    source,
                    source.source_url,
                    max_bytes=self.settings.max_forward_image_bytes,
                    kind="original",
                ),
                self._try_download(
                    source,
                    preview_url,
                    max_bytes=self.settings.max_image_bytes,
                    kind="preview",
                ),
            )

        preview_source = preview or original
        if preview_source is None:
            return None
        try:
            embedded = await asyncio.to_thread(
                transcode_image,
                source,
                preview_source.payload,
                self.settings,
            )
        except ImageLoadError:
            if original is None or preview_source is original:
                return None
            try:
                embedded = await asyncio.to_thread(
                    transcode_image,
                    source,
                    original.payload,
                    self.settings,
                )
            except ImageLoadError:
                return None

        if original is not None:
            try:
                forward_data_uri, forward_width, forward_height, forward_byte_size = (
                    await asyncio.to_thread(
                        prepare_forward_image,
                        original.payload,
                        original.content_type,
                        self.settings,
                    )
                )
            except ImageLoadError:
                original = None
        if original is None:
            forward_data_uri = embedded.data_uri
            forward_width = embedded.width
            forward_height = embedded.height
            forward_byte_size = embedded.byte_size
        return replace(
            embedded,
            forward_data_uri=forward_data_uri,
            forward_width=forward_width,
            forward_height=forward_height,
            forward_byte_size=forward_byte_size,
        )

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
        total_forward_bytes = 0
        for candidate in candidates:
            if candidate is None:
                continue
            if total_bytes + candidate.byte_size > self.settings.max_total_image_bytes:
                continue
            total_bytes += candidate.byte_size
            if (
                candidate.forward_data_uri
                and total_forward_bytes + candidate.forward_byte_size
                > self.settings.max_total_forward_image_bytes
            ):
                candidate = replace(
                    candidate,
                    forward_data_uri=None,
                    forward_width=0,
                    forward_height=0,
                    forward_byte_size=0,
                )
            else:
                total_forward_bytes += candidate.forward_byte_size
            loaded.append(candidate)
        return tuple(loaded)
