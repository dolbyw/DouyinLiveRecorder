from src.models import QualityLevel
from src.runtime.config import parse_room_config_lines


def test_parse_room_config_lines_separates_active_commented_and_rejected():
    snapshot = parse_room_config_lines(
        [
            "高清, live.douyin.com/123?foo=1, 主播A\n",
            "#原画, https://live.bilibili.com/456, 主播B\n",
            "https://unsupported.example.com/live/1\n",
            "\n",
        ],
        QualityLevel.ORIGIN,
    )

    assert len(snapshot.desired_rooms) == 1
    assert snapshot.desired_rooms[0].url == "https://live.douyin.com/123"
    assert snapshot.desired_rooms[0].quality is QualityLevel.HD
    assert snapshot.desired_rooms[0].name == "主播A"
    assert snapshot.commented_room_ids == ("https://live.bilibili.com/456",)
    assert snapshot.rejected_lines == ("https://unsupported.example.com/live/1",)


def test_parse_room_config_lines_keeps_first_duplicate_in_input_order():
    snapshot = parse_room_config_lines(
        [
            "原画, https://live.douyin.com/1, first",
            "流畅, https://live.douyin.com/1, second",
            "标清, https://live.bilibili.com/2, third",
        ],
        QualityLevel.ORIGIN,
    )

    assert [room.url for room in snapshot.desired_rooms] == [
        "https://live.douyin.com/1",
        "https://live.bilibili.com/2",
    ]
    assert snapshot.desired_rooms[0].name == "first"
    assert snapshot.desired_rooms[0].quality is QualityLevel.ORIGIN
