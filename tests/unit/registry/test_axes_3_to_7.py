"""Axes 3-7 registry contracts (DLE-SPC-003). T-UNIT-REG-09..15."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "contracts" / "registry"
FIXTURES = ROOT / "tests" / "fixtures" / "registry"
PRODUCTION = ROOT / "config" / "registry"

FILES = {
    "axis3_links": "axis3_link.schema.json",
    "axis4_branches": "axis4_branch.schema.json",
    "axis5_nodes": "axis5_node.schema.json",
    "axis6_hubs": "axis6_hub.schema.json",
    "axis7_meshes": "axis7_mesh.schema.json",
}
ID_FIELD = {
    "axis3_links": "link_id",
    "axis4_branches": "branch_id",
    "axis5_nodes": "node_id",
    "axis6_hubs": "hub_id",
    "axis7_meshes": "mesh_id",
}


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _validator(schema_file: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((SCHEMAS / schema_file).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


@pytest.fixture(scope="module")
def fx() -> dict[str, list[dict]]:
    return {name: _jsonl(FIXTURES / f"{name}.jsonl") for name in FILES}


@pytest.fixture(scope="module")
def known_atoms(fx) -> set[str]:
    with (PRODUCTION / "axis1_pillars.csv").open(newline="", encoding="utf-8") as fh:
        pillars = {f"[PL:{p['coordinate']}]" for p in csv.DictReader(fh) if p["status"] == "active"}
    records = {r[ID_FIELD[name]] for name, rows in fx.items() for r in rows}
    return pillars | records


@pytest.mark.parametrize("name", list(FILES))
def test_schemas_compile_and_fixtures_validate(name, fx):
    """T-UNIT-REG-09: each schema is valid Draft 2020-12 and every fixture record conforms."""
    v = _validator(FILES[name])
    assert fx[name], f"no fixtures for {name}"
    for rec in fx[name]:
        errors = sorted(v.iter_errors(rec), key=str)
        assert not errors, f"{name} {rec.get(ID_FIELD[name])}: {errors[0].message}"


def test_ids_unique(fx):
    """T-UNIT-REG-10: record IDs are unique within each registry."""
    for name, rows in fx.items():
        ids = [r[ID_FIELD[name]] for r in rows]
        assert len(ids) == len(set(ids)), name


def test_atoms_resolve(fx, known_atoms):
    """T-UNIT-REG-11: every atom a record references is a registered pillar or record."""
    refs: list[str] = []
    for link in fx["axis3_links"]:
        refs += [link["subject"], link["object"]]
    for node in fx["axis5_nodes"]:
        refs += node["anchors"] + node.get("via_links", [])
    for hub in fx["axis6_hubs"]:
        refs += hub.get("anchors", [])
    missing = sorted(set(refs) - known_atoms)
    assert not missing, missing


def test_branch_roots_and_parents(fx):
    """T-UNIT-REG-12: branch path matches its root; parents exist; sector branches follow NAICS."""
    ids = {b["branch_id"] for b in fx["axis4_branches"]}
    for b in fx["axis4_branches"]:
        m = re.fullmatch(r"\[BR:4\.([12])\.(\d+)((?:\.\d+)+)\]", b["branch_id"])
        assert m, b["branch_id"]
        axis, root_num, rest = m.group(1), int(m.group(2)), m.group(3).strip(".").split(".")
        expected_root = f"PL{root_num:03d}" if axis == "1" else f"SC{root_num:02d}"
        assert b["root"] == expected_root
        assert b["depth"] == len(rest)
        if b["parent"] is None:
            assert b["depth"] == 1
        else:
            assert b["parent"] in ids and b["branch_id"].startswith(b["parent"][:-1] + ".")
        if axis == "2":
            assert rest[-1] == b["naics_2022"]


def test_intersections_cite_links(fx):
    """T-UNIT-REG-13: intersection nodes name at least one existing Axis 3 link."""
    links = {link["link_id"] for link in fx["axis3_links"]}
    for n in fx["axis5_nodes"]:
        if n["kind"] == "intersection":
            assert n["via_links"] and set(n["via_links"]) <= links, n["node_id"]


def test_mesh_requirements_resolve(fx):
    """T-UNIT-REG-14: mesh requirements point to hub arms; relations use them."""
    arms = {f"{h['hub_id']}#{a['arm_id']}" for h in fx["axis6_hubs"] for a in h["arms"]}
    for m in fx["axis7_meshes"]:
        for req in m["requirements"]:
            assert req.startswith("CITE:") or req in arms, req
        listed = set(m["requirements"])
        for rel in m["relations"]:
            assert rel["a"] in listed and rel["b"] in listed and rel["a"] != rel["b"]


@pytest.mark.parametrize("name", list(FILES))
def test_production_has_no_fixtures(name):
    """T-UNIT-REG-15: production registries validate and never contain fixture records."""
    v = _validator(FILES[name])
    for rec in _jsonl(PRODUCTION / f"{name}.jsonl"):
        assert rec["status"] != "fixture"
        assert not list(v.iter_errors(rec))
