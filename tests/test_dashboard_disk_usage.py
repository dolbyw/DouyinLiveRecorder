from pathlib import Path

from src.dashboard_disk_usage import RecordingDirectorySizeCache, scan_recording_directory_size


def test_recording_directory_size_cache_reuses_fresh_value(tmp_path, monkeypatch):
    calls = []

    def fake_scan(path: Path) -> int:
        calls.append(path)
        return 123

    cache = RecordingDirectorySizeCache(ttl_seconds=300, scanner=fake_scan)
    save_path = tmp_path / "downloads"

    assert cache.get(save_path, now=100.0) == 123
    assert cache.get(save_path, now=200.0) == 123
    assert calls == [save_path]


def test_recording_directory_size_cache_refreshes_after_ttl(tmp_path, monkeypatch):
    sizes = [123, 456]

    def fake_scan(_path: Path) -> int:
        return sizes.pop(0)

    cache = RecordingDirectorySizeCache(ttl_seconds=300, scanner=fake_scan)
    save_path = tmp_path / "downloads"

    assert cache.get(save_path, now=100.0) == 123
    assert cache.get(save_path, now=401.0) == 456


def test_recording_directory_size_cache_refreshes_when_path_changes(tmp_path, monkeypatch):
    calls = []

    def fake_scan(path: Path) -> int:
        calls.append(path)
        return len(calls)

    cache = RecordingDirectorySizeCache(ttl_seconds=300, scanner=fake_scan)

    assert cache.get(tmp_path / "one", now=100.0) == 1
    assert cache.get(tmp_path / "two", now=101.0) == 2


def test_scan_recording_directory_size_reads_file_metadata_only(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "a.ts").write_bytes(b"x" * 10)
    nested = downloads / "room"
    nested.mkdir()
    (nested / "b.mp4").write_bytes(b"x" * 15)

    assert scan_recording_directory_size(downloads) == 25
