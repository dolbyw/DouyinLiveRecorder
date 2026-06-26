from src.models import StreamInfo, normalize_stream_info


def test_stream_info_preserves_known_and_extra_fields():
    legacy = {
        "anchor_name": "主播A",
        "is_live": True,
        "title": "今晚开播",
        "quality": "原画",
        "m3u8_url": "https://example.test/live.m3u8",
        "record_url": "https://example.test/live.m3u8",
        "new_token": "token-1",
        "uid": 12345,
        "unexpected": "keep-me",
    }

    info = StreamInfo.from_legacy_dict(legacy)
    restored = info.to_legacy_dict()

    assert info.anchor_name == "主播A"
    assert info.is_live is True
    assert info.uid == "12345"
    assert restored["unexpected"] == "keep-me"
    assert restored["new_token"] == "token-1"
    assert restored["record_url"] == "https://example.test/live.m3u8"


def test_normalize_stream_info_fills_required_defaults():
    normalized = normalize_stream_info({"record_url": "https://example.test/live.flv"})

    assert normalized["anchor_name"] == ""
    assert normalized["is_live"] is False
    assert normalized["record_url"] == "https://example.test/live.flv"
