"""Axis 13 valid time (DLE-SPC-005). T-UNIT-TMP-01..10."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import jsonschema
import pytest

from dle.temporal import (
    Interval,
    LegacyFormatError,
    contains,
    inclusive_to_exclusive,
    interval_of,
    overlaps,
    parse_legacy,
    project,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "registry" / "axis13_intervals.jsonl"
PRODUCTION = ROOT / "config" / "registry" / "axis13_intervals.jsonl"


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _validator(rel: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


@pytest.fixture(scope="module")
def records() -> list[dict]:
    return _jsonl(FIXTURES)


def test_schema_and_fixtures(records):
    """T-UNIT-TMP-01: the record schema compiles and every fixture validates."""
    v = _validator("contracts/registry/axis13_interval.schema.json")
    for r in records:
        errs = list(v.iter_errors(r))
        assert not errs, f"{r['interval_id']}: {errs[0].message}"
    for r in _jsonl(PRODUCTION):
        assert r["status"] != "fixture" and not list(v.iter_errors(r))


def test_schema_rejects_bad_records(records):
    """T-UNIT-TMP-02: bad unknown, missing evidence and mixed granularity are rejected."""
    v = _validator("contracts/registry/axis13_interval.schema.json")
    base = dict(records[1])
    bad_unknown = {**base, "determination": "unknown"}
    no_evidence = {k: val for k, val in base.items() if k != "evidence"}
    mixed = {**base, "end": "2027-01-01T00:00:00Z"}
    converted_no_text = {k: val for k, val in base.items() if k != "source_text"}
    for bad in (bad_unknown, no_evidence, mixed, converted_no_text):
        assert list(v.iter_errors(bad)), bad


def test_half_open_containment():
    """T-UNIT-TMP-03: start is in, end is out, open end contains the future."""
    iv = Interval(date(2026, 1, 1), date(2027, 1, 1))
    assert contains(iv, date(2026, 1, 1))
    assert contains(iv, date(2026, 12, 31))
    assert not contains(iv, date(2027, 1, 1))
    assert not contains(iv, date(2025, 12, 31))
    assert contains(Interval(date(2026, 1, 1), None), date(2999, 1, 1))


def test_overlap_rule():
    """T-UNIT-TMP-04: adjacent intervals do not overlap; open intervals overlap anything later."""
    a = Interval(date(2025, 1, 1), date(2026, 1, 1))
    b = Interval(date(2026, 1, 1), date(2027, 1, 1))
    assert not overlaps(a, b) and not overlaps(b, a)
    assert overlaps(a, Interval(date(2025, 6, 1), None))
    assert overlaps(Interval(date(2025, 6, 1), None), Interval(date(2030, 1, 1), None))


def test_inclusive_conversion():
    """T-UNIT-TMP-05: 'through Dec 31' becomes an exclusive end of Jan 1, once."""
    assert inclusive_to_exclusive(date(2025, 12, 31)) == date(2026, 1, 1)
    assert inclusive_to_exclusive(date(2024, 2, 28)) == date(2024, 2, 29)
    with pytest.raises(TypeError):
        inclusive_to_exclusive(datetime(2025, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize(
    ("legacy", "start", "end"),
    [
        ("13.2026.2", date(2026, 4, 1), date(2026, 7, 1)),
        ("[13.2025.4, 13.2026.1]", date(2025, 10, 1), date(2026, 4, 1)),
        ("[13.2018.2, 13.9999.4]", date(2018, 4, 1), None),
        ("2018-05-25/9999-12-31", date(2018, 5, 25), None),
        ("2025-01-01/2025-12-31", date(2025, 1, 1), date(2026, 1, 1)),
        (
            {"effective_start": "2026-01-01", "effective_end": None, "is_active": True},
            date(2026, 1, 1),
            None,
        ),
        (
            {"effective_start": "2026-01-01", "effective_end": "2026-06-30"},
            date(2026, 1, 1),
            date(2026, 7, 1),
        ),
    ],
)
def test_legacy_forms(legacy, start, end):
    """T-UNIT-TMP-06: each legacy Axis 13 form converts to one half-open interval."""
    iv = parse_legacy(legacy)
    assert (iv.start, iv.end) == (start, end)


@pytest.mark.parametrize(
    "legacy", ["13.9999.4", "Q2 2026", {"effective_start": "2026-01-01", "is_active": False}]
)
def test_legacy_refuses_guessing(legacy):
    """T-UNIT-TMP-07: ambiguous legacy values raise instead of guessing."""
    with pytest.raises(LegacyFormatError):
        parse_legacy(legacy)


def test_version_chain(records):
    """T-UNIT-TMP-08: successor starts at the predecessor end, links both ways, no overlap."""
    by_id = {r["interval_id"]: r for r in records}
    for r in records:
        if "superseded_by" in r:
            nxt = by_id[r["superseded_by"]]
            assert nxt["supersedes"] == r["interval_id"]
            assert nxt["subject"] == r["subject"]
            assert r["end"] == nxt["start"]
            assert not overlaps(interval_of(r), interval_of(nxt))


def test_projection_matches_coordinate_contract(records):
    """T-UNIT-TMP-09: projected atoms validate against the 3.7.1 coordinate axis_13 item."""
    coord = json.loads((ROOT / "contracts" / "coordinate.schema.json").read_text(encoding="utf-8"))
    item = jsonschema.Draft202012Validator(
        coord["properties"]["axis_13_temporal"]["items"], format_checker=jsonschema.FormatChecker()
    )
    atom = project(records[1], date(2026, 6, 1))
    assert atom == {
        "claim_scope": "change-control schedule (renewal term)",
        "effective_start": "2026-01-01",
        "effective_end": "2027-01-01",
        "as_of": "2026-06-01",
    }
    assert not list(item.iter_errors(atom))
    assert contains(interval_of(records[1]), date(2026, 6, 1))
    assert not contains(interval_of(records[0]), date(2026, 6, 1))


def test_projection_refusals(records):
    """T-UNIT-TMP-10: unknown cannot project; instants project only when widening is allowed."""
    with pytest.raises(LegacyFormatError):
        project(records[3], date(2026, 6, 1))
    with pytest.raises(LegacyFormatError):
        project(records[2], date(2026, 6, 1))
    widened = project(records[2], date(2026, 6, 1), allow_widen=True)
    assert widened["effective_start"] == "2026-03-14" and widened["effective_end"] is None
