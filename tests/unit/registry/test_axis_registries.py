"""Integrity checks for the Axis 1 and Axis 2 registries (DLE-REG-001, DLE-REG-002).

T-UNIT-REG-01..08. Run after any edit to config/registry/*.csv.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

REGISTRY = Path(__file__).resolve().parents[3] / "config" / "registry"


def _rows(name: str) -> list[dict[str, str]]:
    with (REGISTRY / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def pillars() -> list[dict[str, str]]:
    return _rows("axis1_pillars.csv")


@pytest.fixture(scope="module")
def sectors() -> list[dict[str, str]]:
    return _rows("axis2_sectors.csv")


@pytest.fixture(scope="module")
def crosswalk() -> list[dict[str, str]]:
    return _rows("axis2_crosswalk.csv")


def test_pillar_ids_unique_and_well_formed(pillars):
    """T-UNIT-REG-01: PL<nnn>, unique, coordinate 1.<n>.0.0 matches the ID."""
    ids = [p["pillar_id"] for p in pillars]
    assert len(ids) == len(set(ids))
    for p in pillars:
        m = re.fullmatch(r"PL(\d{3})", p["pillar_id"])
        assert m, p["pillar_id"]
        assert p["coordinate"] == f"1.{int(m.group(1))}.0.0"
        assert p["name"].strip()


def test_pillar_status_and_aliases(pillars):
    """T-UNIT-REG-02: only active/alias; every alias points to an active pillar."""
    by_id = {p["pillar_id"]: p for p in pillars}
    for p in pillars:
        assert p["status"] in {"active", "alias"}, p["pillar_id"]
        if p["status"] == "alias":
            target = by_id.get(p["canonical_id"])
            assert target is not None and target["status"] == "active", p["pillar_id"]
            assert p["canonical_id"] != p["pillar_id"]
        else:
            assert p["canonical_id"] == p["pillar_id"]


def test_pillar_counts(pillars):
    """T-UNIT-REG-03: approved 2026-11-20 shape — 114 active, 4 aliases."""
    status = [p["status"] for p in pillars]
    assert status.count("active") == 114
    assert status.count("alias") == 4


def test_sector_ids_and_coordinates(sectors):
    """T-UNIT-REG-04: SC01..SC20 in order, coordinate 2.<n>.0.0."""
    assert [s["sector_id"] for s in sectors] == [f"SC{i:02d}" for i in range(1, 21)]
    for i, s in enumerate(sectors, start=1):
        assert s["coordinate"] == f"2.{i}.0.0"
        assert s["status"] == "active"


def test_sector_naics_codes(sectors):
    """T-UNIT-REG-05: the 20 NAICS 2022 sector codes, each once."""
    expected = [
        "11",
        "21",
        "22",
        "23",
        "31-33",
        "42",
        "44-45",
        "48-49",
        "51",
        "52",
        "53",
        "54",
        "55",
        "56",
        "61",
        "62",
        "71",
        "72",
        "81",
        "92",
    ]
    assert [s["naics_2022"] for s in sectors] == expected


def test_crosswalk_references_and_resolution(crosswalk, sectors):
    """T-UNIT-REG-06: every row names a known sector and a valid resolution."""
    ids = {s["sector_id"] for s in sectors}
    for r in crosswalk:
        assert r["sector_id"] in ids
        assert r["resolution"] in {"resolvable", "crosswalk only", "excluded"}
        assert r["code_as_given"].strip()


def test_only_current_naics_is_resolvable(crosswalk, sectors):
    """T-UNIT-REG-07: resolvable rows are NAICS codes present in that sector's 2022 seeds."""
    seeds = {
        s["sector_id"]: {
            part.strip().split(" ")[0] for part in s["seed_subsectors_naics_2022"].split(";")
        }
        for s in sectors
    }
    for r in crosswalk:
        if r["resolution"] == "resolvable":
            assert r["scheme"] == "NAICS"
            assert r["code_as_given"] in seeds[r["sector_id"]], r


def test_retired_naics_have_successors(crosswalk, sectors):
    """T-UNIT-REG-08: retired NAICS 2017 codes are crosswalk-only and point to a 2022 seed."""
    seeds = {
        s["sector_id"]: {
            part.strip().split(" ")[0] for part in s["seed_subsectors_naics_2022"].split(";")
        }
        for s in sectors
    }
    retired = [r for r in crosswalk if r["scheme"] == "NAICS" and r["resolution"] != "resolvable"]
    assert len(retired) == 9
    for r in retired:
        assert r["resolution"] == "crosswalk only"
        assert r["naics_2022_successor"] in seeds[r["sector_id"]], r
