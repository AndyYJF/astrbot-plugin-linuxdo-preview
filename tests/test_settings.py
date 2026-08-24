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
