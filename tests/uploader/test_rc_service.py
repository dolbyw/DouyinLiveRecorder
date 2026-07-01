from pathlib import Path

from src.models import UploadConfig
from src.uploader.rc_service import RcloneRcTransferProgress, RcloneRcUploadProgress, RcloneRcUploadService
from src.uploader.rclone_rc import UPLOAD_JOB_GROUP, RcloneRcError


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
    def __init__(self, statuses, stats=None):
        self.statuses = list(statuses)
        self.stats = list(stats or [])
        self.started = []
        self.stats_groups = []
        self.job_ids = []
        self.delete_on_success_path = None

    def start_move(self, config, source_path, *, group=UPLOAD_JOB_GROUP):
        self.started.append((config, Path(source_path), group))
        return 7

    def job_status(self, job_id):
        self.job_ids.append(job_id)
        status = self.statuses.pop(0)
        if status.get("finished") and status.get("success") and self.delete_on_success_path is not None:
            self.delete_on_success_path.unlink(missing_ok=True)
        return status

    def core_stats(self, group=UPLOAD_JOB_GROUP):
        self.stats_groups.append(group)
        return self.stats.pop(0)


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
    assert client.started[0][:2] == (service.config, source)
    assert client.job_ids == [7, 7]
    assert sleeps == [2]
    assert service.status.phase == "success"


def test_rc_upload_service_uses_isolated_stats_group_per_upload_run(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    client = FakeRcClient(
        [
            {"finished": False, "success": False, "progress": {"percentage": 50}},
            {"finished": True, "success": True, "output": {"transferred": "1 file"}},
        ],
        stats=[{"bytes": 1, "totalBytes": 2, "transfers": 0}],
    )
    service = RcloneRcUploadService(
        UploadConfig(enabled=True),
        daemon=FakeDaemon(),
        client=client,
        sleeper=lambda _seconds: None,
    )

    service.run_once(source)

    upload_group = client.started[0][2]
    assert upload_group.startswith(f"{UPLOAD_JOB_GROUP}-")
    assert client.stats_groups == [upload_group]


def test_rc_upload_service_stops_running_job_when_shutdown_is_requested(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"x")
    daemon = FakeDaemon()
    client = FakeRcClient([{"finished": False, "success": False, "progress": {"percentage": 12.5}}])
    stop_requested = False

    def request_stop(_seconds):
        nonlocal stop_requested
        stop_requested = True

    service = RcloneRcUploadService(
        UploadConfig(enabled=True),
        daemon=daemon,
        client=client,
        sleeper=request_stop,
        stop_requested=lambda: stop_requested,
    )

    result = service.run_once(source)

    assert result.phase == "skipped"
    assert result.message == "upload stopped; local files preserved"
    assert daemon.stopped == 1
    assert (source / "room.ts").exists()


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
            files_total=1,
        )
    ]
    assert service.status.message == "upload completed"


def test_rc_upload_service_reports_group_stats_active_transfers_and_waiting_count(tmp_path):
    source = tmp_path / "downloads"
    (source / "Alice").mkdir(parents=True)
    (source / "Bob").mkdir()
    (source / "Carol").mkdir()
    (source / "Alice" / "Alice_20260701.mp4").write_bytes(b"x" * 1_000_000)
    (source / "Bob" / "Bob_20260701.mp4").write_bytes(b"x" * 2_000_000)
    (source / "Carol" / "Carol_20260701.mp4").write_bytes(b"x" * 3_000_000)
    progress_events = []
    client = FakeRcClient(
        [
            {"finished": False, "success": False, "progress": {"percentage": 33.3}},
            {"finished": True, "success": True, "output": {"transferred": "3 files"}},
        ],
        stats=[
            {
                "bytes": 1_500_000,
                "totalBytes": 6_000_000,
                "speed": 800_000,
                "transfers": 1,
                "transferring": [
                    {
                        "name": "Alice/Alice_20260701.mp4",
                        "bytes": 500_000,
                        "size": 1_000_000,
                        "percentage": 50,
                        "speed": 300_000,
                    },
                    {
                        "name": "Bob/Bob_20260701.mp4",
                        "bytes": 1_000_000,
                        "size": 2_000_000,
                        "percentage": 50,
                        "speed": 500_000,
                    },
                ],
            }
        ],
    )
    client.delete_on_success_path = source / "Alice" / "Alice_20260701.mp4"
    service = RcloneRcUploadService(
        UploadConfig(enabled=True),
        daemon=FakeDaemon(),
        client=client,
        sleeper=lambda _seconds: None,
        progress_callback=progress_events.append,
    )

    service.run_once(source)

    assert progress_events == [
        RcloneRcUploadProgress(
            percent=25.0,
            speed_bytes_per_second=800_000,
            bytes_transferred=1_500_000,
            total_bytes=6_000_000,
            current_file="Alice/Alice_20260701.mp4",
            files_total=3,
            files_done=1,
            files_waiting=0,
            active_transfers=(
                RcloneRcTransferProgress(
                    name="Alice/Alice_20260701.mp4",
                    percent=50.0,
                    speed_bytes_per_second=300_000,
                    bytes_transferred=500_000,
                    total_bytes=1_000_000,
                ),
                RcloneRcTransferProgress(
                    name="Bob/Bob_20260701.mp4",
                    percent=50.0,
                    speed_bytes_per_second=500_000,
                    bytes_transferred=1_000_000,
                    total_bytes=2_000_000,
                ),
            ),
        )
    ]


def test_rc_upload_progress_clamps_cumulative_transfer_count_to_current_run(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    for index in range(3):
        (source / f"room-{index}.mp4").write_bytes(b"x" * 1_000_000)
    progress_events = []
    client = FakeRcClient(
        [
            {"finished": False, "success": False, "progress": {"percentage": 97.8}},
            {"finished": True, "success": True, "output": {"transferred": "3 files"}},
        ],
        stats=[
            {
                "bytes": 2_900_000,
                "totalBytes": 3_000_000,
                "speed": 800_000,
                "transfers": 28,
                "transferring": [
                    {
                        "name": "room-2.mp4",
                        "bytes": 900_000,
                        "size": 1_000_000,
                        "percentage": 90,
                        "speed": 300_000,
                    },
                ],
            }
        ],
    )
    service = RcloneRcUploadService(
        UploadConfig(enabled=True),
        daemon=FakeDaemon(),
        client=client,
        sleeper=lambda _seconds: None,
        progress_callback=progress_events.append,
    )

    service.run_once(source)

    assert progress_events[0].files_total == 3
    assert progress_events[0].files_done == 3
    assert progress_events[0].files_waiting == 0


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


def test_rc_upload_service_ignores_excluded_files_when_deciding_success(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    uploaded = source / "room.mp4"
    protected = source / "room.ts"
    uploaded.write_bytes(b"x")
    protected.write_bytes(b"raw")
    client = FakeRcClient([{"finished": True, "success": True, "output": {"transferred": "1 file"}}])
    client.delete_on_success_path = uploaded
    service = RcloneRcUploadService(
        UploadConfig(enabled=True, exclude_patterns=("*.ts",)),
        daemon=FakeDaemon(),
        client=client,
    )

    result = service.run_once(source)

    assert result.phase == "success"
    assert protected.exists()


def test_rc_upload_service_skips_when_only_excluded_files_exist(tmp_path):
    source = tmp_path / "downloads"
    source.mkdir()
    (source / "room.ts").write_bytes(b"raw")
    client = FakeRcClient([])
    service = RcloneRcUploadService(
        UploadConfig(enabled=True, app_retries=0, exclude_patterns=("*.ts",)),
        daemon=FakeDaemon(),
        client=client,
        sleeper=lambda _seconds: None,
    )

    result = service.run_once(source)

    assert result.phase == "skipped"
    assert client.started == []


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

        def start_move(self, _config, _source_path, *, group=UPLOAD_JOB_GROUP):
            del group
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
