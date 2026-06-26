
import os
import sys

from loguru import logger

logger.remove()

custom_format = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> - <level>{message}</level>"

_console_sink_id = logger.add(
    sink=sys.stderr,
    format=custom_format,
    level="DEBUG",
    colorize=True,
    enqueue=True
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
    filter=lambda i: i["level"].name != "INFO",
    serialize=False,
    enqueue=True,
    retention=1,
    rotation="300 KB",
    encoding='utf-8'
)

logger.add(
    f"{script_path}/logs/PlayURL.log",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
    filter=lambda i: i["level"].name == "INFO",
    serialize=False,
    enqueue=True,
    retention=1,
    rotation="300 KB",
    encoding='utf-8'
)
