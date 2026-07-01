import httpx
import pytest

from src.models import UploadConfig
from src.uploader.rclone_rc import (
    RcloneRcClient,
    RcloneRcDaemon,
    RcloneRcError,
    build_rcd_command,
    build_sync_move_payload,
)


def test_build_rcd_command_uses_local_rc_server_defaults():
    config = UploadConfig(enabled=True)

    command = build_rcd_command(config)

    assert command == [
        "rclone",
        "rcd",
        "--rc-addr",
        "127.0.0.1:5572",
        "--rc-no-auth",
        "--transfers",
        "2",
        "--checkers",
        "2",
        "--retries",
        "3",
    ]


def test_build_rcd_command_honors_custom_binary_and_port():
    config = UploadConfig(
        enabled=True,
        rclone_path="C:\\Tools\\rclone\\rclone.exe",
        rc_port=5573,
        transfers=1,
        checkers=1,
        rclone_retries=4,
    )

    command = build_rcd_command(config)

    assert command == [
        "C:\\Tools\\rclone\\rclone.exe",
        "rcd",
        "--rc-addr",
        "127.0.0.1:5573",
        "--rc-no-auth",
        "--transfers",
        "1",
        "--checkers",
        "1",
        "--retries",
        "4",
    ]


def test_build_rcd_command_resolves_relative_binary_from_app_root(tmp_path):
    app_root = tmp_path / "app"
    config = UploadConfig(enabled=True, rclone_path="rclone\\rclone.exe")

    command = build_rcd_command(config, app_root=app_root)

    assert command[0] == str(app_root / "rclone" / "rclone.exe")


def test_build_rcd_command_preserves_absolute_binary(tmp_path):
    config = UploadConfig(enabled=True, rclone_path="C:\\Tools\\rclone\\rclone.exe")

    command = build_rcd_command(config, app_root=tmp_path / "app")

    assert command[0] == "C:\\Tools\\rclone\\rclone.exe"


def test_build_sync_move_payload_maps_upload_config_to_rc_parameters(tmp_path):
    source = tmp_path / "downloads"
    config = UploadConfig(
        enabled=True,
        remote_path="123pan:/LiveBackup/",
        min_age="2h",
        transfers=2,
        checkers=2,
        rclone_retries=3,
        delete_empty_dirs=True,
        dry_run=True,
    )

    payload = build_sync_move_payload(config, source)

    assert payload == {
        "srcFs": str(source),
        "dstFs": "123pan:/LiveBackup/",
        "deleteEmptySrcDirs": True,
        "_async": True,
        "_group": "douyin-live-recorder-upload",
        "_config": {
            "Transfers": 2,
            "Checkers": 2,
            "Retries": 3,
            "DryRun": True,
        },
        "_filter": {
            "MinAge": "2h",
        },
    }


def test_build_sync_move_payload_excludes_protected_recording_patterns(tmp_path):
    source = tmp_path / "downloads"
    config = UploadConfig(enabled=True, exclude_patterns=("*.converting.mp4", "*.ts"))

    payload = build_sync_move_payload(config, source)

    assert payload["_filter"]["ExcludeRule"] == ["*.converting.mp4", "*.ts"]


def test_rc_client_posts_json_to_endpoint_and_returns_response():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"jobid": 7})

    client = RcloneRcClient(base_url="http://127.0.0.1:5572", transport=httpx.MockTransport(handler))

    response = client.post("sync/move", {"srcFs": "downloads", "dstFs": "123pan:/LiveBackup/"})

    assert response == {"jobid": 7}
    assert requests[0].url == "http://127.0.0.1:5572/sync/move"
    assert requests[0].headers["content-type"] == "application/json"


def test_rc_client_raises_error_with_rc_error_body():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "webdav timeout", "path": "sync/move"})

    client = RcloneRcClient(base_url="http://127.0.0.1:5572", transport=httpx.MockTransport(handler))

    with pytest.raises(RcloneRcError, match="webdav timeout"):
        client.post("sync/move", {"srcFs": "downloads"})


def test_rc_client_job_status_posts_job_id():
    seen_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(request.read())
        return httpx.Response(200, json={"finished": True, "success": True})

    client = RcloneRcClient(base_url="http://127.0.0.1:5572", transport=httpx.MockTransport(handler))

    response = client.job_status(7)

    assert response == {"finished": True, "success": True}
    assert b'"jobid":7' in seen_payloads[0]


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.waited = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True

    def kill(self):
        self.killed = True


class FlakyNoopClient:
    def __init__(self, failures_before_ready):
        self.failures_before_ready = failures_before_ready
        self.noop_calls = 0

    def noop(self):
        self.noop_calls += 1
        if self.noop_calls <= self.failures_before_ready:
            raise RcloneRcError("not ready")
        return {"status": "ok"}


def test_daemon_reuses_existing_rc_server_without_starting_process():
    client = FlakyNoopClient(failures_before_ready=0)
    popen_calls = []
    daemon = RcloneRcDaemon(
        UploadConfig(enabled=True),
        client=client,
        popen=lambda command: popen_calls.append(command),
    )

    assert daemon.start() is False
    assert popen_calls == []
    assert client.noop_calls == 1


def test_daemon_starts_rcd_and_waits_until_noop_succeeds():
    client = FlakyNoopClient(failures_before_ready=2)
    processes = []

    def popen(command):
        processes.append((command, FakeProcess()))
        return processes[-1][1]

    daemon = RcloneRcDaemon(
        UploadConfig(enabled=True, rc_port=5573),
        client=client,
        popen=popen,
        sleeper=lambda _seconds: None,
        startup_attempts=3,
    )

    assert daemon.start() is True
    assert processes[0][0] == build_rcd_command(UploadConfig(enabled=True, rc_port=5573))
    assert client.noop_calls == 3


def test_daemon_reports_missing_rclone_binary_clearly():
    daemon = RcloneRcDaemon(
        UploadConfig(enabled=True),
        client=FlakyNoopClient(failures_before_ready=1),
        popen=lambda _command: (_ for _ in ()).throw(FileNotFoundError("rclone")),
    )

    with pytest.raises(RcloneRcError, match="找不到 rclone"):
        daemon.start()


def test_daemon_raises_when_started_process_never_becomes_ready():
    client = FlakyNoopClient(failures_before_ready=99)
    process = FakeProcess()
    daemon = RcloneRcDaemon(
        UploadConfig(enabled=True),
        client=client,
        popen=lambda _command: process,
        sleeper=lambda _seconds: None,
        startup_attempts=2,
    )

    with pytest.raises(RcloneRcError, match="not ready"):
        daemon.start()
    assert process.terminated is True


def test_daemon_stop_terminates_only_owned_process():
    client = FlakyNoopClient(failures_before_ready=1)
    process = FakeProcess()
    daemon = RcloneRcDaemon(
        UploadConfig(enabled=True),
        client=client,
        popen=lambda _command: process,
        sleeper=lambda _seconds: None,
        startup_attempts=2,
    )

    daemon.start()
    daemon.stop()

    assert process.terminated is True
    assert process.waited is True
