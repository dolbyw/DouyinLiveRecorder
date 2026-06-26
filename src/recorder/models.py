from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class SaveFormat(StrEnum):
    TS = "TS"
    FLV = "FLV"
    MKV = "MKV"
    MP4 = "MP4"
    MP3 = "MP3"
    M4A = "M4A"

    @classmethod
    def parse(cls, value: str | SaveFormat) -> SaveFormat:
        if isinstance(value, cls):
            return value
        try:
            return cls(value.upper())
        except (AttributeError, ValueError) as error:
            raise ValueError(f"unsupported save format: {value}") from error


class EndReason(StrEnum):
    COMPLETED = "completed"
    COMMENT_STOPPED = "comment_stopped"
    EXIT_STOPPED = "exit_stopped"
    FAILED_TO_START = "failed_to_start"
    FAILED = "failed"

    @property
    def is_success(self) -> bool:
        return self in {self.COMPLETED, self.COMMENT_STOPPED, self.EXIT_STOPPED}


@dataclass(frozen=True, slots=True)
class RecordRequest:
    anchor_name: str
    platform: str
    room_url: str
    source_url: str
    title: str | None = None
    output_root: Path = Path("downloads")
    save_format: SaveFormat = SaveFormat.TS
    folder_by_author: bool = True
    folder_by_date: bool = True
    folder_by_title: bool = False
    filename_by_title: bool = False
    clean_emojis: bool = False
    split: bool = False
    segment_seconds: int = 1800
    proxy: str | None = None
    headers: str | None = None
    overseas: bool = False
    audio_only: bool = False
    direct_flv: bool = False
    convert_to_mp4: bool = False
    convert_to_h264: bool = False
    custom_script: str | None = None

    def __post_init__(self) -> None:
        for name in ("anchor_name", "platform", "room_url", "source_url"):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")
        object.__setattr__(self, "output_root", Path(self.output_root))
        object.__setattr__(self, "save_format", SaveFormat.parse(self.save_format))
        if self.split and self.segment_seconds <= 0:
            raise ValueError("segment_seconds must be positive when splitting")

    @property
    def effective_format(self) -> SaveFormat:
        if self.direct_flv:
            return SaveFormat.FLV
        if self.audio_only and self.save_format not in {SaveFormat.MP3, SaveFormat.M4A}:
            return SaveFormat.MP3
        return self.save_format


@dataclass(frozen=True, slots=True)
class OutputPlan:
    output_path: Path
    file_glob: Path
    save_format: SaveFormat
    segmented: bool


@dataclass(frozen=True, slots=True)
class ProcessResult:
    reason: EndReason
    return_code: int | None = None
    error: BaseException | None = None
    output_tail: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PostprocessResult:
    processed_files: tuple[Path, ...] = ()
    errors: tuple[BaseException, ...] = ()


@dataclass(frozen=True, slots=True)
class PipelineResult:
    output: OutputPlan
    process: ProcessResult
    postprocess: PostprocessResult = field(default_factory=PostprocessResult)
