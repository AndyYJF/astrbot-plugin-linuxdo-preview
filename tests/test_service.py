from linuxdo_preview.models import FetchedTopic, TopicRef
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
