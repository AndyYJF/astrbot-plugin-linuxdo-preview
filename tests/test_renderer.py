from linuxdo_preview.models import EmbeddedTopicImage, TopicImage, TopicPreview
from linuxdo_preview.renderer import (
    LINUXDO_IMAGE_TEMPLATE,
    build_preview_fragment,
    build_render_options,
    content_to_safe_html,
    image_location_is_usable,
)


def test_renderer_builds_linuxdo_style_fragment_without_remote_media():
    preview = TopicPreview(
        topic_id=123,
        title='<script>alert("x")</script> 测试标题',
        category="开发调优",
        content=(
            "第一段。\n\n"
            "• 条目一\n• 条目二\n\n"
            "【款式图片】\n\n"
            "[图片暂未展示：示例图]\n\n"
            "https://example.com/path?a=1&b=2"
        ),
        canonical_url="https://linux.do/t/topic/123",
        fetch_source="reader-html",
    )
    fragment = build_preview_fragment(preview)

    assert "LINUX DO" in fragment
    assert "开发调优" in fragment
    assert "主题 #123" in fragment
    assert "&lt;script&gt;" in fragment
    assert "<script>alert" not in fragment
    assert "image-placeholder" in fragment
    assert "detail-row" in fragment
    assert "cdn.ldstatic.com" not in fragment
    assert "<img" not in fragment
    assert "原帖" in fragment


def test_content_renderer_escapes_html_and_preserves_readable_blocks():
    rendered = content_to_safe_html(
        "<b>不能执行</b>\n\n│ 引用\n\n【小标题】\n\n[正文过长，已截断]"
    )
    assert "&lt;b&gt;不能执行&lt;/b&gt;" in rendered
    assert "<blockquote>引用</blockquote>" in rendered
    assert "<h2>小标题</h2>" in rendered
    assert 'class="truncated"' in rendered


def test_template_has_no_external_assets_and_quality_is_clamped():
    assert "{{ text|safe }}" in LINUXDO_IMAGE_TEMPLATE
    assert "<img" not in LINUXDO_IMAGE_TEMPLATE
    assert "http://" not in LINUXDO_IMAGE_TEMPLATE
    assert "https://" not in LINUXDO_IMAGE_TEMPLATE
    assert build_render_options(99)["quality"] == 95
    assert build_render_options(20)["quality"] == 60


def test_image_location_rejects_text_error_and_accepts_bitmap_signatures(tmp_path):
    error_file = tmp_path / "error.jpg"
    error_file.write_bytes(b"no available server\n")
    jpeg_file = tmp_path / "valid.jpg"
    jpeg_file.write_bytes(b"\xff\xd8\xff\xe0payload")
    png_file = tmp_path / "valid.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\ndata")

    assert image_location_is_usable(str(error_file)) is False
    assert image_location_is_usable(str(jpeg_file)) is True
    assert image_location_is_usable(str(png_file)) is True
    assert image_location_is_usable(str(tmp_path / "missing.jpg")) is False
    assert image_location_is_usable("https://example.com/render.jpg") is True


def test_renderer_embeds_loaded_post_image_and_uses_vector_logos():
    source = TopicImage(
        position=1,
        alt="清晰示例",
        source_url="https://cdn.ldstatic.com/example.png",
    )
    embedded = EmbeddedTopicImage(
        position=1,
        alt="清晰示例",
        data_uri="data:image/jpeg;base64,/9j/2Q==",
        width=640,
        height=360,
        byte_size=4,
    )
    preview = TopicPreview(
        topic_id=456,
        title="图文主题",
        category="资源荟萃",
        content=source.marker,
        canonical_url="https://linux.do/t/topic/456",
        fetch_source="reader-html",
        images=(source,),
        total_image_count=1,
    )

    fragment = build_preview_fragment(preview, (embedded,))

    assert '<figure class="post-image">' in fragment
    assert 'src="data:image/jpeg;base64,/9j/2Q=="' in fragment
    assert 'width="640" height="360"' in fragment
    assert "已加载 1/1 张" in fragment
    assert fragment.count("<svg") == 2
    assert "linear-gradient" not in fragment
    assert source.source_url not in fragment


def test_renderer_keeps_placeholder_when_image_load_fails():
    source = TopicImage(
        position=1,
        alt="失败示例",
        source_url="https://cdn.ldstatic.com/fail.png",
    )
    rendered = content_to_safe_html(source.marker)

    assert "图片加载失败或超过限制：失败示例" in rendered
    assert "<img" not in rendered


def test_renderer_renders_markdown_table_as_html_table():
    from linuxdo_preview.renderer import content_to_safe_html

    content = (
        "|条件|信任等级1|信任等级2|\n"
        "|---|---|---|\n"
        "|进入至少5个话题|✔||\n"
        "|阅读至少30篇帖子|✔||"
    )

    html_out = content_to_safe_html(content)

    assert "<table>" in html_out
    assert "<th>条件</th>" in html_out
    assert "<td>阅读至少30篇帖子</td>" in html_out
    assert "|---|" not in html_out
    assert html_out.count("<tr>") == 3


def test_renderer_styles_inline_code_and_strikethrough():
    from linuxdo_preview.renderer import content_to_safe_html

    html_out = content_to_safe_html(
        "运行 `pip install astrbot` 即可，~~旧版~~别用。"
    )

    assert '<code class="ic">pip install astrbot</code>' in html_out
    assert "<del>旧版</del>" in html_out


def test_renderer_keeps_non_table_pipe_text_as_paragraph():
    from linuxdo_preview.renderer import content_to_safe_html

    html_out = content_to_safe_html("a | b 只是普通一行")

    assert "<table>" not in html_out
    assert "a | b 只是普通一行" in html_out


def test_renderer_styles_bold_and_horizontal_rule():
    from linuxdo_preview.renderer import content_to_safe_html

    html_out = content_to_safe_html("第一部分\n\n---\n\n这是 **重点** 内容")

    assert '<hr class="sep">' in html_out
    assert "<strong>重点</strong>" in html_out
    assert "---" not in html_out.replace('<hr class="sep">', "")
    assert "**" not in html_out


def test_plain_text_strips_bold_markers():
    from linuxdo_preview.formatter import build_preview_text
    from linuxdo_preview.models import TopicPreview

    preview = TopicPreview(
        topic_id=1,
        title="标题",
        category="分类",
        content="这是 **重点** 内容",
        canonical_url="https://linux.do/t/topic/1",
        fetch_source="fake",
    )

    plain = build_preview_text(preview)

    assert "重点" in plain
    assert "**" not in plain
