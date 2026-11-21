"""Half-open valid-time intervals for Axis 13 (DLE-SPC-005).

Rules (white paper v3.13 §07):
- Intervals are half-open: start <= t < end. ``end is None`` means open (no known end).
- An inclusive last date ("through June 30") becomes an exclusive end once, on ingest.
- Date granularity uses civil dates in the record's time zone; instant granularity uses UTC.
- Legacy forms are converted on ingest and never stored as the canonical value.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

Point = date | datetime

OPEN_SENTINELS = {"9999-12-31", "9999.4", "13.9999.4"}
_QUARTER = re.compile(r"^(?:13\.)?(\d{4})\.([1-4])$")
_QUARTER_PAIR = re.compile(r"^\[\s*(13\.\d{4}\.[1-4])\s*,\s*(13\.\d{4}\.[1-4])\s*\]$")
_ISO_DATE_INTERVAL = re.compile(r"^(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})$")


class LegacyFormatError(ValueError):
    """Raised when a legacy temporal value cannot be converted without guessing."""


@dataclass(frozen=True)
class Interval:
    """A non-empty half-open interval [start, end); end None means open."""

    start: Point
    end: Point | None
    granularity: str = "date"

    def __post_init__(self) -> None:  # noqa: D105
        if self.granularity not in ("date", "instant"):
            raise ValueError("granularity must be 'date' or 'instant'")
        kinds = {type(self.start)} | ({type(self.end)} if self.end is not None else set())
        if self.granularity == "date" and any(k is datetime for k in kinds):
            raise ValueError("date granularity cannot hold datetimes")
        if self.granularity == "instant":
            for p in (self.start, self.end):
                if p is not None and (not isinstance(p, datetime) or p.utcoffset() != timedelta(0)):
                    raise ValueError("instant granularity needs UTC datetimes")
        if self.end is not None and not self.start < self.end:
            raise ValueError("start must be before end (half-open, non-empty)")


def inclusive_to_exclusive(last_day: date) -> date:
    """Convert an inclusive last date to the exclusive end of a half-open interval."""
    if isinstance(last_day, datetime):
        raise TypeError("inclusive conversion applies to dates, not instants")
    return last_day + timedelta(days=1)


def contains(iv: Interval, t: Point) -> bool:
    """Start <= t < end, with an open end containing every later point."""
    if (iv.granularity == "date") != (not isinstance(t, datetime)):
        raise TypeError("compare dates with date intervals and instants with instant intervals")
    return iv.start <= t and (iv.end is None or t < iv.end)


def overlaps(a: Interval, b: Interval) -> bool:
    """Two half-open intervals overlap when each begins before the other ends."""
    if a.granularity != b.granularity:
        raise TypeError("cannot compare date and instant intervals")
    a_before_b_end = b.end is None or a.start < b.end
    b_before_a_end = a.end is None or b.start < a.end
    return a_before_b_end and b_before_a_end


def _quarter_start(year: int, q: int) -> date:
    return date(year, 3 * (q - 1) + 1, 1)


def _next_quarter_start(year: int, q: int) -> date:
    return date(year + 1, 1, 1) if q == 4 else _quarter_start(year, q + 1)


def _parse_quarter(token: str) -> tuple[int, int]:
    m = _QUARTER.match(token)
    if not m:
        raise LegacyFormatError(f"not a quarter token: {token!r}")
    return int(m.group(1)), int(m.group(2))


def parse_legacy(value: Any) -> Interval:  # noqa: ANN401
    """Convert a legacy Axis 13 value to a date-granularity half-open interval.

    Accepted forms:
    - ``"13.YYYY.Q"`` one quarter.
    - ``"[13.YYYY.Q, 13.YYYY.Q]"`` quarter range, end quarter inclusive; ``13.9999.4`` = open.
    - ``"YYYY-MM-DD/YYYY-MM-DD"`` ISO date interval, end day inclusive; ``9999-12-31`` = open.
    - ``{"effective_start", "effective_end", "is_active"}`` (v3.0 shape); end inclusive unless
      ``end_exclusive`` is true; ``is_active`` true with no end = open.
    """
    if isinstance(value, Mapping):
        start = date.fromisoformat(str(value["effective_start"]))
        raw_end = value.get("effective_end")
        if raw_end in (None, "") or str(raw_end) in OPEN_SENTINELS:
            if value.get("is_active") is False:
                raise LegacyFormatError("inactive record with no end date: end is unknown")
            return Interval(start, None)
        end = date.fromisoformat(str(raw_end))
        return Interval(start, end if value.get("end_exclusive") else inclusive_to_exclusive(end))
    if not isinstance(value, str):
        raise LegacyFormatError(f"unsupported legacy value: {value!r}")
    text = value.strip()
    m = _QUARTER_PAIR.match(text)
    if m:
        y1, q1 = _parse_quarter(m.group(1))
        start = _quarter_start(y1, q1)
        if m.group(2) in OPEN_SENTINELS:
            return Interval(start, None)
        y2, q2 = _parse_quarter(m.group(2))
        return Interval(start, _next_quarter_start(y2, q2))
    if _QUARTER.match(text):
        y, q = _parse_quarter(text)
        if text in OPEN_SENTINELS:
            raise LegacyFormatError("open sentinel is not a start")
        return Interval(_quarter_start(y, q), _next_quarter_start(y, q))
    m = _ISO_DATE_INTERVAL.match(text)
    if m:
        start = date.fromisoformat(m.group(1))
        if m.group(2) in OPEN_SENTINELS:
            return Interval(start, None)
        return Interval(start, inclusive_to_exclusive(date.fromisoformat(m.group(2))))
    raise LegacyFormatError(f"unrecognized legacy temporal value: {value!r}")


def _to_point(raw: str | None, granularity: str) -> Point | None:
    if raw is None:
        return None
    if granularity == "date":
        return date.fromisoformat(raw)
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)


def interval_of(record: Mapping[str, Any]) -> Interval | None:
    """Build an Interval from an Axis 13 record; None when the determination is unknown."""
    if record["determination"] == "unknown":
        return None
    g = record["granularity"]
    start = _to_point(record["start"], g)
    if start is None:
        raise LegacyFormatError("a determined interval needs a start")
    return Interval(start, _to_point(record["end"], g), g)


def project(record: Mapping[str, Any], as_of: date, *, allow_widen: bool = False) -> dict[str, Any]:
    """Project a full Axis 13 record to the coordinate's ``axis_13_temporal`` atom (contract 3.7.1).

    The 3.7.1 atom holds dates only. An instant record is refused unless ``allow_widen`` is set,
    in which case the start is floored and the end ceiled to whole UTC days (never narrowed).
    An unknown determination cannot be projected: the caller must open a dependency instead.
    """
    iv = interval_of(record)
    if iv is None:
        raise LegacyFormatError("unknown valid time cannot be projected; open a dependency")
    start: date
    end: date | None
    if iv.granularity == "instant":
        if not allow_widen:
            raise LegacyFormatError(
                "instant precision would be lost; pass allow_widen=True to widen"
            )
        if not isinstance(iv.start, datetime):
            raise TypeError("instant interval without a datetime start")
        start = iv.start.date()
        end = None
        if iv.end is not None:
            if not isinstance(iv.end, datetime):
                raise TypeError("instant interval without a datetime end")
            e = iv.end
            end = e.date() if e.time() == datetime.min.time() else e.date() + timedelta(days=1)
    else:
        start, end = iv.start, iv.end
    return {
        "claim_scope": record["claim_scope"],
        "effective_start": start.isoformat(),
        "effective_end": end.isoformat() if end is not None else None,
        "as_of": as_of.isoformat(),
    }
