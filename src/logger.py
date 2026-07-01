
import os
import sys

from loguru import logger

logger.remove()

custom_format = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> - <level>{message}</level>"


def is_play_url_record(record) -> bool:
    level = record["level"]
    level_name = level.get("name") if isinstance(level, dict) else level.name
    return level_name == "INFO" and record["extra"].get("play_url") is True


def is_streamget_record(record) -> bool:
    return not record["extra"].get("play_url", False)

_console_sink_id = logger.add(
    sink=sys.stderr,
    format=custom_format,
    level="DEBUG",
    colorize=True,
    enqueue=True,
    diagnose=False,
)


def disable_console_logging() -> None:
    global _console_sink_id
    if _console_sink_id is not None:
        logger.remove(_console_sink_id)
        _console_sink_id = None

script_path = os.path.split(os.path.realpath(sys.argv[0]))[0]

logger.add(
    f"{script_path}/logs/streamget.log",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    filter=is_streamget_record,
    serialize=False,
    enqueue=True,
    retention=3,
    rotation="5 MB",
    encoding='utf-8',
    diagnose=False,
)

logger.add(
    f"{script_path}/logs/PlayURL.log",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
    filter=is_play_url_record,
    serialize=False,
    enqueue=True,
    retention=1,
    rotation="300 KB",
    encoding='utf-8',
    diagnose=False,
)
