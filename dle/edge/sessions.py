"""Session resolver computing deterministic JCS history-hash session IDs.

Implements FR-SES-01, FR-SES-02, FR-SES-03, and ADR-003. A multi-turn chat's
session ID equals the SHA-256 of the JCS-canonical tuple
``{tenant, model, systemInstruction, history}`` where ``history`` excludes the
newest incoming user/function turn, or the explicit ``X-DLE-Session`` header.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from dle.config.loader import compute_policy_digest
from dle.errors import SessionError

MAX_EXPLICIT_SESSION_LEN = 128


def _normalize_model(model: str) -> str:
    return model.removeprefix("models/")


def _validate_explicit_session(explicit_session: str | None) -> str | None:
    if explicit_session is None:
        return None
    trimmed = explicit_session.strip()
    if not trimmed:
        raise SessionError("X-DLE-Session header cannot be empty")
    if len(trimmed) > MAX_EXPLICIT_SESSION_LEN:
        raise SessionError(
            f"X-DLE-Session length ({len(trimmed)}) exceeds limit ({MAX_EXPLICIT_SESSION_LEN})"
        )
    return trimmed


def _is_incoming_user_or_function_turn(turn: Mapping[str, object]) -> bool:
    role = turn.get("role")
    if role in (None, "user", "function"):
        return True
    parts = turn.get("parts")
    if isinstance(parts, list):
        return any(isinstance(part, Mapping) and "functionResponse" in part for part in parts)
    return False


def _strip_newest_incoming_turn(
    contents: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    items = [{str(k): v for k, v in item.items()} for item in contents]
    if items and _is_incoming_user_or_function_turn(items[-1]):
        return items[:-1]
    return items


def resolve_session_id(
    *,
    tenant: str,
    model: str,
    system_instruction: Mapping[str, object] | None,
    contents: Sequence[Mapping[str, object]],
    explicit_session: str | None = None,
) -> str:
    """Resolve deterministic session ID from incoming request history or ``X-DLE-Session``."""
    override = _validate_explicit_session(explicit_session)
    if override is not None:
        return override

    payload: dict[str, object] = {
        "tenant": tenant,
        "model": _normalize_model(model),
        "systemInstruction": dict(system_instruction) if system_instruction is not None else None,
        "history": _strip_newest_incoming_turn(contents),
    }
    return compute_policy_digest(payload)


def session_id_after_response(
    *,
    tenant: str,
    model: str,
    system_instruction: Mapping[str, object] | None,
    contents: Sequence[Mapping[str, object]],
    response_content: Mapping[str, object],
    explicit_session: str | None = None,
) -> str:
    """Compute the post-response session ID that the client's next turn will match."""
    override = _validate_explicit_session(explicit_session)
    if override is not None:
        return override

    history = [
        *[{str(k): v for k, v in item.items()} for item in contents],
        {str(k): v for k, v in response_content.items()},
    ]
    payload: dict[str, object] = {
        "tenant": tenant,
        "model": _normalize_model(model),
        "systemInstruction": dict(system_instruction) if system_instruction is not None else None,
        "history": history,
    }
    return compute_policy_digest(payload)


@dataclass(frozen=True)
class SessionRecord:
    """In-memory session metadata tracking TTL expiry."""

    session_id: str
    tenant: str
    model: str
    created_utc: datetime
    last_seen_utc: datetime
    expires_utc: datetime


class InMemorySessionStore:
    """Thread-safe ephemeral session store supporting Phase 1 pass-through and expiry purge."""

    def __init__(self, *, expiry_hours: float = 24.0) -> None:
        """Initialize empty session table with configurable idle TTL."""
        if expiry_hours <= 0.0:
            raise ValueError("expiry_hours must be positive")
        self._ttl = timedelta(hours=expiry_hours)
        self._lock = threading.Lock()
        self._records: dict[str, SessionRecord] = {}

    def touch(
        self,
        session_id: str,
        *,
        tenant: str,
        model: str,
        now: datetime | None = None,
    ) -> SessionRecord:
        """Insert or refresh a session record and return its updated snapshot."""
        ts = now if now is not None else datetime.now(UTC)
        with self._lock:
            existing = self._records.get(session_id)
            created = existing.created_utc if existing is not None else ts
            record = SessionRecord(
                session_id=session_id,
                tenant=tenant,
                model=_normalize_model(model),
                created_utc=created,
                last_seen_utc=ts,
                expires_utc=ts + self._ttl,
            )
            self._records[session_id] = record
            return record

    def get(self, session_id: str) -> SessionRecord | None:
        """Return session record if present."""
        with self._lock:
            return self._records.get(session_id)

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Delete expired session records and return count removed."""
        ts = now if now is not None else datetime.now(UTC)
        with self._lock:
            expired = [sid for sid, rec in self._records.items() if rec.expires_utc <= ts]
            for sid in expired:
                del self._records[sid]
            return len(expired)


__all__ = [
    "MAX_EXPLICIT_SESSION_LEN",
    "InMemorySessionStore",
    "SessionRecord",
    "resolve_session_id",
    "session_id_after_response",
]
