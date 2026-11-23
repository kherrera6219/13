"""Structured JSON logging with mandatory content and secret redaction.

Implements NFR-PRIV-01, NFR-OBS-01, AGENTS.md rule 8, and DLE-STD-001 §5.
Prompt text, response text, passages, headers, and API keys are never emitted
in log events; only IDs, lengths, timings, and SHA-256 digests are logged.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
import threading
from collections.abc import Mapping
from typing import TextIO, cast

import structlog
from structlog.typing import EventDict, FilteringBoundLogger, WrappedLogger

REDACTED = "[REDACTED]"

BANNED_LOG_KEYS: frozenset[str] = frozenset(
    {
        "text",
        "prompt",
        "prompts",
        "passage",
        "passages",
        "response",
        "response_text",
        "contents",
        "content",
        "body",
        "payload",
        "headers",
        "header",
        "api_key",
        "apikey",
        "key",
        "secret",
        "token",
        "password",
        "authorization",
        "cookie",
        "x_goog_api_key",
        "x_dle_admin_key",
        "system_instruction",
        "systeminstruction",
        "query",
        "question",
        "answer",
        "draft",
        "raw_text",
        "raw_body",
        "message_text",
    }
)

_SAFE_KEY_WHITELIST: frozenset[str] = frozenset(
    {
        "key_id",
        "content_sha256",
        "response_sha256",
        "prompt_sha256",
        "passage_sha256",
        "body_sha256",
        "prompt_tokens",
        "input_tokens",
        "output_tokens",
        "thought_tokens",
        "total_tokens",
        "cached_tokens",
    }
)

_BANNED_SUFFIXES: tuple[str, ...] = (
    "_text",
    "_prompt",
    "_passage",
    "_secret",
    "_token",
    "_key",
    "_password",
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"(?i)(?:api[_-]?key|x-goog-api-key|x-dle-admin-key|key)=[^&\s]+"),
)

_SECRETS_LOCK = threading.Lock()
_REGISTERED_SECRETS: set[str] = set()


def register_secret(secret: str) -> None:
    """Register a runtime secret or canary string so loggers always scrub it."""
    if secret:
        with _SECRETS_LOCK:
            _REGISTERED_SECRETS.add(secret)


def clear_registered_secrets() -> None:
    """Clear registered runtime secrets (primarily for test isolation)."""
    with _SECRETS_LOCK:
        _REGISTERED_SECRETS.clear()


def _is_banned_key(raw_key: str) -> bool:
    norm = raw_key.strip().lower().replace("-", "_")
    if norm in _SAFE_KEY_WHITELIST:
        return False
    if norm in BANNED_LOG_KEYS:
        return True
    return norm.endswith(_BANNED_SUFFIXES)


def _scrub_string(value: str, secrets_snapshot: tuple[str, ...]) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(REDACTED, result)
    for secret in secrets_snapshot:
        if secret in result:
            result = result.replace(secret, REDACTED)
    return result


def _redact_value(value: object, secrets_snapshot: tuple[str, ...]) -> object:
    if isinstance(value, str):
        return _scrub_string(value, secrets_snapshot)
    if isinstance(value, Mapping):
        sanitized: dict[str, object] = {}
        for k, v in value.items():
            key_str = str(k)
            if _is_banned_key(key_str):
                sanitized[key_str] = REDACTED
            else:
                sanitized[key_str] = _redact_value(v, secrets_snapshot)
        return sanitized
    if isinstance(value, list):
        return [_redact_value(item, secrets_snapshot) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item, secrets_snapshot) for item in value]
    return value


def redact_event_dict(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Structlog processor that redacts content fields, headers, and secrets."""
    with _SECRETS_LOCK:
        secrets_snapshot = tuple(sorted(_REGISTERED_SECRETS, key=len, reverse=True))
    for key in list(event_dict.keys()):
        if _is_banned_key(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key], secrets_snapshot)
    return event_dict


def configure_logging(*, stream: TextIO | None = None, level: str = "INFO") -> None:
    """Configure structlog JSON output with timestamping and mandatory redaction."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    target_stream = stream if stream is not None else sys.stderr
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            redact_event_dict,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=target_stream),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> FilteringBoundLogger:
    """Return a bound structured logger tagged with the component name."""
    return cast(FilteringBoundLogger, structlog.get_logger(component=name))


def sha256_text(value: str) -> str:
    """Return lowercase hex SHA-256 digest of a UTF-8 string for safe log correlation."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "BANNED_LOG_KEYS",
    "REDACTED",
    "clear_registered_secrets",
    "configure_logging",
    "get_logger",
    "redact_event_dict",
    "register_secret",
    "sha256_text",
]
