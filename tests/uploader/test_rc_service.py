from pathlib import Path

from src.models import UploadConfig
from src.uploader.rc_service import RcloneRcUploadProgress, RcloneRcUploadService
from src.uploader.rclone_rc import RcloneRcError


class FakeDaemon:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1
        return True

    def stop(self):
        self.stopped += 1


class PreparingFakeDaemon(FakeDaemon):
    def __init__(self):
        super().__init__()
        self.prepared = 0

    def prepare_remote(self):
        self.prepared += 1


class FakeRcClient:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.started = []
        self.job_ids = []
        self.delete_on_success_path = None

    def start_move(self, config, source_path):
        self.started.append((config, Path(source_path)))
        return 7

    def job_status(self, job_id):
        self.job_ids.append(job_id)
        status = self.statuses.pop(0)
        if status.get("finished") and status.get("success") and self.delete_on_success_path is not None:
            self.delete_on_success_path.unlink(missing_ok=True)
        return status


def test_rc_upload_service_skips_missing_or_empty_source(tmp_path):
    daemon = FakeDaemon()
    client = FakeRcClient([])
    service = RcloneRcUploadService(UploadConfig(enabled=True, app_retries=0), daemon=daemon, client=client)

    result = service.run_once(tmp_path / "missing")

    assert result.phase == "skipped"
    assert result.exit_code == 0
    assert daemon.started == 0
    assert client.started == []


def test_rc_upload_service_waits_for_async_job_success(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    sleeps = []
    daemon = FakeDaemon()
    client = FakeRcClient(
        [
            {"finished": False, "success": False, "progress": {"percentage": 12.5}},
            {"finished": True, "success": True, "output": {"transferred": "1 file"}},
        ]
    )
    client.delete_on_success_path = source / "room.ts"
    service = RcloneRcUploadService(
        UploadConfig(enabled=True),
        daemon=daemon,
        client=client,
        sleeper=lambda seconds: sleeps.append(seconds),
        poll_interval_seconds=2,
    )

    result = service.run_once(source)

    assert result.phase == "success"
    assert result.exit_code == 0
    assert result.attempts == 1
    assert result.message == "upload completed"
    assert daemon.started == 1
    assert client.started == [(service.config, source)]
    assert client.job_ids == [7, 7]
    assert sleeps == [2]
    assert service.status.phase == "success"


def test_rc_upload_service_prepares_webdav_remote_before_daemon_start(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    daemon = PreparingFakeDaemon()
    client = FakeRcClient([{"finished": True, "success": True, "output": {"transferred": "1 file"}}])
    client.delete_on_success_path = source / "room.ts"
    service = RcloneRcUploadService(
        UploadConfig(
            enabled=True,
            webdav_remote_name="123pan",
            webdav_url="https://webdav.example.com/dav",
            webdav_username="user@example.com",
            webdav_password="plain-password",
        ),
        daemon=daemon,
        client=client,
    )

    result = service.run_once(source)

    assert result.phase == "success"
    assert daemon.prepared == 1
    assert daemon.started == 1


def test_rc_upload_service_reports_progress_callback_from_job_status(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    progress_events = []
    daemon = FakeDaemon()
    client = FakeRcClient(
        [
            {
                "finished": False,
                "success": False,
                "progress": {
                    "percentage": 42.25,
                    "speed": 8_388_608,
                    "bytes": 1_500_000_000,
                    "totalBytes": 3_000_000_000,
                    "name": "room.ts",
                },
            },
            {"finished": True, "success": True, "output": {"transferred": "1 file"}},
        ]
    )
    client.delete_on_success_path = source / "room.ts"
    service = RcloneRcUploadService(
        UploadConfig(enabled=True),
        daemon=daemon,
        client=client,
        sleeper=lambda _seconds: None,
        progress_callback=progress_events.append,
    )

    result = service.run_once(source)

    assert result.phase == "success"
    assert progress_events == [
        RcloneRcUploadProgress(
            percent=42.25,
            speed_bytes_per_second=8_388_608,
            bytes_transferred=1_500_000_000,
            total_bytes=3_000_000_000,
            current_file="room.ts",
        )
    ]
    assert service.status.message == "upload completed"


def test_rc_upload_service_reports_partial_success_when_files_remain_after_job_success(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    client = FakeRcClient([{"finished": True, "success": True, "output": {"transferred": "1 file"}}])
    service = RcloneRcUploadService(UploadConfig(enabled=True), daemon=FakeDaemon(), client=client)

    result = service.run_once(source)

    assert result.phase == "partial"
    assert result.files_remaining == 1
    assert "仍有 1 个文件待上传" in result.message


def test_rc_upload_service_reports_failed_async_job(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    daemon = FakeDaemon()
    client = FakeRcClient([{"finished": True, "success": False, "error": "webdav timeout"}])
    service = RcloneRcUploadService(UploadConfig(enabled=True, app_retries=0), daemon=daemon, client=client)

    result = service.run_once(source)

    assert result.phase == "failed"
    assert result.exit_code == 1
    assert result.stderr == "webdav timeout"
    assert result.attempts == 1
    assert service.status.phase == "failed"


def test_rc_upload_service_treats_failed_job_as_success_when_source_files_are_gone(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    file = source / "room.ts"
    file.write_bytes(b"x")

    class DeletingClient(FakeRcClient):
        def job_status(self, job_id):
            file.unlink()
            return {"finished": True, "success": False, "error": "not deleting directories as there were IO errors"}

    service = RcloneRcUploadService(
        UploadConfig(enabled=True, app_retries=3, retry_sleep_seconds=1),
        daemon=FakeDaemon(),
        client=DeletingClient([]),
        sleeper=lambda _seconds: None,
    )

    result = service.run_once(source)

    assert result.phase == "success"
    assert result.exit_code == 0
    assert result.attempts == 1
    assert "空目录" in result.message


def test_rc_upload_service_accepts_object_not_found_when_remote_files_verify(tmp_path, monkeypatch):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    daemon = FakeDaemon()
    client = FakeRcClient([{"finished": True, "success": False, "error": "object not found"}])
    verified = []

    def fake_accept_failed_upload(config, source_path, failure_text, **_kwargs):
        verified.append((config, Path(source_path), failure_text))
        return True

    monkeypatch.setattr("src.uploader.rc_service.accept_failed_upload_if_remote_verified", fake_accept_failed_upload)
    service = RcloneRcUploadService(UploadConfig(enabled=True, app_retries=0), daemon=daemon, client=client)

    result = service.run_once(source)

    assert result.phase == "success"
    assert result.exit_code == 0
    assert result.message == "upload completed after remote verification"
    assert verified == [(service.config, source, "object not found")]


def test_rc_upload_service_retries_when_start_move_raises(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    sleeps = []

    class RaisingClient:
        def __init__(self):
            self.calls = 0

        def start_move(self, _config, _source_path):
            self.calls += 1
            raise RuntimeError("rc unavailable")

    client = RaisingClient()
    service = RcloneRcUploadService(
        UploadConfig(enabled=True, app_retries=2, retry_sleep_seconds=15),
        daemon=FakeDaemon(),
        client=client,
        sleeper=lambda seconds: sleeps.append(seconds),
    )

    result = service.run_once(source)

    assert result.phase == "failed"
    assert result.exit_code == 1
    assert result.stderr == "rc unavailable"
    assert result.attempts == 3
    assert client.calls == 3
    assert sleeps == [15, 15]


def test_rc_upload_service_does_not_retry_missing_rclone_binary(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    sleeps = []

    class MissingRcloneDaemon:
        def __init__(self):
            self.started = 0

        def start(self):
            self.started += 1
            raise RcloneRcError("找不到 rclone 可执行文件: rclone")

    daemon = MissingRcloneDaemon()
    service = RcloneRcUploadService(
        UploadConfig(enabled=True, app_retries=2, retry_sleep_seconds=15),
        daemon=daemon,
        client=FakeRcClient([]),
        sleeper=lambda seconds: sleeps.append(seconds),
    )

    result = service.run_once(source)

    assert result.phase == "failed"
    assert result.attempts == 1
    assert "找不到 rclone" in result.stderr
    assert daemon.started == 1
    assert sleeps == []
