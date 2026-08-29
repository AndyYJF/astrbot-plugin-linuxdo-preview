from __future__ import annotations

import html
import re

from .models import CleanedTopicContent, TopicImage, TopicPreview

_BIDI_AND_ZERO_WIDTH_RE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^\s)]+)(?:\s+[^)]*)?\)"
)
_DISCOURSE_LINKED_IMAGE_RE = re.compile(
    r"\[!\[(?P<alt>[^\]]*)\]\("
    r"(?P<preview>https?://[^\s)]+)(?:\s+\"[^\"]*\")?\)"
    r"[^\]\n]{0,300}\]\("
    r"(?P<url>https?://[^\s)]+)(?:\s+\"[^\"]*\")?\)"
)
_LINKED_IMAGE_RE = re.compile(
    r"\[(?P<image>!\[[^\]]*\]\([^\s)]+(?:\s+[^)]*)?\))\]"
    r"\(https?://[^\s)]+\)"
)
_MEDIA_URL_RE = re.compile(
    r"https?://[^\s)\]\"']+\.(?:avif|gif|jpe?g|png|webp)"
    r"(?:\?[^\s)\]\"']*)?",
    re.I,
)
_EMPTY_LINK_RE = re.compile(r"(?<!!)\[\s*\]\([^()\n]{0,500}\)")
_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>https?://[^\s)]+)\)")
_HTML_TAG_RE = re.compile(r"<[^>]{1,500}>")
_COOKED_IMAGE_TAG_RE = re.compile(r"<img\b[^>]{0,1000}>", re.I)
_COOKED_IMAGE_ATTR_RE = re.compile(
    r"\b(?P<attr>src|alt|class)\s*=\s*\"(?P<value>[^\"]{0,2000})\"",
    re.I,
)
_COOKED_ONEBOX_RE = re.compile(
    r"<aside\b[^>]{0,300}\bclass=\"[^\"]*\bonebox\b[^\"]*\"[^>]{0,300}>.*?</aside>",
    re.I | re.S,
)
_COOKED_DECORATIVE_CLASS_RE = re.compile(
    r"\b(?:site-icon|thumbnail|avatar|emoji)\b",
    re.I,
)
_COOKED_LIGHTBOX_RE = re.compile(
    r"<a\b[^>]{0,300}\bclass=\"[^\"]*\blightbox\b[^\"]*\"[^>]{0,300}?"
    r"\bhref=\"(?P<original>https?://[^\"\s]{1,2000})\"[^>]{0,300}>\s*"
    r"<img\b(?P<imgattrs>[^>]{0,1000})>",
    re.I,
)
_UPLOAD_PLACEHOLDER_RE = re.compile(r"\[图片暂未展示(?:：[^\]]*)?\]")
_BOLD_MD_RE = re.compile(r"(?<!\w)(?:\*\*|__)(.+?)(?:\*\*|__)(?!\w)")


def strip_bold_markers(text: str) -> str:
    """Remove bold emphasis markers for plain-text outputs."""
    return _BOLD_MD_RE.sub(r"\1", text)
_DETAILS_OPEN_RE = re.compile(r"\[details(?:=\"?(?P<title>[^\]\"]+)\"?)?\]", re.I)
_QUOTE_OPEN_RE = re.compile(r"\[quote(?:=\"?(?P<who>[^\]\"]+)\"?)?\]", re.I)


def clean_discourse_content(
    raw: str,
    max_chars: int,
    max_images: int,
) -> CleanedTopicContent:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _BIDI_AND_ZERO_WIDTH_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)

    image_count = 0
    visible_images = 0
    images: list[TopicImage] = []

    def image_placeholder(
        url: str,
        alt: str = "",
        preview_url: str | None = None,
    ) -> str:
        nonlocal image_count, visible_images
        alt = alt.split("|")[0].strip()
        if "/images/emoji/" in url:
            emoji = re.search(r":[a-zA-Z0-9_+\-]+:", alt)
            return emoji.group(0) if emoji else ""

        image_count += 1
        if visible_images >= max(0, max_images):
            return ""
        visible_images += 1
        alt = re.sub(r"^Image\s+\d+\s*:\s*", "", alt, flags=re.I)[:80].strip()
        if url.startswith(("https://", "http://")):
            image = TopicImage(
                position=visible_images,
                alt=alt,
                source_url=url,
                preview_url=preview_url,
            )
            images.append(image)
            return image.marker
        return f"[图片暂未展示：{alt}]" if alt else "[图片暂未展示]"

    def replace_image(match: re.Match[str]) -> str:
        return image_placeholder(match.group("url"), match.group("alt"))

    text = _DISCOURSE_LINKED_IMAGE_RE.sub(
        lambda match: image_placeholder(
            match.group("url"),
            match.group("alt"),
            preview_url=match.group("preview"),
        ),
        text,
    )
    text = _LINKED_IMAGE_RE.sub(lambda match: match.group("image"), text)
    text = _IMAGE_RE.sub(replace_image, text)
    text = _MEDIA_URL_RE.sub(lambda match: image_placeholder(match.group(0)), text)
    text = re.sub(r"^\s*[\[\]]\s*$", "", text, flags=re.M)
    text = _DETAILS_OPEN_RE.sub(
        lambda match: f"\n【{(match.group('title') or '折叠内容').strip()}】\n", text
    )
    text = re.sub(r"\[/details\]", "\n", text, flags=re.I)
    text = re.sub(r"\[/?grid\]", "\n", text, flags=re.I)

    def replace_quote(match: re.Match[str]) -> str:
        who = match.group("who")
        suffix = f"：{who}" if who else ""
        return f"\n【引用{suffix}】\n"

    text = _QUOTE_OPEN_RE.sub(replace_quote, text)
    text = re.sub(r"\[/quote\]", "\n", text, flags=re.I)
    text = re.sub(r"\[/?spoiler\]", "", text, flags=re.I)
    text = re.sub(
        r"\[/?(?:center|left|right|color(?:=[^\]]+)?|size(?:=[^\]]+)?)\]",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?:p|div|ul|ol|pre|blockquote)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.I)
    text = re.sub(r"</li>", "\n", text, flags=re.I)
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)

    # Jina emits invisible Discourse heading anchors as
    # ``## [](https://linux.do/t/topic/123#heading)Visible heading``.
    # They have no user-facing label, so remove them before heading decoration.
    # The negative lookbehind keeps empty-alt Markdown images intact.
    text = _EMPTY_LINK_RE.sub("", text)
    text = _LINK_RE.sub(
        lambda match: (
            match.group("url")
            if match.group("label").strip() == match.group("url")
            else f"{match.group('label').strip()}：{match.group('url')}"
        ),
        text,
    )
    text = re.sub(r"^#{1,6}\s*(.+)$", r"【\1】", text, flags=re.M)
    text = re.sub(r"^\s*>\s?", "│ ", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "• ", text, flags=re.M)
    text = re.sub(r"```[^\n]*\n?", "\n【代码】\n", text)
    # Bold markers stay in the text: the HTML renderer styles them and the
    # plain-text builders strip them, so both output kinds stay readable.
    text = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"\1", text)
    text = text.replace("[CQ:", "［CQ:")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if image_count > visible_images:
        text = (
            f"{text}\n\n[另有 {image_count - visible_images} 张图片暂未展示]"
        ).strip()

    truncated = len(text) > max_chars
    if truncated:
        cut = text[: max(1, max_chars - 18)]
        boundary = max(cut.rfind("\n\n"), cut.rfind("\n"), cut.rfind("。"))
        if boundary >= max_chars // 2:
            cut = cut[: boundary + (1 if cut[boundary] == "。" else 0)]
        text = f"{cut.rstrip()}\n\n[正文过长，已截断]"
    visible_refs = tuple(image for image in images if image.marker in text)
    return CleanedTopicContent(
        text=text,
        truncated=truncated,
        images=visible_refs,
        total_image_count=image_count,
    )


def merge_cooked_images(
    cleaned: CleanedTopicContent,
    cooked: str,
    max_images: int,
) -> CleanedTopicContent:
    """Merge absolute HTTPS images that exist only in Discourse cooked HTML.

    Authenticated single-post raw markdown does not always carry image syntax
    (for example oneboxed uploads), so the rendered ``cooked`` HTML is the only
    place those post images appear. Onebox preview thumbnails/site icons are
    excluded. Newly found images replace ``[图片暂未展示…]`` placeholders left
    by unresolvable ``upload://`` raw refs in document order; any remainder is
    appended after the text in cooked order.
    """
    if not cooked.strip():
        return cleaned
    body = _COOKED_ONEBOX_RE.sub("", cooked)
    known = {image.source_url for image in cleaned.images}
    known.update(
        image.preview_url for image in cleaned.images if image.preview_url
    )
    text = cleaned.text
    images = list(cleaned.images)
    found = 0
    appended = 0
    candidates: list[tuple[int, str, str | None, dict[str, str]]] = []
    lightbox_spans: list[tuple[int, int]] = []
    for anchor in _COOKED_LIGHTBOX_RE.finditer(body):
        attributes = {
            attr.group("attr").lower(): attr.group("value")
            for attr in _COOKED_IMAGE_ATTR_RE.finditer(anchor.group("imgattrs"))
        }
        candidates.append(
            (
                anchor.start(),
                anchor.group("original"),
                attributes.get("src") or None,
                attributes,
            )
        )
        lightbox_spans.append(anchor.span())
    for tag_match in _COOKED_IMAGE_TAG_RE.finditer(body):
        if any(start <= tag_match.start() < end for start, end in lightbox_spans):
            continue
        attributes = {
            attr.group("attr").lower(): attr.group("value")
            for attr in _COOKED_IMAGE_ATTR_RE.finditer(tag_match.group(0))
        }
        candidates.append(
            (tag_match.start(), attributes.get("src", ""), None, attributes)
        )
    candidates.sort(key=lambda item: item[0])

    for _start, url, preview_url, attributes in candidates:
        if (
            not url.startswith(("https://", "http://"))
            or "/images/emoji/" in url
            or _COOKED_DECORATIVE_CLASS_RE.search(attributes.get("class", ""))
            or url in known
        ):
            continue
        found += 1
        known.add(url)
        if preview_url:
            known.add(preview_url)
        if len(images) >= max(0, max_images):
            continue
        appended += 1
        alt = re.sub(r"^Image\s+\d+\s*:\s*", "", attributes.get("alt", ""), flags=re.I)
        image = TopicImage(
            position=len(images) + 1,
            alt=alt.split("|")[0].strip()[:80],
            source_url=url,
            preview_url=preview_url,
        )
        images.append(image)
        text, replaced = _UPLOAD_PLACEHOLDER_RE.subn(image.marker, text, count=1)
        if not replaced:
            text = f"{text}\n\n{image.marker}" if text else image.marker
    if found > appended:
        text = (
            f"{text}\n\n[另有 {found - appended} 张图片暂未展示]"
        ).strip()
    return CleanedTopicContent(
        text=text,
        truncated=cleaned.truncated,
        images=tuple(images),
        total_image_count=cleaned.total_image_count + found,
    )


def clean_discourse_markdown(raw: str, max_chars: int) -> tuple[str, bool]:
    """Compatibility text-only cleaner used by older callers and focused tests."""
    cleaned = clean_discourse_content(raw, max_chars=max_chars, max_images=5)
    text = re.sub(
        r"\[帖子图片#\d+(?:：(?P<alt>[^\]]+))?\]",
        lambda match: (
            f"[图片暂未展示：{match.group('alt')}]"
            if match.group("alt")
            else "[图片暂未展示]"
        ),
        cleaned.text,
    )
    return strip_bold_markers(text), cleaned.truncated


def build_preview_text(preview: TopicPreview) -> str:
    truncation_note = "（内容已截断）" if preview.truncated else ""
    return (
        f"【{preview.title} · #{preview.topic_id}】{truncation_note}\n\n"
        f"{strip_bold_markers(preview.content)}\n\n"
        f"原帖：{preview.canonical_url}"
    )


def build_plain_preview(preview: TopicPreview, max_chars: int) -> str:
    full = build_preview_text(preview)
    if len(full) <= max_chars:
        return full

    header = f"【{preview.title} · #{preview.topic_id}】\n\n"
    footer = f"\n\n[内容较长，请查看原帖]\n原帖：{preview.canonical_url}"
    available = max(1, max_chars - len(header) - len(footer))
    content = preview.content[:available]
    boundary = max(content.rfind("\n\n"), content.rfind("\n"), content.rfind("。"))
    if boundary >= available // 2:
        content = content[: boundary + (1 if content[boundary] == "。" else 0)]
    return f"{header}{content.rstrip()}{footer}"


def split_text(text: str, chunk_chars: int, max_chunks: int) -> list[str]:
    if chunk_chars <= 0 or max_chunks <= 0:
        return []
    remaining = text.strip()
    chunks: list[str] = []
    while remaining and len(chunks) < max_chunks:
        if len(remaining) <= chunk_chars:
            chunks.append(remaining)
            remaining = ""
            break
        window = remaining[:chunk_chars]
        boundary = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind("。"))
        if boundary < chunk_chars // 2:
            boundary = chunk_chars
        elif window[boundary] == "。":
            boundary += 1
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].lstrip()
    if remaining and chunks:
        marker = "\n\n[其余内容请查看原帖]"
        shortened = chunks[-1][: max(1, chunk_chars - len(marker))].rstrip()
        chunks[-1] = f"{shortened}{marker}"
    return chunks


def build_forward_chunks(
    preview: TopicPreview, chunk_chars: int, max_chunks: int
) -> list[str]:
    body_chunks = split_text(preview.content, chunk_chars, max_chunks)
    if not body_chunks:
        body_chunks = ["[首帖正文为空]"]
    truncation_note = "（内容已截断）" if preview.truncated else ""
    body_chunks[0] = (
        f"【{preview.title} · #{preview.topic_id}】{truncation_note}\n\n"
        f"{body_chunks[0]}"
    )
    body_chunks[-1] = f"{body_chunks[-1]}\n\n原帖：{preview.canonical_url}"
    return body_chunks


def error_message(topic_id: int, code: str) -> str:
    messages = {
        "auth_forbidden": (
            f"已授权的 LINUX DO 账号仍无权查看帖子 #{topic_id}，或帖子已删除。"
        ),
        "auth_invalid": "LINUX DO 只读登录授权已失效，请联系管理员重新授权。",
        "auth_unavailable": "LINUX DO 登录通道尚未配置完成，请联系管理员。",
        "not_found": f"LINUX DO 帖子 #{topic_id} 不存在或已删除。",
        "restricted": (
            f"LINUX DO 帖子 #{topic_id} 需要登录或更高信任等级；"
            "当前 QQ 会话没有获得登录抓取授权。"
        ),
        "rate_limited": "LINUX DO 预览服务请求过多，请稍后再试。",
        "too_large": f"LINUX DO 帖子 #{topic_id} 返回内容过大，已停止读取。",
        "challenge": "LINUX DO 的 Cloudflare 校验未能通过，请稍后再试。",
        "render_failed": f"LINUX DO 帖子 #{topic_id} 长图生成失败，请稍后再试。",
    }
    return messages.get(code, f"暂时无法读取 LINUX DO 帖子 #{topic_id}，请稍后再试。")
