from linuxdo_preview.settings import Settings


def test_image_limits_are_clamped_from_plugin_config():
    settings = Settings.from_mapping(
        {
            "max_images_per_topic": 99,
            "max_image_bytes": 1,
            "max_total_image_bytes": 99_000_000,
            "max_forward_image_bytes": 1,
            "max_total_forward_image_bytes": 99_000_000,
            "image_timeout_seconds": 1,
            "render_timeout_seconds": 999,
        }
    )

    assert settings.max_images_per_topic == 12
    assert settings.max_image_bytes == 128_000
    assert settings.max_total_image_bytes == 16_000_000
    assert settings.max_forward_image_bytes == 512_000
    assert settings.max_total_forward_image_bytes == 32_000_000
    assert settings.image_timeout_seconds == 5
    assert settings.render_timeout_seconds == 180


def test_images_can_be_disabled_without_disabling_text_preview():
    settings = Settings.from_mapping({"max_images_per_topic": 0})

    assert settings.max_images_per_topic == 0
    assert settings.enabled is True


def test_authenticated_channel_is_fail_closed_and_clamped():
    defaults = Settings.from_mapping({"authenticated_enabled": True})

    assert defaults.authenticated_enabled is True
    assert defaults.authenticated_sender_allowlist == frozenset()
    assert defaults.authenticated_secret_file.startswith("/AstrBot/data/secrets/")

    configured = Settings.from_mapping(
        {
            "authenticated_sender_allowlist": [" 10001 ", "", 10002],
            "authenticated_secret_file": "/secure/linuxdo.json",
            "authenticated_timeout_seconds": 999,
            "authenticated_requests_per_minute": 99,
            "authenticated_cache_ttl_seconds": 1,
        }
    )
    assert configured.authenticated_sender_allowlist == frozenset(
        {"10001", "10002"}
    )
    assert configured.authenticated_secret_file == "/secure/linuxdo.json"
    assert configured.authenticated_timeout_seconds == 60
    assert configured.authenticated_requests_per_minute == 6
    assert configured.authenticated_cache_ttl_seconds == 30

    legacy = Settings.from_mapping(
        {"authenticated_private_sender_allowlist": ["10003"]}
    )
    assert legacy.authenticated_sender_allowlist == frozenset({"10003"})


def test_authenticated_subject_requires_enabled_explicit_private_sender():
    settings = Settings(
        authenticated_enabled=True,
        authenticated_sender_allowlist=frozenset({"10001"}),
    )

    assert settings.authenticated_subject_for("10001", "") == (
        "qq:10001:private"
    )
    assert settings.authenticated_subject_for("10002", "") is None
    assert settings.authenticated_subject_for("10001", "20001") is None
    assert Settings().authenticated_subject_for("10001", "") is None

    group_settings = Settings(
        authenticated_enabled=True,
        authenticated_sender_allowlist=frozenset({"10001"}),
        authenticated_allow_group_messages=True,
    )
    assert group_settings.authenticated_subject_for("10001", "20001") == (
        "qq:10001:group:20001"
    )
    assert group_settings.authenticated_subject_for("10002", "20001") is None
