from datetime import datetime
from pathlib import Path

from src.logger import logger
from src.models import UploadConfig
from src.uploader.service import (
    RcloneResult,
    RcloneUploadService,
    build_rclone_config_create_command,
    build_rclone_move_command,
    parse_rclone_duration_seconds,
    prepare_upload_config_for_run,
    resolve_upload_source,
    seconds_until_next_daily_run,
)


def capture_logs():
    messages = []
    sink_id = logger.add(messages.append, format="{level}|{message}", level="DEBUG", diagnose=False)
    return messages, sink_id


def test_build_rclone_move_command_uses_safe_webdav_defaults(tmp_path):
    source = tmp_path / "downloads"
    config = UploadConfig(enabled=True)

    command = build_rclone_move_command(config, source)

    assert command == [
        "rclone",
        "move",
        str(source),
        "123pan:/LiveBackup/",
        "--min-age",
        "1h",
        "--transfers",
        "2",
        "--checkers",
        "2",
        "--retries",
        "3",
        "--stats",
        "1m",
        "-v",
        "--delete-empty-src-dirs",
    ]


def test_build_rclone_move_command_excludes_protected_recording_patterns(tmp_path):
    source = tmp_path / "downloads"
    config = UploadConfig(enabled=True, exclude_patterns=("*.converting.mp4", "*.ts"))

    command = build_rclone_move_command(config, source)

    assert command[-4:] == [
        "--exclude",
        "*.converting.mp4",
        "--exclude",
        "*.ts",
    ]


def test_recording_finished_upload_runs_without_min_age_filter():
    config = UploadConfig(enabled=True, trigger_mode="录制结束", min_age="1h")

    prepared = prepare_upload_config_for_run(config)

    assert prepared.min_age == "0s"
    assert config.min_age == "1h"


def test_scheduled_upload_keeps_configured_min_age_filter():
    config = UploadConfig(enabled=True, trigger_mode="间隔", min_age="1h")

    prepared = prepare_upload_config_for_run(config)

    assert prepared.min_age == "1h"
    assert prepared is config


def test_build_rclone_move_command_honors_custom_binary_and_dry_run(tmp_path):
    source = tmp_path / "custom"
    config = UploadConfig(
        enabled=True,
        remote_path="backup:/rooms/",
        rclone_path="C:\\Tools\\rclone\\rclone.exe",
        min_age="2h",
        transfers=1,
        checkers=1,
        rclone_retries=4,
        delete_empty_dirs=False,
        dry_run=True,
    )

    command = build_rclone_move_command(config, source)

    assert command == [
        "C:\\Tools\\rclone\\rclone.exe",
        "move",
        str(source),
        "backup:/rooms/",
        "--min-age",
        "2h",
        "--transfers",
        "1",
        "--checkers",
        "1",
        "--retries",
        "4",
        "--stats",
        "1m",
        "-v",
        "--dry-run",
    ]


def test_build_rclone_move_command_resolves_relative_binary_from_app_root(tmp_path):
    source = tmp_path / "custom"
    app_root = tmp_path / "app"
    config = UploadConfig(enabled=True, rclone_path="rclone\\rclone.exe")

    command = build_rclone_move_command(config, source, app_root=app_root)

    assert command[0] == str(app_root / "rclone" / "rclone.exe")


def test_build_rclone_move_command_preserves_absolute_binary(tmp_path):
    source = tmp_path / "custom"
    config = UploadConfig(enabled=True, rclone_path="C:\\Tools\\rclone\\rclone.exe")

    command = build_rclone_move_command(config, source, app_root=tmp_path / "app")

    assert command[0] == "C:\\Tools\\rclone\\rclone.exe"


def test_build_rclone_config_create_command_uses_plain_webdav_settings():
    config = UploadConfig(
        enabled=True,
        rclone_path="C:\\Tools\\rclone\\rclone.exe",
        webdav_remote_name="123pan",
        webdav_url="https://webdav.example.com/dav",
        webdav_username="user@example.com",
        webdav_password="plain-password",
        webdav_vendor="other",
    )

    command = build_rclone_config_create_command(config)

    assert command == [
        "C:\\Tools\\rclone\\rclone.exe",
        "config",
        "create",
        "123pan",
        "webdav",
        "url",
        "https://webdav.example.com/dav",
        "vendor",
        "other",
        "user",
        "user@example.com",
        "pass",
        "plain-password",
        "--non-interactive",
        "--obscure",
    ]


def test_build_rclone_config_create_command_skips_incomplete_webdav_settings():
    assert build_rclone_config_create_command(UploadConfig(webdav_remote_name="123pan")) is None


def test_resolve_upload_source_prefers_upload_source_then_recording_then_default(tmp_path):
    config = UploadConfig(source_path=str(tmp_path / "upload"))

    assert resolve_upload_source(config, "D:\\Records", tmp_path / "downloads") == Path(config.source_path)
    assert resolve_upload_source(UploadConfig(), "D:\\Records", tmp_path / "downloads") == Path("D:\\Records")
    assert resolve_upload_source(UploadConfig(), "", tmp_path / "downloads") == tmp_path / "downloads"


def test_run_once_skips_missing_or_empty_source(tmp_path):
    calls = []
    service = RcloneUploadService(UploadConfig(enabled=True), runner=lambda command: calls.append(command))

    result = service.run_once(tmp_path / "missing")

    assert result.phase == "skipped"
    assert result.exit_code == 0
    assert calls == []
    assert service.status.phase == "skipped"


def test_run_once_marks_success_and_records_output(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    calls = []

    def runner(command):
        calls.append(command)
        (source / "room.ts").unlink()
        return RcloneResult(exit_code=0, stdout="Transferred: 1 file", stderr="")

    service = RcloneUploadService(UploadConfig(enabled=True), runner=runner)

    result = service.run_once(source)

    assert result.phase == "success"
    assert result.attempts == 1
    assert result.exit_code == 0
    assert "Transferred" in result.stdout
    assert len(calls) == 1
    assert service.status.phase == "success"


def test_run_once_reports_partial_success_when_files_remain_after_move(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    remaining = source / "still-cooling.ts"
    remaining.write_bytes(b"x" * 5)

    def runner(_command):
        return RcloneResult(exit_code=0, stdout="Transferred: 1 file", stderr="")

    service = RcloneUploadService(UploadConfig(enabled=True), runner=runner)

    result = service.run_once(source)

    assert result.phase == "partial"
    assert result.files_total == 1
    assert result.files_remaining == 1
    assert result.bytes_remaining == 5
    assert "仍有 1 个文件待上传" in result.message


def test_run_once_logs_partial_success_with_remaining_file_context(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "still-cooling.ts").write_bytes(b"x" * 5)

    def runner(_command):
        return RcloneResult(exit_code=0, stdout="Transferred: 1 file", stderr="")

    service = RcloneUploadService(UploadConfig(enabled=True), runner=runner)
    messages, sink_id = capture_logs()
    try:
        result = service.run_once(source)
    finally:
        logger.remove(sink_id)

    output = "\n".join(messages)
    assert result.phase == "partial"
    assert "upload attempt started" in output
    assert "upload partially completed" in output
    assert f"source={source}" in output
    assert "remote=123pan:/LiveBackup/" in output
    assert "files_remaining=1" in output
    assert "bytes_remaining=5" in output


def test_run_once_ignores_excluded_files_when_deciding_success(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    uploaded = source / "room.mp4"
    protected = source / "room.ts"
    uploaded.write_bytes(b"x")
    protected.write_bytes(b"raw")

    def runner(_command):
        uploaded.unlink()
        return RcloneResult(exit_code=0, stdout="Transferred: 1 file", stderr="")

    service = RcloneUploadService(UploadConfig(enabled=True, exclude_patterns=("*.ts",)), runner=runner)

    result = service.run_once(source)

    assert result.phase == "success"
    assert result.files_remaining == 0
    assert protected.exists()


def test_run_once_skips_when_only_excluded_files_exist(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"raw")
    calls = []

    service = RcloneUploadService(
        UploadConfig(enabled=True, app_retries=0, exclude_patterns=("*.ts",)),
        runner=lambda command: calls.append(command) or RcloneResult(exit_code=1),
        sleeper=lambda _seconds: None,
    )

    result = service.run_once(source)

    assert result.phase == "skipped"
    assert calls == []


def test_run_once_prepares_webdav_remote_before_upload(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    calls = []

    def runner(command):
        calls.append(command)
        if command[1] == "move":
            (source / "room.ts").unlink()
        return RcloneResult(exit_code=0, stdout="ok", stderr="")

    service = RcloneUploadService(
        UploadConfig(
            enabled=True,
            webdav_remote_name="123pan",
            webdav_url="https://webdav.example.com/dav",
            webdav_username="user@example.com",
            webdav_password="plain-password",
        ),
        runner=runner,
    )

    result = service.run_once(source)

    assert result.phase == "success"
    assert calls[0][:5] == ["rclone", "config", "create", "123pan", "webdav"]
    assert calls[1][:2] == ["rclone", "move"]


def test_webdav_remote_config_failure_logs_without_password(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")

    def runner(_command):
        return RcloneResult(exit_code=7, stderr="login failed")

    service = RcloneUploadService(
        UploadConfig(
            enabled=True,
            webdav_remote_name="123pan",
            webdav_url="https://webdav.example.com/dav?token=abc",
            webdav_username="user@example.com",
            webdav_password="plain-password",
        ),
        runner=runner,
    )
    messages, sink_id = capture_logs()
    try:
        result = service.run_once(source)
    finally:
        logger.remove(sink_id)

    output = "\n".join(messages)
    assert result.phase == "failed"
    assert "upload remote config failed" in output
    assert "plain-password" not in output
    assert "token=abc" not in output
    assert "[REDACTED]" in output


def test_run_once_retries_failed_uploads_with_app_retry_limit(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    sleeps = []
    calls = []

    def runner(command):
        calls.append(command)
        return RcloneResult(exit_code=9, stdout="", stderr="webdav timeout")

    service = RcloneUploadService(
        UploadConfig(enabled=True, app_retries=2, retry_sleep_seconds=15),
        runner=runner,
        sleeper=lambda seconds: sleeps.append(seconds),
    )

    result = service.run_once(source)

    assert result.phase == "failed"
    assert result.attempts == 3
    assert result.exit_code == 9
    assert result.stderr == "webdav timeout"
    assert len(calls) == 3
    assert sleeps == [15, 15]
    assert service.status.phase == "failed"


def test_run_once_logs_failed_attempts_with_exit_code_and_context(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")

    def runner(_command):
        return RcloneResult(exit_code=9, stdout="", stderr="webdav timeout token=abc")

    service = RcloneUploadService(
        UploadConfig(enabled=True, app_retries=1, retry_sleep_seconds=0),
        runner=runner,
        sleeper=lambda _seconds: None,
    )
    messages, sink_id = capture_logs()
    try:
        result = service.run_once(source)
    finally:
        logger.remove(sink_id)

    output = "\n".join(messages)
    assert result.phase == "failed"
    assert "upload attempt started" in output
    assert "upload attempt failed" in output
    assert "upload failed" in output
    assert "exit_code=9" in output
    assert "attempt=2" in output
    assert f"source={source}" in output
    assert "remote=123pan:/LiveBackup/" in output
    assert "token=abc" not in output


def test_run_once_accepts_123pan_object_not_found_when_remote_files_verify(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    file = source / "room.ts"
    file.write_bytes(b"x")
    calls = []

    def runner(command):
        calls.append(command)
        if "lsjson" in command:
            return RcloneResult(
                exit_code=0,
                stdout='[{"Path":"room.ts","Name":"room.ts","Size":1,"IsDir":false}]',
            )
        return RcloneResult(exit_code=4, stdout="Transferred: 1 B / 1 B, 100%", stderr="object not found")

    service = RcloneUploadService(UploadConfig(enabled=True, app_retries=0), runner=runner)

    result = service.run_once(source)

    assert result.phase == "success"
    assert result.exit_code == 0
    assert "remote verification" in result.message
    assert not file.exists()
    assert any("lsjson" in call for call in calls)


def test_seconds_until_next_daily_run_uses_today_when_time_is_future():
    now = datetime(2026, 6, 28, 2, 30, 0)

    assert seconds_until_next_daily_run("03:00", now) == 1800


def test_seconds_until_next_daily_run_rolls_to_tomorrow_when_time_has_passed():
    now = datetime(2026, 6, 28, 3, 1, 0)

    assert seconds_until_next_daily_run("03:00", now) == 86340


def test_seconds_until_next_daily_run_falls_back_for_invalid_time():
    now = datetime(2026, 6, 28, 3, 1, 0)

    assert seconds_until_next_daily_run("bad", now) == 60


def test_parse_rclone_duration_seconds_supports_compound_units():
    assert parse_rclone_duration_seconds("1h30m10s") == 5410
    assert parse_rclone_duration_seconds("2m") == 120
    assert parse_rclone_duration_seconds("0s") == 0


def test_parse_rclone_duration_seconds_ignores_invalid_or_fractional_values():
    assert parse_rclone_duration_seconds("") == 0
    assert parse_rclone_duration_seconds("bad") == 0
    assert parse_rclone_duration_seconds("1.5h") == 0
