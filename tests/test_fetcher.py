import pytest

from linuxdo_preview.fetcher import (
    LinuxDoFetcher,
    is_cloudflare_challenge,
    is_restricted_placeholder,
    parse_reader_page_title,
    parse_reader_topic_response,
    unwrap_reader_response,
)
from linuxdo_preview.models import FetchError, FetchErrorCode, TopicRef
from linuxdo_preview.settings import Settings


def test_detects_cf_mitigated_header():
    assert is_cloudflare_challenge(
        403,
        {"cf-mitigated": "challenge", "content-type": "text/html"},
        "<html>Just a moment...</html>",
    )


def test_does_not_treat_regular_forbidden_as_cf_challenge():
    assert not is_cloudflare_challenge(
        403,
        {"content-type": "text/plain"},
        "You must be logged in",
    )


def test_unwraps_reader_metadata_only_when_wrapper_is_present():
    wrapped = (
        "Title: \n\nURL Source: https://linux.do/raw/123/1\n\nMarkdown Content:\n正文"
    )
    assert unwrap_reader_response(wrapped) == "正文"
    assert unwrap_reader_response("用户正文 Markdown Content: 保留") == (
        "用户正文 Markdown Content: 保留"
    )


def test_parses_topic_title_category_and_cooked_body():
    wrapped = (
        "Title: 主题 - 开发调优 - LINUX DO\n\n"
        "URL Source: https://linux.do/t/topic/123\n\n"
        "Markdown Content:\n楼主正文"
    )
    assert parse_reader_topic_response(wrapped, 123) == (
        "主题",
        "开发调优",
        "楼主正文",
    )
    assert parse_reader_page_title("", 123) == ("LINUX DO 帖子 #123", "")


def test_detects_private_not_found_placeholder_without_matching_normal_posts():
    assert is_restricted_placeholder(
        "Oops! That page doesn’t exist or is private."
    )
    assert is_restricted_placeholder(
        "\n# Oops! That page doesn't exist or is private.\n"
    )
    assert not is_restricted_placeholder(
        "正文中引用：Oops! That page doesn’t exist or is private. 但这里还有内容。"
    )


async def test_reader_private_placeholder_raises_restricted(monkeypatch):
    fetcher = LinuxDoFetcher(Settings())

    async def fake_request(*args, **kwargs):
        return (
            200,
            {"content-type": "text/plain"},
            "Title: \n\nURL Source: https://linux.do/t/topic/123\n\n"
            "Warning: Target URL returned error 404: Not Found\n\n"
            "Markdown Content:\nOops! That page doesn’t exist or is private.",
        )

    monkeypatch.setattr(fetcher, "_request", fake_request)
    with pytest.raises(FetchError) as captured:
        await fetcher._fetch_reader(TopicRef(123, "https://linux.do/t/topic/123"))
    assert captured.value.code is FetchErrorCode.RESTRICTED
    await fetcher.close()


async def test_reader_uses_topic_html_and_op_cooked_selector(monkeypatch):
    fetcher = LinuxDoFetcher(Settings())
    captured = {}

    async def fake_request(url, timeout_seconds, request_headers):
        captured.update(
            url=url,
            timeout_seconds=timeout_seconds,
            request_headers=request_headers,
        )
        return (
            200,
            {"content-type": "text/plain"},
            "Title: 标题 - 福利羊毛 - LINUX DO\n\n"
            "URL Source: https://linux.do/t/topic/123\n\n"
            "Markdown Content:\n仅楼主正文",
        )

    monkeypatch.setattr(fetcher, "_request", fake_request)
    fetched = await fetcher.fetch_first_post(
        TopicRef(123, "https://linux.do/t/topic/123")
    )
    assert captured["url"] == "https://r.jina.ai/https://linux.do/t/topic/123"
    assert captured["request_headers"]["X-Target-Selector"] == "#post_1 .cooked"
    assert captured["request_headers"]["X-No-Cache"] == "true"
    assert fetched.title == "标题"
    assert fetched.category == "福利羊毛"
    assert fetched.content == "仅楼主正文"
    assert fetched.source == "reader-html"
    await fetcher.close()


async def test_reader_rate_limit_fails_fast():
    fetcher = LinuxDoFetcher(Settings(reader_requests_per_minute=1))
    await fetcher._acquire_reader_slot()
    with pytest.raises(FetchError) as captured:
        await fetcher._acquire_reader_slot()
    assert captured.value.code is FetchErrorCode.RATE_LIMITED
    await fetcher.close()
