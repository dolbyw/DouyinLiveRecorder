from datetime import UTC, datetime, timedelta

from src.dashboard_state import (
    AppDisplayPhase,
    AttentionDisposition,
    DashboardConfig,
    DashboardStateStore,
    RoomDisplayStatus,
)
from src.models import QualityLevel
from src.runtime import RoomSpec

ROOM_ID = "https://live.douyin.com/1"
STARTED_AT = datetime(2026, 6, 23, 8, 0, tzinfo=UTC)
NOW = STARTED_AT + timedelta(minutes=8, seconds=13)


def configured_store() -> DashboardStateStore:
    store = DashboardStateStore()
    store.reconcile_rooms((RoomSpec(ROOM_ID, QualityLevel.ORIGIN, "招财"),))
    return store


def test_reconcile_lists_every_enabled_room_in_config_order():
    store = DashboardStateStore()
    rooms = (
        RoomSpec("https://live.douyin.com/1", QualityLevel.ORIGIN, "招财"),
        RoomSpec("https://live.bilibili.com/2", QualityLevel.HD, "小鹿"),
    )

    store.reconcile_rooms(rooms)
    snapshot = store.snapshot(now=datetime(2026, 6, 23, tzinfo=UTC))

    assert [room.name for room in snapshot.rooms] == ["招财", "小鹿"]
    assert [room.platform for room in snapshot.rooms] == ["抖音", "B站"]
    assert [room.status for room in snapshot.rooms] == [RoomDisplayStatus.WAITING, RoomDisplayStatus.WAITING]


def test_reconcile_updates_room_and_removes_inactive_room():
    store = DashboardStateStore()
    first = RoomSpec(ROOM_ID, QualityLevel.ORIGIN, "旧名称")
    removed = RoomSpec("https://live.douyin.com/2", QualityLevel.HD, "移除")
    store.reconcile_rooms((first, removed))

    store.reconcile_rooms((RoomSpec(ROOM_ID, QualityLevel.HD, "新名称"),))

    snapshot = store.snapshot(now=NOW)
    assert [(room.name, room.quality) for room in snapshot.rooms] == [("新名称", "高清")]


def test_dashboard_config_contains_only_operational_fields():
    config = DashboardConfig(
        save_format="TS",
        quality="原画",
        split_seconds=1800,
        poll_seconds=300,
        max_requests=3,
        use_proxy=True,
        convert_to_mp4=True,
        save_path="D:/downloads",
        disk_free_gb=463.9,
    )

    representation = repr(config).lower()
    assert "cookie" not in representation
    assert "token" not in representation
    assert "password" not in representation


def test_room_lifecycle_uses_strongest_active_status():
    store = configured_store()
    store.mark_monitoring(ROOM_ID)
    store.mark_recording(ROOM_ID, "序号1 招财", "原画", STARTED_AT)
    store.mark_retrying(ROOM_ID, "temporary network error")
    store.mark_converting(ROOM_ID, "招财_000.ts", 47.4, 72, 152)

    room = store.snapshot(now=NOW).rooms[0]
    assert room.status is RoomDisplayStatus.CONVERTING
    assert room.progress_percent == 47.4
    assert room.elapsed_seconds == 72


def test_recording_finish_returns_room_to_monitoring():
    store = configured_store()
    store.mark_monitoring(ROOM_ID)
    store.mark_recording(ROOM_ID, "序号1 招财", "原画", STARTED_AT)

    store.mark_recording_finished(ROOM_ID)

    assert store.snapshot(now=NOW).rooms[0].status is RoomDisplayStatus.MONITORING


def test_duplicate_events_update_one_entry_without_discarding_recent_history():
    store = configured_store()
    store.add_event(ROOM_ID, "recording_started", "开始录制", at=STARTED_AT)
    store.add_event(ROOM_ID, "recording_started", "开始录制", at=NOW)
    store.add_event(ROOM_ID, "conversion_started", "开始转码", at=NOW + timedelta(seconds=1))
    store.add_event(ROOM_ID, "conversion_finished", "转码完成", at=NOW + timedelta(seconds=2))
    store.add_event(ROOM_ID, "recording_finished", "录制完成", at=NOW + timedelta(seconds=3))

    events = store.snapshot(now=NOW).events
    assert len(events) == 4
    assert [event.message for event in events] == ["录制完成", "转码完成", "开始转码", "开始录制"]


def test_duplicate_event_increments_occurrence_count():
    store = configured_store()
    store.add_event(ROOM_ID, "retry", "网络异常", at=STARTED_AT)
    store.add_event(ROOM_ID, "retry", " 网络异常 ", at=NOW)

    event = store.snapshot(now=NOW).events[0]
    assert event.occurrences == 2
    assert event.at == NOW


def test_snapshot_carries_start_time_and_monotonic_application_phase():
    store = DashboardStateStore(started_at=STARTED_AT)
    store.set_phase(AppDisplayPhase.STOPPING)
    store.set_phase(AppDisplayPhase.RUNNING)

    snapshot = store.snapshot(now=NOW)

    assert snapshot.started_at == STARTED_AT
    assert snapshot.phase is AppDisplayPhase.STOPPING


def test_monitoring_records_only_real_probe_time():
    store = configured_store()
    store.mark_monitoring(ROOM_ID, at=STARTED_AT, checked=True)
    store.mark_monitoring(ROOM_ID, at=NOW, checked=False)

    assert store.snapshot(now=NOW).rooms[0].last_checked_at == STARTED_AT


def test_recording_snapshot_carries_output_pattern():
    store = configured_store()
    store.mark_recording(
        ROOM_ID,
        "序号1 招财",
        "原画",
        STARTED_AT,
        output_path="D:/downloads/a_%03d.ts",
    )

    assert store.snapshot(now=NOW).rooms[0].output_path == "D:/downloads/a_%03d.ts"


def test_first_sweep_tracks_started_and_returned_probes_separately():
    store = configured_store()

    store.mark_initial_probe_started(ROOM_ID, at=STARTED_AT)
    probing = store.snapshot(now=STARTED_AT)
    store.mark_initial_probe_finished(ROOM_ID, at=NOW)
    completed = store.snapshot(now=NOW)

    assert probing.first_sweep_total == 1
    assert probing.first_sweep_started == 1
    assert probing.first_sweep_completed == 0
    assert probing.rooms[0].status is RoomDisplayStatus.PROBING
    assert completed.first_sweep_completed == 1
    assert completed.first_sweep_completed_at == NOW


def test_first_sweep_finish_is_idempotent_and_deleted_pending_room_updates_total():
    store = DashboardStateStore()
    first = RoomSpec(ROOM_ID, QualityLevel.ORIGIN, "招财")
    pending = RoomSpec("https://live.douyin.com/2", QualityLevel.ORIGIN, "待删除")
    store.reconcile_rooms((first, pending))
    store.mark_initial_probe_started(ROOM_ID, at=STARTED_AT)
    store.mark_initial_probe_finished(ROOM_ID, at=NOW)
    store.mark_initial_probe_finished(ROOM_ID, at=NOW)

    store.reconcile_rooms((first,))
    snapshot = store.snapshot(now=NOW)

    assert snapshot.first_sweep_total == 1
    assert snapshot.first_sweep_completed == 1
    assert snapshot.first_sweep_completed_at == NOW


def test_incident_stays_active_until_explicitly_cleared():
    store = configured_store()
    store.report_incident(
        ROOM_ID,
        "recording-connection",
        "录制连接中断",
        disposition=AttentionDisposition.AUTOMATIC,
        at=STARTED_AT,
        retry_attempt=2,
        retry_limit=5,
        next_retry_at=NOW,
    )

    incident = store.snapshot(now=NOW).incidents[0]
    assert incident.disposition is AttentionDisposition.AUTOMATIC
    assert incident.occurrences == 1
    assert incident.retry_attempt == 2

    cleared = store.clear_incident(ROOM_ID, "recording-connection", at=NOW)

    assert cleared is not None
    assert store.snapshot(now=NOW).incidents == ()


def test_repeated_incident_updates_one_entry_and_can_escalate():
    store = configured_store()
    store.report_incident(
        ROOM_ID,
        "recording-connection",
        "连接中断",
        disposition=AttentionDisposition.AUTOMATIC,
        at=STARTED_AT,
    )
    store.report_incident(
        ROOM_ID,
        "recording-connection",
        "重试耗尽",
        disposition=AttentionDisposition.ACTION_REQUIRED,
        at=NOW,
    )

    incident = store.snapshot(now=NOW).incidents[0]
    assert incident.disposition is AttentionDisposition.ACTION_REQUIRED
    assert incident.occurrences == 2
    assert incident.started_at == STARTED_AT
    assert incident.updated_at == NOW


def test_clear_room_incidents_only_removes_requested_incident_ids():
    store = configured_store()
    for incident_id in ("probe", "recording"):
        store.report_incident(
            ROOM_ID,
            incident_id,
            f"{incident_id} failed",
            disposition=AttentionDisposition.AUTOMATIC,
            at=STARTED_AT,
        )

    cleared = store.clear_room_incidents(ROOM_ID, incident_ids=("probe",), at=NOW)

    assert [incident.incident_id for incident in cleared] == ["probe"]
    assert [incident.incident_id for incident in store.snapshot(now=NOW).incidents] == ["recording"]


def test_correlated_recording_lifecycle_updates_one_semantic_event():
    store = configured_store()
    store.add_event(
        ROOM_ID,
        "recording_finished",
        "直播结束 · 等待转码",
        at=STARTED_AT,
        correlation_id="recording-42",
        details={"duration": "01:18:42", "size": "3.6 GB"},
    )
    store.add_event(
        ROOM_ID,
        "conversion_finished",
        "录制完成并转为 MP4",
        at=NOW,
        correlation_id="recording-42",
        details={"duration": "01:18:42", "size": "3.6 GB", "format": "MP4"},
    )

    events = store.snapshot(now=NOW).events
    assert len(events) == 1
    assert events[0].event_type == "conversion_finished"
    assert events[0].correlation_id == "recording-42"
    assert dict(events[0].details)["format"] == "MP4"


def test_clearing_incident_emits_exactly_one_recovery_event():
    store = configured_store()
    store.report_incident(
        ROOM_ID,
        "probe",
        "探测失败",
        disposition=AttentionDisposition.AUTOMATIC,
        at=STARTED_AT,
    )

    first = store.clear_incident(ROOM_ID, "probe", at=NOW, recovery_message="连接已恢复")
    second = store.clear_incident(ROOM_ID, "probe", at=NOW, recovery_message="连接已恢复")

    assert first is not None
    assert second is None
    assert [event.message for event in store.snapshot(now=NOW).events] == ["连接已恢复"]


def test_event_retention_keeps_fifty_most_recent_entries():
    store = configured_store()
    for index in range(55):
        store.add_event(ROOM_ID, f"event-{index}", f"事件 {index}", at=NOW + timedelta(seconds=index))

    events = store.snapshot(now=NOW).events
    assert len(events) == 50
    assert events[0].message == "事件 54"
    assert events[-1].message == "事件 5"
