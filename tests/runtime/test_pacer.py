import asyncio

import pytest

from src.runtime.pacer import (
    RequestPacer,
    calculate_first_sweep_spacing,
    calculate_legacy_first_start_spacing,
    calculate_start_spacing,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


@pytest.mark.asyncio
async def test_spacing_divides_window_by_room_count():
    pacer = RequestPacer(jitter=lambda _low, _high: 1.0)

    await pacer.configure(window_seconds=300, room_ids=tuple(str(index) for index in range(14)))

    assert pacer.spacing == pytest.approx(300 / 14)


@pytest.mark.asyncio
async def test_first_turn_is_immediate_and_following_turn_waits():
    clock = FakeClock()
    pacer = RequestPacer(clock=clock, sleep=clock.sleep, jitter=lambda _low, _high: 1.0)
    await pacer.configure(window_seconds=300, room_ids=("first", "second"))

    first = await pacer.wait_turn("first")
    second = await pacer.wait_turn("second")

    assert first == 0
    assert second == pytest.approx(15 / 2)
    assert clock.sleeps == [pytest.approx(15 / 2)]


@pytest.mark.asyncio
async def test_simultaneous_turns_are_serialized_without_duplicate_start_times():
    clock = FakeClock()
    pacer = RequestPacer(clock=clock, sleep=clock.sleep, jitter=lambda _low, _high: 1.0)
    room_ids = tuple(str(index) for index in range(14))
    await pacer.configure(window_seconds=300, room_ids=room_ids)

    starts = await asyncio.gather(*(pacer.wait_turn(room_id) for room_id in room_ids))

    assert starts == pytest.approx([index * (15 / 14) for index in range(14)])
    assert len(set(starts)) == 14


@pytest.mark.asyncio
async def test_jitter_changes_the_next_spacing():
    clock = FakeClock()
    pacer = RequestPacer(clock=clock, sleep=clock.sleep, jitter=lambda _low, _high: 0.9)
    await pacer.configure(window_seconds=100, room_ids=("first", "second"))

    await pacer.wait_turn("first")
    await pacer.wait_turn("second")

    assert clock.sleeps == [6.75]


def test_legacy_spacing_uses_larger_of_configured_and_automatic():
    assert calculate_start_spacing(300, 14, 0) == pytest.approx(300 / 14)
    assert calculate_start_spacing(300, 14, 30) == 30


@pytest.mark.parametrize(
    ("room_count", "expected"),
    [(5, 3.0), (15, 1.0), (30, 1.0), (100, 1.0)],
)
def test_first_sweep_spacing_targets_fifteen_seconds_with_safety_floor(room_count, expected):
    assert calculate_first_sweep_spacing(15, room_count, minimum_seconds=1) == expected


def test_legacy_first_start_spacing_is_adaptive_and_respects_user_delay():
    assert calculate_legacy_first_start_spacing(15, 0) == 1
    assert calculate_legacy_first_start_spacing(15, 5) == 5


@pytest.mark.asyncio
async def test_pacer_rejects_non_positive_window():
    pacer = RequestPacer()

    with pytest.raises(ValueError, match="window"):
        await pacer.configure(window_seconds=0, room_ids=("room",))


@pytest.mark.asyncio
async def test_first_sweep_transitions_to_steady_spacing_without_resetting_rooms():
    clock = FakeClock()
    pacer = RequestPacer(clock=clock, sleep=clock.sleep, jitter=lambda _low, _high: 1.0)
    room_ids = tuple(f"room-{index}" for index in range(1, 16))
    await pacer.configure(window_seconds=300, room_ids=room_ids)

    starts = [await pacer.wait_turn(room_id) for room_id in room_ids]
    await pacer.configure(window_seconds=300, room_ids=room_ids)
    repeat = await pacer.wait_turn(room_ids[0])

    assert starts == pytest.approx(list(range(15)))
    assert repeat == pytest.approx(34)
    assert pacer.first_sweep_progress.total == 15
    assert pacer.first_sweep_progress.issued == 15


@pytest.mark.asyncio
async def test_reconfiguration_gives_only_new_rooms_a_fast_first_permit():
    clock = FakeClock()
    pacer = RequestPacer(clock=clock, sleep=clock.sleep, jitter=lambda _low, _high: 1.0)
    await pacer.configure(window_seconds=300, room_ids=("a", "b"))
    await pacer.wait_turn("a")
    await pacer.wait_turn("b")

    await pacer.configure(window_seconds=300, room_ids=("b", "c"))
    await pacer.wait_turn("c")

    assert pacer.first_sweep_progress.total == 2
    assert pacer.first_sweep_progress.issued == 2
