from linuxdo_preview.urls import extract_topic_refs


def test_extracts_supported_topic_and_raw_variants_in_order():
    refs = extract_topic_refs(
        "看看 https://linux.do/t/topic/2045356/3 和 linux.do/raw/2349758/1",
        limit=3,
    )
    assert [ref.topic_id for ref in refs] == [2045356, 2349758]
    assert refs[0].raw_first_post_url == "https://linux.do/raw/2045356/1"


def test_deduplicates_same_topic_and_strips_punctuation():
    refs = extract_topic_refs(
        "(https://linux.do/t/a-slug/42)。https://www.linux.do/raw/42?x=1",
        limit=5,
    )
    assert len(refs) == 1
    assert refs[0].topic_id == 42
    assert refs[0].original_url == "https://linux.do/t/a-slug/42"


def test_rejects_lookalike_domains_and_non_topic_routes():
    refs = extract_topic_refs(
        "https://evil-linux.do/t/topic/123 https://linux.do/u/topic/456 "
        "https://linux.do.evil.example/t/topic/789",
        limit=5,
    )
    assert refs == []
