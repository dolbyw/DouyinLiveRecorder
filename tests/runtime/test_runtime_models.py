from dataclasses import FrozenInstanceError

import pytest

from src.models import QualityLevel
from src.runtime.models import RoomSpec, RoomStatus


def test_room_spec_requires_an_absolute_http_url():
    with pytest.raises(ValueError, match="absolute HTTP URL"):
        RoomSpec(url="live.douyin.com/1", quality=QualityLevel.ORIGIN)


def test_room_spec_is_immutable_and_uses_url_identity():
    room = RoomSpec(url="https://live.douyin.com/1", quality=QualityLevel.HD, name="主播")

    with pytest.raises(FrozenInstanceError):
        room.name = "changed"

    assert room.room_id == "https://live.douyin.com/1"


def test_room_status_starts_idle():
    status = RoomStatus(room_id="https://live.douyin.com/1")

    assert status.monitoring is False
    assert status.recording_name is None
    assert status.consecutive_errors == 0
