"""Client tool call pass-through extraction and parked run state (`E4`).

Implements FR-TOOL-01, FR-TOOL-02, FR-TOOL-03, and ADR-002. Client tool
declarations and ``functionCall`` parts pass through untouched; runs awaiting
``functionResponse`` are parked by post-response session ID with TTL expiry.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


def extract_model_content(response_body: Mapping[str, object]) -> dict[str, object] | None:
    """Return a deep copy of ``candidates[0].content`` when present."""
    candidates = response_body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    first = candidates[0]
    if not isinstance(first, Mapping):
        return None
    content = first.get("content")
    if not isinstance(content, Mapping):
        return None
    return copy.deepcopy({str(k): v for k, v in content.items()})


def extract_function_calls(response_body: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    """Extract ``functionCall`` parts in original order with ``id``, ``name``, and ``args``."""
    content = extract_model_content(response_body)
    if content is None:
        return ()
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ()
    calls: list[dict[str, object]] = []
    for part in parts:
        if isinstance(part, Mapping) and isinstance(part.get("functionCall"), Mapping):
            calls.append(copy.deepcopy({str(k): v for k, v in part["functionCall"].items()}))
    return tuple(calls)


@dataclass(frozen=True)
class ParkedRun:
    """In-flight run paused until client returns ``functionResponse``."""

    run_id: str
    session_id: str
    pending_calls: tuple[dict[str, object], ...]
    run_state: dict[str, object]
    parked_utc: datetime
    expires_utc: datetime


class ToolBridge:
    """Thread-safe park/resume store keyed by post-response session ID with TTL expiry."""

    def __init__(self, *, expiry_hours: float = 24.0) -> None:
        """Initialize an empty parked-run store with TTL ``expiry_hours``."""
        if expiry_hours <= 0.0:
            raise ValueError("expiry_hours must be positive")
        self._ttl = timedelta(hours=expiry_hours)
        self._lock = threading.Lock()
        self._parked: dict[str, ParkedRun] = {}

    def park(
        self,
        *,
        run_id: str,
        session_id: str,
        pending_calls: tuple[dict[str, object], ...],
        run_state: Mapping[str, object],
        now: datetime | None = None,
    ) -> ParkedRun:
        """Park ``pending_calls`` and ``run_state`` under ``session_id``."""
        ts = now if now is not None else datetime.now(UTC)
        record = ParkedRun(
            run_id=run_id,
            session_id=session_id,
            pending_calls=tuple(copy.deepcopy(call) for call in pending_calls),
            run_state=copy.deepcopy({str(k): v for k, v in run_state.items()}),
            parked_utc=ts,
            expires_utc=ts + self._ttl,
        )
        with self._lock:
            self._parked[session_id] = record
        return record

    def peek(self, session_id: str) -> ParkedRun | None:
        """Return currently parked run without popping it."""
        with self._lock:
            return self._parked.get(session_id)

    def resume(self, session_id: str, *, now: datetime | None = None) -> ParkedRun | None:
        """Purge expired parked runs, then pop and return the run for ``session_id``."""
        ts = now if now is not None else datetime.now(UTC)
        with self._lock:
            expired = [sid for sid, rec in self._parked.items() if rec.expires_utc <= ts]
            for sid in expired:
                del self._parked[sid]
            return self._parked.pop(session_id, None)

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Delete all expired parked runs and return how many were removed."""
        ts = now if now is not None else datetime.now(UTC)
        with self._lock:
            expired = [sid for sid, rec in self._parked.items() if rec.expires_utc <= ts]
            for sid in expired:
                del self._parked[sid]
            return len(expired)

    def count(self) -> int:
        """Return number of currently parked runs."""
        with self._lock:
            return len(self._parked)


__all__ = [
    "ParkedRun",
    "ToolBridge",
    "extract_function_calls",
    "extract_model_content",
]
