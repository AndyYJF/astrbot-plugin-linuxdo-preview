from __future__ import annotations

import asyncio

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Node, Nodes, Plain
from astrbot.api.star import Context, Star, register

from .linuxdo_preview.cache import TTLCache
from .linuxdo_preview.formatter import (
    build_forward_chunks,
    build_plain_preview,
    error_message,
)
from .linuxdo_preview.image_loader import TopicImageLoader
from .linuxdo_preview.models import EmbeddedTopicImage, FetchError
from .linuxdo_preview.renderer import (
    LINUXDO_IMAGE_TEMPLATE,
    build_preview_fragment,
    build_render_options,
    image_location_is_usable,
)
from .linuxdo_preview.service import PreviewService
from .linuxdo_preview.settings import Settings
from .linuxdo_preview.urls import extract_topic_refs


@register(
    "astrbot_plugin_linuxdo_preview",
    "AndyYan",
    "将 QQ 中的 LINUX DO 首帖渲染为长图，支持绑定 QQ 的只读登录通道",
    "0.7.0",
)
class LinuxDoPreviewPlugin(Star):
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | dict | None = None,
    ) -> None:
        super().__init__(context)
        self.settings = Settings.from_mapping(config)
        self.service = PreviewService(self.settings)
        self.image_loader = TopicImageLoader(self.settings)
        self._render_semaphore = asyncio.Semaphore(self.settings.max_concurrency)
        self._rendered_images: TTLCache[str] = TTLCache(
            ttl_seconds=self.settings.cache_ttl_seconds,
            max_entries=self.settings.max_cache_entries,
        )
        self._embedded_images: TTLCache[tuple[EmbeddedTopicImage, ...]] = TTLCache(
            ttl_seconds=self.settings.cache_ttl_seconds,
            max_entries=min(4, self.settings.max_cache_entries),
        )

    async def initialize(self) -> None:
        logger.info(
            "LINUX DO preview initialized: mode=%s, proxy=%s, groups=%s, "
            "authenticated=%s, authenticated_senders=%s, auth_groups=%s",
            self.settings.fetch_mode,
            "configured" if self.settings.proxy_url else "none",
            len(self.settings.group_allowlist),
            "enabled" if self.settings.authenticated_enabled else "disabled",
            len(self.settings.authenticated_sender_allowlist),
            self.settings.authenticated_allow_group_messages,
        )

    async def terminate(self) -> None:
        await asyncio.gather(self.service.close(), self.image_loader.close())

    async def _render_preview_bundle(
        self,
        preview,
    ) -> tuple[str | None, tuple[EmbeddedTopicImage, ...]]:
        cache_key = f"{preview.cache_scope}:{preview.topic_id}"
        cached_location = self._rendered_images.get(cache_key)
        cached_images = self._embedded_images.get(cache_key)
        if (
            cached_location
            and image_location_is_usable(cached_location)
            and cached_images is not None
        ):
            return cached_location, cached_images

        async with self._render_semaphore:
            cached_location = self._rendered_images.get(cache_key)
            cached_images = self._embedded_images.get(cache_key)
            if cached_images is None:
                cached_images = await self.image_loader.load(preview.images)
                self._embedded_images.put(cache_key, cached_images)
            if not cached_location or not image_location_is_usable(cached_location):
                try:
                    fragment = build_preview_fragment(preview, cached_images)
                    async with asyncio.timeout(self.settings.render_timeout_seconds):
                        cached_location = await self.html_render(
                            LINUXDO_IMAGE_TEMPLATE,
                            {"text": fragment},
                            return_url=False,
                            options=build_render_options(self.settings.image_quality),
                        )
                    if (
                        not isinstance(cached_location, str)
                        or not cached_location.strip()
                    ):
                        raise RuntimeError("renderer returned an empty image location")
                    if not image_location_is_usable(cached_location):
                        raise RuntimeError("renderer image location is unavailable")
                    self._rendered_images.put(cache_key, cached_location)
                except Exception as exc:
                    logger.warning(
                        "LINUX DO T2I render failed; using text fallback: "
                        "topic_id=%s error=%s",
                        preview.topic_id,
                        type(exc).__name__,
                    )
                    return None, cached_images
            return cached_location, cached_images

    @staticmethod
    def _image_from_location(location: str) -> Image:
        return (
            Image.fromURL(location)
            if location.startswith(("http://", "https://"))
            else Image.fromFileSystem(location)
        )

    @staticmethod
    def _image_from_embedded(image: EmbeddedTopicImage) -> Image:
        data_uri = image.forward_data_uri
        if (
            not data_uri
            or not data_uri.startswith("data:image/")
            or "," not in data_uri
        ):
            raise ValueError("embedded image has no forward data URI")
        return Image.fromBase64(data_uri.split(",", 1)[1])

    def _build_success_chain(
        self,
        event: AstrMessageEvent,
        preview_location: str,
        embedded_images: tuple[EmbeddedTopicImage, ...],
    ) -> list[object]:
        preview_image = self._image_from_location(preview_location)
        if event.get_platform_name() != "aiocqhttp":
            return [preview_image]

        uin = event.get_self_id() or "10000"
        nodes = [
            Node(
                uin=uin,
                name="LINUX DO 预览",
                content=[preview_image],
            )
        ]
        nodes.extend(self._build_post_image_nodes(uin, embedded_images))
        return [Nodes(nodes)]

    def _build_post_image_nodes(
        self,
        uin: str,
        embedded_images: tuple[EmbeddedTopicImage, ...],
    ) -> list[Node]:
        return [
            Node(
                uin=uin,
                name=f"帖子图片 #{image.position}",
                content=[self._image_from_embedded(image)],
            )
            for image in embedded_images
            if image.forward_data_uri
        ]

    def _build_text_fallback_chain(
        self,
        event: AstrMessageEvent,
        preview,
        embedded_images: tuple[EmbeddedTopicImage, ...],
    ) -> list[object]:
        uin = event.get_self_id() or "10000"
        text_chunks = build_forward_chunks(
            preview,
            chunk_chars=2_000,
            max_chunks=6,
        )
        chunk_count = len(text_chunks)
        nodes = [
            Node(
                uin=uin,
                name="LINUX DO 预览状态",
                content=[Plain("长图渲染失败，已自动切换为纯文本预览。")],
            )
        ]
        nodes.extend(
            Node(
                uin=uin,
                name=(
                    "LINUX DO 文本预览"
                    if chunk_count == 1
                    else f"LINUX DO 文本预览 {index}/{chunk_count}"
                ),
                content=[Plain(chunk)],
            )
            for index, chunk in enumerate(text_chunks, start=1)
        )
        nodes.extend(self._build_post_image_nodes(uin, embedded_images))
        return [Nodes(nodes)]

    async def _build_authenticated_chain(
        self,
        event: AstrMessageEvent,
        preview,
    ) -> list[object]:
        cache_key = f"{preview.cache_scope}:{preview.topic_id}"
        embedded_images = self._embedded_images.get(cache_key)
        if embedded_images is None:
            embedded_images = await self.image_loader.load(preview.images)
            self._embedded_images.put(cache_key, embedded_images)

        if event.get_platform_name() != "aiocqhttp":
            return [
                Plain(
                    build_plain_preview(
                        preview,
                        max_chars=self.settings.max_content_chars,
                    )
                )
            ]

        uin = event.get_self_id() or "10000"
        text_chunks = build_forward_chunks(
            preview,
            chunk_chars=2_000,
            max_chunks=6,
        )
        chunk_count = len(text_chunks)
        nodes = [
            Node(
                uin=uin,
                name="LINUX DO 授权预览状态",
                content=[
                    Plain(
                        "该内容通过绑定的只读授权获取，"
                        "未交给 Jina Reader 或第三方 T2I。"
                    )
                ],
            )
        ]
        nodes.extend(
            Node(
                uin=uin,
                name=(
                    "LINUX DO 授权文本预览"
                    if chunk_count == 1
                    else f"LINUX DO 授权文本预览 {index}/{chunk_count}"
                ),
                content=[Plain(chunk)],
            )
            for index, chunk in enumerate(text_chunks, start=1)
        )
        nodes.extend(self._build_post_image_nodes(uin, embedded_images))
        return [Nodes(nodes)]

    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE | filter.EventMessageType.PRIVATE_MESSAGE
    )
    async def on_group_message(self, event: AstrMessageEvent):
        if not self.settings.enabled:
            return
        sender_id = str(event.get_sender_id() or "").strip()
        self_id = str(event.get_self_id() or "").strip()
        if self_id and sender_id == self_id:
            return

        group_id = str(event.get_group_id() or "").strip()
        if (
            group_id
            and self.settings.group_allowlist
            and group_id not in self.settings.group_allowlist
        ):
            return

        auth_subject = self.settings.authenticated_subject_for(sender_id, group_id)

        ref_limit = self.settings.max_links_per_message
        if auth_subject:
            ref_limit = min(ref_limit, 1)
        refs = extract_topic_refs(
            event.get_message_str(),
            limit=ref_limit,
        )
        if not refs:
            return

        conversation_id = f"group:{group_id}" if group_id else f"private:{sender_id}"
        scope = f"{event.get_platform_id()}:{conversation_id}"
        for ref in refs:
            if not self.service.reserve(scope, ref.topic_id):
                continue
            try:
                preview = await self.service.get_preview(
                    ref,
                    auth_subject=auth_subject,
                )
            except FetchError as exc:
                logger.warning(
                    "LINUX DO preview failed: topic_id=%s code=%s detail=%s",
                    ref.topic_id,
                    exc.code.value,
                    exc.detail,
                )
                if self.settings.reply_on_error:
                    message = error_message(ref.topic_id, exc.code.value)
                    yield event.plain_result(message)
                continue
            except Exception as exc:
                logger.exception(
                    "Unexpected LINUX DO preview error for topic_id=%s: %s",
                    ref.topic_id,
                    type(exc).__name__,
                )
                if self.settings.reply_on_error:
                    yield event.plain_result(error_message(ref.topic_id, "unavailable"))
                continue

            try:
                if preview.cache_scope != "public":
                    success_chain = await self._build_authenticated_chain(
                        event,
                        preview,
                    )
                else:
                    image_location, embedded_images = (
                        await self._render_preview_bundle(preview)
                    )
                    if image_location is None:
                        if event.get_platform_name() != "aiocqhttp":
                            yield event.plain_result(
                                build_plain_preview(
                                    preview,
                                    max_chars=self.settings.max_content_chars,
                                )
                            )
                            continue
                        success_chain = self._build_text_fallback_chain(
                            event,
                            preview,
                            embedded_images,
                        )
                    else:
                        success_chain = self._build_success_chain(
                            event,
                            image_location,
                            embedded_images,
                        )
            except Exception as exc:
                logger.exception(
                    "LINUX DO image render failed: topic_id=%s error=%s",
                    ref.topic_id,
                    type(exc).__name__,
                )
                if self.settings.reply_on_error:
                    yield event.plain_result(
                        error_message(ref.topic_id, "render_failed")
                    )
                continue

            yield event.chain_result(success_chain)
