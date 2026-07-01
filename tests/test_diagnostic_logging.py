from src.diagnostic_logging import format_log_context, sanitize_command, sanitize_for_log
from src.logger import is_play_url_record, is_streamget_record


def test_sanitize_for_log_redacts_sensitive_headers_and_values():
    text = (
        "Cookie: session=abc\n"
        "Authorization: Bearer secret\n"
        "password=my-password token=my-token normal=value"
    )

    sanitized = sanitize_for_log(text)

    assert "session=abc" not in sanitized
    assert "Bearer secret" not in sanitized
    assert "my-password" not in sanitized
    assert "my-token" not in sanitized
    assert "normal=value" in sanitized
    assert "[REDACTED]" in sanitized


def test_sanitize_for_log_redacts_sensitive_url_query_values():
    text = "https://example.test/live.m3u8?token=abc&sign=xyz&quality=origin"

    sanitized = sanitize_for_log(text)

    assert "token=abc" not in sanitized
    assert "sign=xyz" not in sanitized
    assert "quality=origin" in sanitized
    assert "token=%5BREDACTED%5D" in sanitized or "token=[REDACTED]" in sanitized


def test_format_log_context_sorts_keys_and_sanitizes_values():
    context = format_log_context(room_url="https://x.test/?token=abc", anchor_name="Alice", attempt=2)

    assert context == "anchor_name=Alice attempt=2 room_url=https://x.test/?token=%5BREDACTED%5D"


def test_sanitize_command_redacts_sensitive_option_values():
    command = [
        "rclone",
        "config",
        "create",
        "remote",
        "webdav",
        "pass",
        "plain-secret",
        "--password",
        "another-secret",
        "--url",
        "https://example.test/?token=abc",
    ]

    sanitized = sanitize_command(command)

    assert "plain-secret" not in sanitized
    assert "another-secret" not in sanitized
    assert "token=abc" not in sanitized
    assert sanitized[:7] == ("rclone", "config", "create", "remote", "webdav", "pass", "[REDACTED]")


def test_logger_filters_route_technical_info_and_explicit_play_url_records():
    info_record = {"level": {"name": "INFO"}, "extra": {}}
    play_url_record = {"level": {"name": "INFO"}, "extra": {"play_url": True}}

    assert is_streamget_record(info_record) is True
    assert is_streamget_record(play_url_record) is False
    assert is_play_url_record(info_record) is False
    assert is_play_url_record(play_url_record) is True
