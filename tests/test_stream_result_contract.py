import pytest

from src.stream import get_stream_url, get_yy_stream_url


@pytest.mark.asyncio
async def test_get_stream_url_returns_normalized_contract_fields():
    result = await get_stream_url(
        {
            "anchor_name": "主播A",
            "is_live": True,
            "title": "测试直播",
            "play_url_list": [
                {
                    "m3u8": "https://example.test/live.m3u8",
                    "flv": "https://example.test/live.flv",
                }
            ],
        },
        "OD",
        url_type="all",
        hls_extra_key="m3u8",
        flv_extra_key="flv",
    )

    assert result["anchor_name"] == "主播A"
    assert result["is_live"] is True
    assert result["quality"] == "OD"
    assert result["m3u8_url"] == "https://example.test/live.m3u8"
    assert result["flv_url"] == "https://example.test/live.flv"
    assert result["record_url"] == "https://example.test/live.m3u8"


@pytest.mark.asyncio
async def test_get_yy_stream_url_returns_legacy_dict_shape():
    result = await get_yy_stream_url(
        {
            "anchor_name": "主播B",
            "title": "YY 开播",
            "avp_info_res": {
                "stream_line_addr": {
                    "main": {
                        "cdn_info": {"url": "https://example.test/yy.flv"},
                    }
                }
            },
        }
    )

    assert result["anchor_name"] == "主播B"
    assert result["is_live"] is True
    assert result["quality"] == "OD"
    assert result["flv_url"] == "https://example.test/yy.flv"
    assert result["record_url"] == "https://example.test/yy.flv"
