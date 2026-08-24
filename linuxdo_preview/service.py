from __future__ import annotations

from .cache import TTLCache
from .fetcher import LinuxDoFetcher
from .formatter import clean_discourse_content
from .models import FetchedTopic, TopicPreview, TopicRef
from .settings import Settings


class PreviewService:
    def __init__(
        self,
        settings: Settings,
        fetcher: LinuxDoFetcher | None = None,
    ) -> None:
        self.settings = settings
        self.fetcher = fetcher or LinuxDoFetcher(settings)
        self._previews: TTLCache[TopicPreview] = TTLCache(
            ttl_seconds=settings.cache_ttl_seconds,
            max_entries=settings.max_cache_entries,
        )
        self._authenticated_previews: TTLCache[TopicPreview] = TTLCache(
            ttl_seconds=settings.authenticated_cache_ttl_seconds,
            max_entries=min(16, settings.max_cache_entries),
        )
        self._seen: TTLCache[bool] = TTLCache(
            ttl_seconds=settings.dedup_ttl_seconds,
            max_entries=max(256, settings.max_cache_entries * 4),
        )

    async def close(self) -> None:
        await self.fetcher.close()

    def reserve(self, scope: str, topic_id: int) -> bool:
        key = f"{scope}:{topic_id}"
        if self._seen.contains(key):
            return False
        self._seen.put(key, True)
        return True

    async def get_preview(
        self,
        ref: TopicRef,
        *,
        auth_subject: str | None = None,
    ) -> TopicPreview:
        normalized_subject = str(auth_subject or "").strip()
        if normalized_subject:
            authenticated_cache_key = f"{normalized_subject}:{ref.topic_id}"
            cached_authenticated = self._authenticated_previews.get(
                authenticated_cache_key
            )
            if cached_authenticated is not None:
                return cached_authenticated

            fetched = await self.fetcher.fetch_authenticated_first_post(ref)
            preview = self._build_preview(
                ref,
                fetched,
                cache_scope=f"auth:{normalized_subject}",
            )
            self._authenticated_previews.put(authenticated_cache_key, preview)
            return preview

        cache_key = str(ref.topic_id)
        cached = self._previews.get(cache_key)
        if cached is not None:
            return cached

        fetched = await self.fetcher.fetch_first_post(ref)
        preview = self._build_preview(ref, fetched, cache_scope="public")
        self._previews.put(cache_key, preview)
        return preview

    def _build_preview(
        self,
        ref: TopicRef,
        fetched: FetchedTopic,
        *,
        cache_scope: str,
    ) -> TopicPreview:
        cleaned = clean_discourse_content(
            fetched.content,
            max_chars=self.settings.max_content_chars,
            max_images=self.settings.max_images_per_topic,
        )
        preview = TopicPreview(
            topic_id=ref.topic_id,
            title=fetched.title,
            category=fetched.category,
            content=cleaned.text,
            canonical_url=ref.canonical_url,
            fetch_source=fetched.source,
            truncated=cleaned.truncated,
            images=cleaned.images,
            total_image_count=cleaned.total_image_count,
            cache_scope=cache_scope,
        )
        return preview
