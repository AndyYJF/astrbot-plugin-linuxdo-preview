from __future__ import annotations

import asyncio
import json
import os

from linuxdo_preview.image_loader import is_allowed_image_url
from linuxdo_preview.models import TopicRef
from linuxdo_preview.service import PreviewService
from linuxdo_preview.settings import Settings

SAMPLE = TopicRef(2045356, "https://linux.do/t/topic/2045356")


async def main() -> None:
    proxy = os.environ.get("LINUXDO_TEST_PROXY", "http://127.0.0.1:7890")

    settings = Settings(
        proxy_url=proxy,
        max_content_chars=12_000,
    )
    service = PreviewService(settings)
    try:
        preview = await service.get_preview(SAMPLE)
        assert preview.fetch_source == "reader-html"
        assert "LINUX DO专属文化衫" in preview.title
        assert "售价保持不变" in preview.content
        assert "9527-oo" not in preview.content
        assert "upload://" not in preview.content
        assert "cdn.ldstatic.com" not in preview.content
        assert preview.total_image_count == 41
        assert len(preview.images) == settings.max_images_per_topic
        assert all(is_allowed_image_url(image.source_url) for image in preview.images)
        assert all(image.marker in preview.content for image in preview.images)
        result = {
            "reader_source": preview.fetch_source,
            "title": preview.title,
            "content_chars": len(preview.content),
            "contains_expected": True,
            "contains_reply_2": False,
            "contains_upload_url": False,
            "total_images": preview.total_image_count,
            "selected_images": len(preview.images),
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        await service.close()


if __name__ == "__main__":
    asyncio.run(main())
