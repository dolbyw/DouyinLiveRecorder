from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = ("authorization", "cookie", "pass", "password", "secret", "sign", "token", "auth", "key")
_SENSITIVE_LINE_PATTERN = re.compile(r"(?im)^(\s*(?:cookie|authorization)\s*:\s*)(.+)$")
_SENSITIVE_PAIR_PATTERN = re.compile(
    r"(?i)(^|[\s;])(password|token|secret|authorization|cookie|auth|sign|key)=([^\s&;]+)"
)
_URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_SENSITIVE_COMMAND_KEYS = {"pass", "password", "--password", "--pass", "--token", "--auth", "--key", "--secret"}


def sanitize_for_log(value: object) -> str:
    text = str(value)
    text = _URL_PATTERN.sub(lambda match: _sanitize_url(match.group(0)), text)
    text = _SENSITIVE_LINE_PATTERN.sub(lambda match: f"{match.group(1)}{_REDACTED}", text)
    return _SENSITIVE_PAIR_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}={_REDACTED}", text)


def sanitize_command(command: Iterable[object]) -> tuple[str, ...]:
    sanitized: list[str] = []
    redact_next = False
    for part in command:
        text = str(part)
        lowered = text.lower()
        if redact_next:
            sanitized.append(_REDACTED)
            redact_next = False
            continue
        if lowered in _SENSITIVE_COMMAND_KEYS:
            sanitized.append(text)
            redact_next = True
            continue
        if any(lowered.startswith(f"{key}=") for key in _SENSITIVE_COMMAND_KEYS):
            key, _, _value = text.partition("=")
            sanitized.append(f"{key}={_REDACTED}")
            continue
        sanitized.append(sanitize_for_log(text))
    return tuple(sanitized)


def format_log_context(**context: object) -> str:
    parts = []
    for key in sorted(context):
        value = context[key]
        if value is None:
            continue
        parts.append(f"{key}={sanitize_for_log(value)}")
    return " ".join(parts)


def _sanitize_url(url: str) -> str:
    split = urlsplit(url)
    if not split.query:
        return url
    query = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        if _is_sensitive_key(key):
            query.append((key, _REDACTED))
        else:
            query.append((key, value))
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEYS)
