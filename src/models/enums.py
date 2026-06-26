from __future__ import annotations

from enum import Enum


class QualityLevel(str, Enum):
    ORIGIN = "原画"
    BLUE = "蓝光"
    UHD = "超清"
    HD = "高清"
    SD = "标清"
    LD = "流畅"

    @classmethod
    def from_raw(cls, value: str | None, default: QualityLevel | None = None) -> QualityLevel:
        normalized = (value or "").strip()
        if not normalized:
            return default or cls.ORIGIN

        aliases = {
            "原画": cls.ORIGIN,
            "OD": cls.ORIGIN,
            "蓝光": cls.BLUE,
            "BD": cls.BLUE,
            "超清": cls.UHD,
            "UHD": cls.UHD,
            "高清": cls.HD,
            "HD": cls.HD,
            "标清": cls.SD,
            "SD": cls.SD,
            "流畅": cls.LD,
            "LD": cls.LD,
        }
        return aliases.get(normalized.upper(), aliases.get(normalized, default or cls.ORIGIN))


class SaveType(str, Enum):
    TS = "TS"
    MKV = "MKV"
    FLV = "FLV"
    MP4 = "MP4"
    MP3 = "MP3"
    M4A = "M4A"

    @classmethod
    def from_raw(cls, value: str | None, default: SaveType | None = None) -> SaveType:
        normalized = (value or "").strip().upper()
        aliases = {
            "TS": cls.TS,
            "MKV": cls.MKV,
            "FLV": cls.FLV,
            "MP4": cls.MP4,
            "MP3": cls.MP3,
            "MP3音频": cls.MP3,
            "M4A": cls.M4A,
            "M4A音频": cls.M4A,
        }
        return aliases.get(normalized, default or cls.TS)


class ProxyMode(str, Enum):
    DISABLED = "disabled"
    GLOBAL = "global"
