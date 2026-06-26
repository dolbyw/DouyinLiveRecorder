from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.config_loader import normalize_url_config_entry, parse_url_config_entry
from src.models import QualityLevel

from .models import RoomSpec


@dataclass(frozen=True, slots=True)
class RoomConfigSnapshot:
    desired_rooms: tuple[RoomSpec, ...] = ()
    commented_room_ids: tuple[str, ...] = ()
    rejected_lines: tuple[str, ...] = ()


def parse_room_config_lines(
    lines: Iterable[str],
    default_quality: QualityLevel,
) -> RoomConfigSnapshot:
    desired: list[RoomSpec] = []
    commented: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        parsed = parse_url_config_entry(line, default_quality=default_quality.value)
        normalized = normalize_url_config_entry(parsed) if parsed is not None else None
        if normalized is None:
            rejected.append(line)
            continue
        if normalized.url in seen:
            continue
        seen.add(normalized.url)
        if normalized.is_comment:
            commented.append(normalized.url)
        else:
            desired.append(
                RoomSpec(
                    url=normalized.url,
                    quality=normalized.quality,
                    name=normalized.name,
                )
            )

    return RoomConfigSnapshot(
        desired_rooms=tuple(desired),
        commented_room_ids=tuple(commented),
        rejected_lines=tuple(rejected),
    )
