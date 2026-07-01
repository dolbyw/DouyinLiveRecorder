from src.recorder.models import OutputPlan, SaveFormat
from src.recorder.segments import SegmentFinalizer


def test_segment_finalizer_submits_stable_closed_segments_once(tmp_path):
    first = tmp_path / "room_000.ts"
    second = tmp_path / "room_001.ts"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    plan = OutputPlan(tmp_path / "room_%03d.ts", tmp_path / "room_*.ts", SaveFormat.TS, True)
    submitted = []

    finalizer = SegmentFinalizer(plan, submit=submitted.append)

    finalizer.scan()
    finalizer.scan()
    finalizer.scan()

    assert submitted == [first]


def test_segment_finalizer_ignores_non_segment_and_temporary_files(tmp_path):
    ready = tmp_path / "room_000.ts"
    current = tmp_path / "room_001.ts"
    temporary = tmp_path / "room_002.converting.mp4"
    ready.write_bytes(b"ready")
    current.write_bytes(b"current")
    temporary.write_bytes(b"temp")
    plan = OutputPlan(tmp_path / "room_%03d.ts", tmp_path / "room_*.ts", SaveFormat.TS, True)
    submitted = []

    finalizer = SegmentFinalizer(plan, submit=submitted.append)

    finalizer.scan()
    finalizer.scan()

    assert submitted == [ready]


def test_segment_finalizer_does_nothing_for_non_segmented_plans(tmp_path):
    source = tmp_path / "room.ts"
    source.write_bytes(b"source")
    plan = OutputPlan(source, source, SaveFormat.TS, False)
    submitted = []

    SegmentFinalizer(plan, submit=submitted.append).scan()

    assert submitted == []
