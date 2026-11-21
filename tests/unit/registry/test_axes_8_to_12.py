"""Axes 8-12 contracts (DLE-SPC-004). T-UNIT-REG-16..22."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "contracts" / "registry"
FIXTURES = ROOT / "tests" / "fixtures" / "registry"
REGISTRY = ROOT / "config" / "registry"
CONDUCT = ROOT / "config" / "personas" / "conduct.yaml"

ROLE_FOR_AXIS = {8: "Scholar", 9: "Practitioner", 10: "Regulator", 11: "Harmonizer"}
FIELDS = [
    "job_role",
    "education",
    "certifications",
    "skills",
    "job_training",
    "career_path",
    "related_jobs",
]
HUMAN_NAME = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Prof)\.?\s+[A-Z]|,\s*(?:MD|JD|PhD|Esq)\b|\b(?:DR|MR|MRS|MS|PROF)_[A-Z]+"
)


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _validator(name: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


@pytest.fixture(scope="module")
def profiles() -> list[dict]:
    return _jsonl(FIXTURES / "personas.jsonl")


@pytest.fixture(scope="module")
def jurisdictions() -> list[dict]:
    return _jsonl(FIXTURES / "axis12_jurisdictions.jsonl")


def _items(profile: dict) -> list[dict]:
    f = profile["fields"]
    return [f["job_role"]] + [i for k in FIELDS[1:] for i in f[k]]


def _inputs(profile: dict) -> set[str]:
    out: set[str] = set()
    for val in profile["inputs"].values():
        if isinstance(val, list):
            out |= set(val)
    return out


def test_schemas_and_fixtures(profiles, jurisdictions):
    """T-UNIT-REG-16: schemas compile; every fixture validates."""
    pv, jv = (
        _validator("persona_profile.schema.json"),
        _validator("axis12_jurisdiction.schema.json"),
    )
    assert len(profiles) == 4 and jurisdictions
    for p in profiles:
        errs = list(pv.iter_errors(p))
        assert not errs, f"{p['profile_id']}: {errs[0].message}"
    for j in jurisdictions:
        errs = list(jv.iter_errors(j))
        assert not errs, f"{j['jurisdiction_id']}: {errs[0].message}"


def test_role_axis_pairing(profiles):
    """T-UNIT-REG-17: one profile per role axis; ID prefix and role name match the axis."""
    assert sorted(p["axis"] for p in profiles) == [8, 9, 10, 11]
    for p in profiles:
        assert p["role_name"] == ROLE_FOR_AXIS[p["axis"]]
        assert p["profile_id"].startswith(f"[ROLE:{p['axis']}.")
        assert p["conduct_ref"].endswith(f"#axis{p['axis']}")


def test_derived_from_within_inputs(profiles):
    """T-UNIT-REG-18: every field item is built only from the profile's own inputs."""
    for p in profiles:
        allowed = _inputs(p)
        for item in _items(p):
            stray = set(item["derived_from"]) - allowed
            assert not stray, f"{p['profile_id']} {item['text']}: {stray}"


def test_inputs_resolve(profiles, jurisdictions):
    """T-UNIT-REG-19: pillar and sector inputs are registered; others exist in fixtures."""
    with (REGISTRY / "axis1_pillars.csv").open(newline="", encoding="utf-8") as fh:
        pillars = {f"[PL:{r['coordinate']}]" for r in csv.DictReader(fh) if r["status"] == "active"}
    with (REGISTRY / "axis2_sectors.csv").open(newline="", encoding="utf-8") as fh:
        sectors = {f"[SECTOR:{r['coordinate']}]" for r in csv.DictReader(fh)}
    ids = {"branch_id": "axis4_branches", "hub_id": "axis6_hubs", "mesh_id": "axis7_meshes"}
    known = {r[k] for k, f in ids.items() for r in _jsonl(FIXTURES / f"{f}.jsonl")}
    arms = {
        f"{h['hub_id']}#{a['arm_id']}"
        for h in _jsonl(FIXTURES / "axis6_hubs.jsonl")
        for a in h["arms"]
    }
    jur = {j["jurisdiction_id"] for j in jurisdictions}
    for p in profiles:
        i = p["inputs"]
        assert set(i.get("pillars", [])) <= pillars
        assert set(i.get("sectors", [])) <= sectors
        assert set(i.get("branches", []) + i.get("hubs", []) + i.get("meshes", [])) <= known
        assert set(i.get("hub_arms", [])) <= arms
        if p["axis"] in (10, 11):
            assert i["jurisdiction"] in jur


def test_credential_sources(profiles):
    """T-UNIT-REG-20: Regulator credentials trace to hub arms; Harmonizer ones to meshes."""
    for p in profiles:
        for c in p["fields"]["certifications"]:
            if p["axis"] == 10:
                assert any("#" in d for d in c["derived_from"])
            if p["axis"] == 11:
                assert any(d.startswith("[MESH:7.") for d in c["derived_from"])


def test_no_human_names(profiles):
    """T-UNIT-REG-21: profiles describe perspectives, never named people or personal credentials."""
    for p in profiles:
        text = json.dumps(p["fields"]) + p["mandate"]
        assert not HUMAN_NAME.search(text), p["profile_id"]
    assert (
        HUMAN_NAME.search("Dr. Sarah Chen")
        and HUMAN_NAME.search("Sarah Chen, MD")
        and HUMAN_NAME.search("DR_SARAH")
    )


def test_conduct_file():
    """T-UNIT-REG-22: conduct covers all four roles and carries no activation settings."""
    conduct = yaml.safe_load(CONDUCT.read_text(encoding="utf-8"))
    for ax, name in ROLE_FOR_AXIS.items():
        block = conduct[f"axis{ax}"]
        assert block["role_name"] == name
        assert {"traits", "must", "must_not", "veto_on", "synthesis_weight"} <= set(block)
        assert not {"activation_threshold", "cosine_threshold", "activate_if"} & set(block)
    assert abs(sum(conduct[f"axis{a}"]["synthesis_weight"] for a in ROLE_FOR_AXIS) - 1.0) < 1e-9
    for rec in _jsonl(REGISTRY / "axis12_jurisdictions.jsonl"):
        assert rec["status"] != "fixture"
