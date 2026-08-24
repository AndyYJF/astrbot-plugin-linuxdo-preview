from linuxdo_preview.formatter import (
    build_forward_chunks,
    build_plain_preview,
    build_preview_text,
    clean_discourse_content,
    clean_discourse_markdown,
    split_text,
)
from linuxdo_preview.models import TopicPreview


def test_cleans_discourse_markup_images_html_and_cq_sequences():
    raw = """# 标题

[details="图集"]
[grid]
![示例图|100x100](upload://abc.jpeg)
![二](upload://def.jpeg)
[/grid]
[/details]

<b>正文</b> [站点](https://example.com) [CQ:at,qq=123]
"""
    cleaned, truncated = clean_discourse_markdown(raw, max_chars=5000)
    assert truncated is False
    assert "【标题】" in cleaned
    assert "【图集】" in cleaned
    assert "[图片暂未展示：示例图]" in cleaned
    assert "正文" in cleaned
    assert "站点：https://example.com" in cleaned
    assert "［CQ:at,qq=123]" in cleaned
    assert "upload://" not in cleaned
    assert "<b>" not in cleaned


def test_collapses_reader_linked_image_with_metadata_to_one_placeholder():
    raw = (
        "[![Image 1: 商品图|690x700](https://cdn3.ldstatic.com/optimized/a.png) "
        "image 1920×1951 356 KB]"
        '(https://cdn3.ldstatic.com/original/a.jpeg "商品图")'
    )

    cleaned, truncated = clean_discourse_markdown(raw, max_chars=5000)

    assert truncated is False
    assert cleaned == "[图片暂未展示：商品图]"
    assert "https://" not in cleaned
    assert "1920" not in cleaned


def test_hides_a_standalone_remote_image_url():
    cleaned, _ = clean_discourse_markdown(
        "图片：https://example.com/path/photo.webp?size=large", max_chars=5000
    )

    assert "https://" not in cleaned
    assert "[图片暂未展示]" in cleaned


def test_removes_invisible_reader_heading_anchor_before_heading_rendering():
    raw = "\n".join(
        [
            "#### [](https://linux.do/t/topic/2795372#p-1-h-1)推广要求",
            "## [](https://linux.do/t/topic/2795372#p-1-h-2)客户端支持",
        ]
    )

    cleaned, truncated = clean_discourse_markdown(raw, max_chars=5000)

    assert truncated is False
    assert cleaned == "【推广要求】\n【客户端支持】"
    assert "[](" not in cleaned
    assert "linux.do/t/topic/2795372#" not in cleaned


def test_empty_link_cleanup_does_not_change_images_or_labeled_links():
    raw = "[](discarded) [仓库](https://github.com/example/repo) ![](upload://photo.png)"

    cleaned, _ = clean_discourse_markdown(raw, max_chars=5000)

    assert "[](discarded)" not in cleaned
    assert "仓库：https://github.com/example/repo" in cleaned
    assert "[图片暂未展示]" in cleaned


def test_preserves_bounded_reader_image_refs_in_post_order():
    raw = "\n\n".join(
        [
            (
                f"[![Image {index}: 图{index}|690x400]"
                f"(https://cdn{index}.ldstatic.com/optimized/{index}.png) "
                f"image 1200×800 300 KB]"
                f'(https://cdn{index}.ldstatic.com/original/{index}.png "图{index}")'
            )
            for index in range(1, 4)
        ]
    )

    cleaned = clean_discourse_content(raw, max_chars=5000, max_images=2)

    assert cleaned.truncated is False
    assert cleaned.total_image_count == 3
    assert len(cleaned.images) == 2
    assert cleaned.images[0].source_url.endswith("original/1.png")
    assert cleaned.images[1].source_url.endswith("original/2.png")
    assert cleaned.images[0].preview_url.endswith("optimized/1.png")
    assert cleaned.images[1].preview_url.endswith("optimized/2.png")
    assert cleaned.images[0].marker in cleaned.text
    assert cleaned.images[1].marker in cleaned.text
    assert "[另有 1 张图片暂未展示]" in cleaned.text
    assert "original/" not in cleaned.text


def test_truncates_at_a_readable_boundary():
    cleaned, truncated = clean_discourse_markdown("第一段。\n\n" + "甲" * 300, 80)
    assert truncated is True
    assert cleaned.endswith("[正文过长，已截断]")
    assert len(cleaned) <= 100


def test_split_text_caps_chunks_and_adds_remainder_marker():
    chunks = split_text("段落一。" * 200, chunk_chars=80, max_chunks=3)
    assert len(chunks) == 3
    assert all(len(chunk) <= 80 for chunk in chunks)
    assert chunks[-1].endswith("[其余内容请查看原帖]")


def test_build_preview_text_includes_id_and_canonical_link():
    preview = TopicPreview(
        topic_id=123,
        title="测试标题",
        category="开发调优",
        content="正文",
        canonical_url="https://linux.do/t/topic/123",
        fetch_source="reader",
    )
    rendered = build_preview_text(preview)
    assert "#123" in rendered
    assert "正文" in rendered
    assert rendered.endswith("https://linux.do/t/topic/123")


def test_plain_and_forward_fallbacks_always_keep_original_link():
    preview = TopicPreview(
        topic_id=123,
        title="测试标题",
        category="开发调优",
        content="很长的正文。" * 1000,
        canonical_url="https://linux.do/t/topic/123",
        fetch_source="reader",
        truncated=True,
    )
    plain = build_plain_preview(preview, max_chars=500)
    forward = build_forward_chunks(preview, chunk_chars=200, max_chunks=3)

    assert len(plain) <= 500
    assert plain.endswith("https://linux.do/t/topic/123")
    assert len(forward) == 3
    assert forward[-1].endswith("https://linux.do/t/topic/123")
