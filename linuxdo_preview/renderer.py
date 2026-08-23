from __future__ import annotations

import html
import re
from collections.abc import Sequence
from pathlib import Path

from .models import EmbeddedTopicImage, TopicPreview


def image_location_is_usable(location: str) -> bool:
    if location.startswith(("http://", "https://")):
        return True
    path = Path(location)
    if not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            signature = handle.read(12)
    except OSError:
        return False
    return (
        signature.startswith(b"\xff\xd8\xff")
        or signature.startswith(b"\x89PNG\r\n\x1a\n")
        or signature.startswith((b"GIF87a", b"GIF89a"))
        or (signature.startswith(b"RIFF") and signature[8:12] == b"WEBP")
    )

_URL_RE = re.compile(r"https?://[^\s<>]+")
_IMAGE_PLACEHOLDER_RE = re.compile(
    r"\[(?:图片暂未展示(?:：(?P<alt>[^\]]+))?|"
    r"另有\s+(?P<count>\d+)\s+张图片暂未展示)\]"
)
_IMAGE_TOKEN_RE = re.compile(
    r"\[帖子图片#(?P<position>\d+)(?:：(?P<alt>[^\]]+))?\]"
)
_STANDALONE_TITLE_RE = re.compile(r"^【(?P<title>[^】]{1,120})】$")


LINUXDO_IMAGE_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <script id="astrbot-t2i-shiki-runtime"></script>
  <style>
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      padding: 0;
      width: 100%;
      background: #f4f5f6;
      color: #2b2b2b;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC",
        "Microsoft YaHei", Arial, sans-serif;
    }
    body { min-width: 960px; }
    .page {
      width: 960px;
      min-height: 720px;
      margin: 0 auto;
      background: #ffffff;
      padding-bottom: 42px;
    }
    .topbar {
      height: 58px;
      padding: 0 38px;
      border-bottom: 1px solid #e3e5e7;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .brand { display: flex; align-items: center; gap: 11px; }
    .brand-mark {
      width: 34px;
      height: 34px;
      display: block;
      flex: 0 0 auto;
    }
    .brand-name {
      color: #a6a6a6;
      font-size: 16px;
      font-weight: 700;
      letter-spacing: .4px;
    }
    .edition { color: #8b8e91; font-size: 13px; }
    .notice {
      margin: 18px 38px 0;
      padding: 11px 16px;
      background: #d7f2ff;
      color: #31373c;
      font-size: 15px;
      line-height: 1.5;
    }
    .notice b { font-weight: 750; }
    .topic { padding: 17px 58px 0; }
    .topic-title {
      margin: 0;
      color: #262626;
      font-size: 33px;
      line-height: 1.28;
      font-weight: 800;
      letter-spacing: -.4px;
      word-break: break-word;
    }
    .topic-meta {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 9px;
      color: #888;
      font-size: 13px;
    }
    .pill { padding: 4px 9px; background: #ededed; color: #6a6d70; border-radius: 3px; }
    .pill-blue { background: #e8f7ff; color: #1684bd; }
    .post {
      display: grid;
      grid-template-columns: 58px minmax(0, 1fr);
      column-gap: 16px;
      margin-top: 27px;
    }
    .avatar {
      width: 48px;
      height: 48px;
      display: block;
    }
    .author-row { height: 48px; display: flex; align-items: center; gap: 9px; }
    .author-name { font-size: 16px; color: #67696b; font-weight: 700; }
    .op-badge { font-size: 12px; color: #0a98df; font-weight: 700; font-style: italic; }
    .post-body {
      margin-top: 8px;
      font-size: 17px;
      line-height: 1.72;
      color: #292b2d;
      overflow-wrap: anywhere;
    }
    .post-body p { margin: 0 0 17px; }
    .post-body h2 { margin: 25px 0 12px; font-size: 22px; line-height: 1.4; }
    .post-body ul { margin: 5px 0 18px; padding-left: 27px; }
    .post-body li { margin: 5px 0; }
    .post-body blockquote {
      margin: 10px 0 18px;
      padding: 10px 14px;
      border-left: 4px solid #8ed7fa;
      background: #f4f8fa;
      color: #555b60;
    }
    .post-body pre {
      margin: 12px 0 18px;
      padding: 14px 16px;
      border-radius: 4px;
      background: #f2f3f4;
      color: #35383a;
      white-space: pre-wrap;
      font: 14px/1.6 "SFMono-Regular", Consolas, monospace;
    }
    .detail-row, .image-placeholder {
      display: block;
      margin: 8px 0;
      padding: 10px 13px;
      background: #f3f3f3;
      color: #46494c;
      font-size: 15px;
      line-height: 1.4;
      border-radius: 2px;
    }
    .detail-row::before { content: "▶"; margin-right: 9px; color: #333; }
    .image-placeholder::before { content: "▧"; margin-right: 8px; color: #0b9bd8; }
    .post-image {
      margin: 12px 0 20px;
      padding: 0;
    }
    .post-image img {
      display: block;
      max-width: 100%;
      height: auto;
      border-radius: 5px;
      border: 1px solid #e4e6e8;
      background: #f4f5f6;
    }
    .post-image figcaption {
      margin-top: 6px;
      color: #8b8e91;
      font-size: 13px;
      line-height: 1.45;
    }
    .link { color: #0098dd; overflow-wrap: anywhere; }
    .truncated {
      margin: 20px 0;
      padding: 10px 13px;
      background: #fff5db;
      color: #886722;
      border-radius: 4px;
      font-size: 14px;
    }
    .footer {
      margin: 30px 58px 0 132px;
      padding-top: 17px;
      border-top: 1px solid #e5e6e7;
      color: #96999b;
      font-size: 13px;
      line-height: 1.6;
      overflow-wrap: anywhere;
    }
    .footer .source { color: #168ec6; }
  </style>
</head>
<body>{{ text|safe }}</body>
</html>"""


def _logo_svg(css_class: str, clip_id: str) -> str:
    return f"""<svg class="{css_class}" viewBox="0 0 48 48"
      xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs><clipPath id="{clip_id}"><circle cx="24" cy="24" r="21"/></clipPath></defs>
      <g clip-path="url(#{clip_id})">
        <rect x="3" y="3" width="42" height="14" fill="#d9d9d7"/>
        <rect x="3" y="17" width="42" height="16" fill="#ffffff"/>
        <rect x="3" y="33" width="42" height="12" fill="#ffe7a0"/>
      </g>
      <circle cx="24" cy="24" r="21" fill="none" stroke="#d7d9da"
        stroke-width="1.25"/>
    </svg>"""


def _render_topic_image(
    match: re.Match[str],
    images: dict[int, EmbeddedTopicImage],
) -> str:
    position = int(match.group("position"))
    alt = (match.group("alt") or "").strip()
    loaded = images.get(position)
    safe_alt = html.escape(alt or f"帖子图片 {position}", quote=True)
    if loaded is None:
        return (
            '<div class="image-placeholder">'
            f"图片加载失败或超过限制：{safe_alt}</div>"
        )
    data_uri = html.escape(loaded.data_uri, quote=True)
    caption = f"<figcaption>{safe_alt}</figcaption>" if alt else ""
    return (
        f'<figure class="post-image"><img src="{data_uri}" alt="{safe_alt}" '
        f'width="{loaded.width}" height="{loaded.height}">{caption}</figure>'
    )


def _decorate_inline(
    text: str,
    images: dict[int, EmbeddedTopicImage] | None = None,
) -> str:
    image_map = images or {}
    escaped = html.escape(text, quote=True)

    def replace_placeholder(match: re.Match[str]) -> str:
        alt = match.group("alt")
        count = match.group("count")
        if count:
            label = f"另有 {count} 张图片暂未展示"
        elif alt:
            label = f"图片暂未展示：{alt}"
        else:
            label = "图片暂未展示"
        return f'<span class="image-placeholder">{label}</span>'

    escaped = _IMAGE_PLACEHOLDER_RE.sub(replace_placeholder, escaped)
    escaped = _IMAGE_TOKEN_RE.sub(
        lambda match: _render_topic_image(match, image_map), escaped
    )
    return _URL_RE.sub(
        lambda match: f'<span class="link">{match.group(0)}</span>',
        escaped,
    )


def content_to_safe_html(
    content: str,
    embedded_images: Sequence[EmbeddedTopicImage] = (),
) -> str:
    image_map = {image.position: image for image in embedded_images}
    blocks = re.split(r"\n\s*\n", content.strip()) if content.strip() else []
    rendered: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        if all(line.startswith("• ") for line in lines):
            items = "".join(
                f"<li>{_decorate_inline(line[2:].strip(), image_map)}</li>"
                for line in lines
            )
            rendered.append(f"<ul>{items}</ul>")
            continue

        if all(line.startswith("│ ") for line in lines):
            quote = "<br>".join(
                _decorate_inline(line[2:], image_map) for line in lines
            )
            rendered.append(f"<blockquote>{quote}</blockquote>")
            continue

        if len(lines) == 1:
            image_match = _IMAGE_TOKEN_RE.fullmatch(lines[0])
            if image_match:
                rendered.append(_render_topic_image(image_match, image_map))
                continue

            title_match = _STANDALONE_TITLE_RE.fullmatch(lines[0])
            if title_match:
                title = title_match.group("title")
                css_class = (
                    "detail-row"
                    if any(token in title for token in ("图片", "折叠", "图集"))
                    else "section-title"
                )
                if css_class == "detail-row":
                    rendered.append(
                        f'<div class="detail-row">'
                        f"{_decorate_inline(title, image_map)}</div>"
                    )
                else:
                    rendered.append(
                        f"<h2>{_decorate_inline(title, image_map)}</h2>"
                    )
                continue

            if lines[0] == "[正文过长，已截断]":
                rendered.append('<div class="truncated">正文过长，已截断</div>')
                continue

        paragraph = "<br>".join(
            _decorate_inline(line, image_map) for line in lines
        )
        rendered.append(f"<p>{paragraph}</p>")

    return "".join(rendered) or "<p>首帖正文为空</p>"


def build_preview_fragment(
    preview: TopicPreview,
    embedded_images: Sequence[EmbeddedTopicImage] = (),
) -> str:
    title = html.escape(preview.title, quote=True)
    category = html.escape(preview.category, quote=True)
    canonical_url = html.escape(preview.canonical_url, quote=True)
    category_pill = f'<span class="pill">{category}</span>' if category else ""
    truncated_pill = (
        '<span class="pill pill-blue">正文已截断</span>' if preview.truncated else ""
    )
    body = content_to_safe_html(preview.content, embedded_images)
    if preview.total_image_count:
        image_note = (
            f"帖子图片：已加载 {len(embedded_images)}/{preview.total_image_count} 张"
            f"（本次最多处理 {len(preview.images)} 张）。"
        )
    else:
        image_note = "正文未包含帖子图片。"
    brand_logo = _logo_svg("brand-mark", "brand-logo-clip")
    avatar_logo = _logo_svg("avatar", "avatar-logo-clip")
    return f"""<main class="page">
  <header class="topbar">
    <div class="brand">
      {brand_logo}
      <span class="brand-name">LINUX DO</span>
    </div>
    <span class="edition">公开首帖 · 图片限量版</span>
  </header>
  <div class="notice"><b>真诚、友善、团结、专业</b>，共建你我引以为荣之社区。</div>
  <section class="topic">
    <h1 class="topic-title">{title}</h1>
    <div class="topic-meta">
      {category_pill}
      <span class="pill">主题 #{preview.topic_id}</span>
      {truncated_pill}
    </div>
    <article class="post">
      {avatar_logo}
      <div>
        <div class="author-row">
          <span class="author-name">LINUX DO 社区</span>
          <span class="op-badge">TOPIC OWNER</span>
        </div>
        <div class="post-body">{body}</div>
      </div>
    </article>
  </section>
  <footer class="footer">
    原帖：<span class="source">{canonical_url}</span><br>
    由 AstrBot 生成；{image_note}
  </footer>
</main>"""


def build_render_options(quality: int) -> dict[str, object]:
    return {
        "full_page": True,
        "type": "jpeg",
        "quality": max(60, min(95, int(quality))),
    }
