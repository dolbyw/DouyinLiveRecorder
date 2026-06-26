from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StreamInfo:
    anchor_name: str = ""
    is_live: bool = False
    title: str | None = None
    quality: str | None = None
    m3u8_url: str | None = None
    flv_url: str | None = None
    record_url: str | None = None
    type: int | None = None
    new_cookies: str | None = None
    new_token: str | None = None
    uid: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_legacy_dict(cls, data: Mapping[str, Any] | None) -> StreamInfo:
        if not data:
            return cls()

        known_keys = {
            "anchor_name",
            "is_live",
            "title",
            "quality",
            "m3u8_url",
            "flv_url",
            "record_url",
            "type",
            "new_cookies",
            "new_token",
            "uid",
        }
        extras = {key: value for key, value in data.items() if key not in known_keys}
        return cls(
            anchor_name=str(data.get("anchor_name") or ""),
            is_live=bool(data.get("is_live", False)),
            title=data.get("title"),
            quality=data.get("quality"),
            m3u8_url=data.get("m3u8_url"),
            flv_url=data.get("flv_url"),
            record_url=data.get("record_url"),
            type=data.get("type"),
            new_cookies=data.get("new_cookies"),
            new_token=data.get("new_token"),
            uid=str(data["uid"]) if data.get("uid") is not None else None,
            extras=extras,
        )

    def to_legacy_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = dict(self.extras)
        data.update(
            {
                "anchor_name": self.anchor_name,
                "is_live": self.is_live,
            }
        )
        optional_values = {
            "title": self.title,
            "quality": self.quality,
            "m3u8_url": self.m3u8_url,
            "flv_url": self.flv_url,
            "record_url": self.record_url,
            "type": self.type,
            "new_cookies": self.new_cookies,
            "new_token": self.new_token,
            "uid": self.uid,
        }
        for key, value in optional_values.items():
            if value is not None:
                data[key] = value
        return data


def normalize_stream_info(data: Mapping[str, Any] | None) -> dict[str, Any]:
    return StreamInfo.from_legacy_dict(data).to_legacy_dict()


def make_stream_info(base: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    payload = dict(base or {})
    payload.update(kwargs)
    return normalize_stream_info(payload)


def normalize_platform_payload(
    data: Mapping[str, Any] | None,
    *,
    live_aliases: tuple[str, ...] = ("is_live", "live_status"),
    default_anchor_name: str = "",
) -> dict[str, Any]:
    payload = dict(data or {})
    if "anchor_name" not in payload:
        payload["anchor_name"] = default_anchor_name

    if "is_live" not in payload:
        for alias in live_aliases:
            if alias in payload:
                payload["is_live"] = bool(payload[alias])
                break
        else:
            payload["is_live"] = False

    return normalize_stream_info(payload)
