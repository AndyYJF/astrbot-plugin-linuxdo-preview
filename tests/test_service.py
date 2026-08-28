import pytest

from linuxdo_preview.models import (
    FetchedTopic,
    FetchError,
    FetchErrorCode,
    TopicRef,
)
from linuxdo_preview.service import PreviewService
from linuxdo_preview.settings import Settings


class FakeFetcher:
    def __init__(self):
        self.calls = 0
        self.closed = False

    async def fetch_first_post(self, ref):
        self.calls += 1
        return FetchedTopic(
            title=f"标题 {ref.topic_id}",
            category="开发调优",
            content=f"帖子 {ref.topic_id}",
            source="fake",
        )

    async def close(self):
        self.closed = True


async def test_service_caches_success_and_deduplicates_by_scope():
    settings = Settings(cache_ttl_seconds=60, dedup_ttl_seconds=60)
    fetcher = FakeFetcher()
    service = PreviewService(settings, fetcher=fetcher)
    ref = TopicRef(123, "https://linux.do/t/topic/123")

    assert service.reserve("group-a", 123) is True
    assert service.reserve("group-a", 123) is False
    assert service.reserve("group-b", 123) is True

    first = await service.get_preview(ref)
    second = await service.get_preview(ref)
    assert first == second
    assert first.title == "标题 123"
    assert first.category == "开发调优"
    assert first.images == ()
    assert first.total_image_count == 0
    assert fetcher.calls == 1

    await service.close()
    assert fetcher.closed is True


class FakeAuthenticatedFetcher(FakeFetcher):
    def __init__(self):
        super().__init__()
        self.auth_calls = 0

    async def fetch_first_post(self, ref):
        self.calls += 1
        raise FetchError(FetchErrorCode.RESTRICTED, "private")

    async def fetch_authenticated_first_post(self, ref):
        self.auth_calls += 1
        return FetchedTopic(
            title=f"受限标题 {ref.topic_id}",
            category="开发调优",
            content="授权正文",
            source="discourse-user-api",
        )


async def test_authenticated_preview_cache_is_subject_scoped_and_not_public():
    settings = Settings(cache_ttl_seconds=60, authenticated_cache_ttl_seconds=60)
    fetcher = FakeAuthenticatedFetcher()
    service = PreviewService(settings, fetcher=fetcher)
    ref = TopicRef(321, "https://linux.do/t/topic/321")

    first = await service.get_preview(ref, auth_subject="qq-a")
    second = await service.get_preview(ref, auth_subject="qq-a")
    other = await service.get_preview(ref, auth_subject="qq-b")

    assert first == second
    assert first.cache_scope == "auth:qq-a"
    assert other.cache_scope == "auth:qq-b"
    assert fetcher.auth_calls == 2
    assert fetcher.calls == 0

    with pytest.raises(FetchError) as captured:
        await service.get_preview(ref)
    assert captured.value.code is FetchErrorCode.RESTRICTED
    assert fetcher.calls == 1
    await service.close()


async def test_authenticated_preview_merges_cooked_only_images():
    class CookedFetcher(FakeAuthenticatedFetcher):
        async def fetch_authenticated_first_post(self, ref):
            return FetchedTopic(
                title="受限标题",
                category="开发调优",
                content="授权正文",
                source="discourse-user-api",
                cooked=(
                    "<p>授权正文</p>"
                    '<img src="https://cdn3.ldstatic.com/optimized/4X/a/b.jpeg" '
                    'alt="图">'
                ),
            )

    settings = Settings(cache_ttl_seconds=60, authenticated_cache_ttl_seconds=60)
    service = PreviewService(settings, fetcher=CookedFetcher())
    ref = TopicRef(321, "https://linux.do/t/topic/321")

    preview = await service.get_preview(ref, auth_subject="qq-a")

    assert preview.cache_scope == "auth:qq-a"
    assert len(preview.images) == 1
    assert preview.images[0].source_url == (
        "https://cdn3.ldstatic.com/optimized/4X/a/b.jpeg"
    )
    assert preview.images[0].marker in preview.content
    assert preview.total_image_count == 1
    await service.close()
