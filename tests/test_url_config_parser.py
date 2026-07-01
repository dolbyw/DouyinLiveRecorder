from src.config_loader import normalize_url_config_entry, parse_url_config_entry
from src.models import QualityLevel


def test_parse_url_config_entry_supports_default_quality_for_plain_url():
    entry = parse_url_config_entry("https://live.example.com/room/1", default_quality="高清")

    assert entry is not None
    assert entry.quality is QualityLevel.HD
    assert entry.url == "https://live.example.com/room/1"
    assert entry.name == ""
    assert entry.is_comment is False


def test_parse_url_config_entry_supports_quality_url_name_and_comment():
    entry = parse_url_config_entry("#原画, https://live.example.com/room/2, 主播A", default_quality="流畅")

    assert entry is not None
    assert entry.quality is QualityLevel.ORIGIN
    assert entry.url == "https://live.example.com/room/2"
    assert entry.name == "主播A"
    assert entry.is_comment is True


def test_parse_url_config_entry_supports_url_then_name_shape():
    entry = parse_url_config_entry("https://live.example.com/room/3, 主播B", default_quality="标清")

    assert entry is not None
    assert entry.quality is QualityLevel.SD
    assert entry.url == "https://live.example.com/room/3"
    assert entry.name == "主播B"


def test_parse_url_config_entry_preserves_commas_inside_name():
    entry = parse_url_config_entry("原画, https://live.example.com/room/4, 主播C, 晚间场", default_quality="流畅")

    assert entry is not None
    assert entry.quality is QualityLevel.ORIGIN
    assert entry.url == "https://live.example.com/room/4"
    assert entry.name == "主播C, 晚间场"


def test_normalize_url_config_entry_adds_scheme_and_strips_query_for_known_hosts():
    parsed = parse_url_config_entry("原画, live.douyin.com/123456?foo=bar", default_quality="流畅")

    assert parsed is not None
    normalized = normalize_url_config_entry(parsed)

    assert normalized is not None
    assert normalized.url == "https://live.douyin.com/123456"


def test_normalize_url_config_entry_keeps_only_host_id_for_xiaohongshu():
    parsed = parse_url_config_entry(
        "https://www.xiaohongshu.com/live/abc?a=1&host_id=12345&b=2",
        default_quality="原画",
    )

    assert parsed is not None
    normalized = normalize_url_config_entry(parsed)

    assert normalized is not None
    assert normalized.url == "https://www.xiaohongshu.com/live/abc?host_id=12345"


def test_normalize_url_config_entry_rejects_unknown_hosts():
    parsed = parse_url_config_entry("https://unsupported.example.com/live/1", default_quality="原画")

    assert parsed is not None
    assert normalize_url_config_entry(parsed) is None
