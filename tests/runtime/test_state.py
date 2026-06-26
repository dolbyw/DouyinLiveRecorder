from datetime import UTC, datetime

import pytest

from src.models import QualityLevel
from src.runtime import RoomSpec, StateStore


def room(url: str, quality: QualityLevel = QualityLevel.ORIGIN, name: str = "") -> RoomSpec:
    return RoomSpec(url=url, quality=quality, name=name)


def test_replace_desired_rooms_reports_added_removed_and_updated():
    store = StateStore()
    first = room("https://live.douyin.com/1")
    removed = room("https://live.douyin.com/2")
    store.replace_desired_rooms([first, removed])

    updated = room(first.url, QualityLevel.HD, "new name")
    added = room("https://live.douyin.com/3")
    changes = store.replace_desired_rooms([updated, added])

    assert changes.added == (added,)
    assert changes.removed == (removed,)
    assert changes.updated == ((first, updated),)


def test_replace_desired_rooms_rejects_duplicate_urls():
    store = StateStore()
    duplicate = room("https://live.douyin.com/1")

    with pytest.raises(ValueError, match="duplicate room"):
        store.replace_desired_rooms([duplicate, duplicate])


def test_recording_lifecycle_updates_observed_state():
    store = StateStore()
    spec = room("https://live.douyin.com/1", QualityLevel.HD)
    store.replace_desired_rooms([spec])
    started_at = datetime(2026, 6, 20, tzinfo=UTC)

    store.mark_monitoring(spec.room_id)
    store.mark_recording_started(spec.room_id, "序号1 主播", QualityLevel.HD, started_at)
    recording = store.snapshot().status_for(spec.room_id)

    assert recording.monitoring is True
    assert recording.recording_name == "序号1 主播"
    assert recording.recording_started_at == started_at

    store.mark_recording_finished(spec.room_id)
    assert store.snapshot().status_for(spec.room_id).recording_name is None


def test_success_clears_consecutive_room_errors():
    store = StateStore()
    spec = room("https://live.douyin.com/1")
    store.replace_desired_rooms([spec])

    store.mark_room_error(spec.room_id, "network")
    store.mark_room_error(spec.room_id, "network again")

    assert store.snapshot().status_for(spec.room_id).consecutive_errors == 2

    store.mark_room_success(spec.room_id)

    assert store.snapshot().status_for(spec.room_id).consecutive_errors == 0


def test_room_and_application_stop_are_idempotent():
    store = StateStore()
    spec = room("https://live.douyin.com/1")
    store.replace_desired_rooms([spec])

    store.request_room_stop(spec.room_id)
    store.request_room_stop(spec.room_id)
    store.request_shutdown()
    store.request_shutdown()

    snapshot = store.snapshot()
    assert snapshot.shutdown_requested is True
    assert snapshot.status_for(spec.room_id).stop_requested is True


def test_snapshot_is_detached_from_later_store_changes():
    store = StateStore()
    first = room("https://live.douyin.com/1")
    store.replace_desired_rooms([first])
    before = store.snapshot()

    store.replace_desired_rooms([first, room("https://live.douyin.com/2")])

    assert before.desired_rooms == (first,)
