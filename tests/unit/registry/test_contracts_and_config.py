"""Contract, fixture, and configuration consistency checks.

T-UNIT-REG-23..28. Covers schemas under contracts/, coordinate fixtures,
Axis 1 ISCED-F completeness, profile/receipt/OpenAPI release-mode alignment,
tiers distance weights, and SQLite migration DDL execution.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import date
from pathlib import Path

import jsonschema
import yaml

from dle.temporal import project

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"
CONFIG = ROOT / "config"
FIXTURES = ROOT / "tests" / "fixtures"
REGISTRY_FIXTURES = FIXTURES / "registry"
MIGRATION_0001 = ROOT / "dle" / "store" / "migrations" / "0001_init.sql"


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_all_contracts_compile_and_coordinate_fixtures_validate():
    """T-UNIT-REG-23: all schemas compile as Draft 2020-12 and coordinate fixtures validate."""
    for schema_path in sorted(CONTRACTS.rglob("*.json")):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)

    coord_schema = json.loads((CONTRACTS / "coordinate.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        coord_schema, format_checker=jsonschema.FormatChecker()
    )
    for name in ("coordinate_warehouse.json", "coordinate_storage_procurement.json"):
        doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(doc), key=str)
        assert not errors, f"{name}: {errors[0].message}"


def test_warehouse_coordinate_resolves_all_atoms_and_time():
    """T-UNIT-REG-24: warehouse coordinate atoms resolve and Axis 13 matches [TIME:13.2]."""
    doc = json.loads((FIXTURES / "coordinate_warehouse.json").read_text(encoding="utf-8"))

    with (CONFIG / "registry" / "axis1_pillars.csv").open(newline="", encoding="utf-8") as fh:
        pillars = {f"[PL:{r['coordinate']}]" for r in csv.DictReader(fh) if r["status"] == "active"}
    with (CONFIG / "registry" / "axis2_sectors.csv").open(newline="", encoding="utf-8") as fh:
        sectors = {f"[SECTOR:{r['coordinate']}]" for r in csv.DictReader(fh)}

    links = {r["link_id"] for r in _jsonl(REGISTRY_FIXTURES / "axis3_links.jsonl")}
    branches = {r["branch_id"] for r in _jsonl(REGISTRY_FIXTURES / "axis4_branches.jsonl")}
    nodes = {r["node_id"] for r in _jsonl(REGISTRY_FIXTURES / "axis5_nodes.jsonl")}
    hubs = {r["hub_id"] for r in _jsonl(REGISTRY_FIXTURES / "axis6_hubs.jsonl")}
    meshes = {r["mesh_id"] for r in _jsonl(REGISTRY_FIXTURES / "axis7_meshes.jsonl")}
    roles = {r["profile_id"] for r in _jsonl(REGISTRY_FIXTURES / "personas.jsonl")}
    jurisdictions = {
        r["jurisdiction_id"] for r in _jsonl(REGISTRY_FIXTURES / "axis12_jurisdictions.jsonl")
    }

    expected_sets = [
        ("axis_1_pillars", pillars),
        ("axis_2_sectors", sectors),
        ("axis_3_honeycomb", links),
        ("axis_4_branches", branches),
        ("axis_5_nodes", nodes),
        ("axis_6_octopus", hubs),
        ("axis_7_spiderweb", meshes),
        ("axis_8_scholar", roles),
        ("axis_9_practitioner", roles),
        ("axis_10_regulator", roles),
        ("axis_11_compliance", roles),
        ("axis_12_jurisdiction", jurisdictions),
    ]
    for field, allowed in expected_sets:
        assert doc[field], f"{field} must not be empty in warehouse fixture"
        for item in doc[field]:
            assert item["canonical_str"] in allowed, f"{field}: {item['canonical_str']}"

    intervals = {r["interval_id"]: r for r in _jsonl(REGISTRY_FIXTURES / "axis13_intervals.jsonl")}
    projected = project(intervals["[TIME:13.2]"], date(2026, 6, 1))
    assert doc["axis_13_temporal"] == [projected]


def test_axis1_has_no_unverified_field_codes():
    """T-UNIT-REG-25: axis1_pillars.csv contains no '(verify)' placeholders."""
    with (CONFIG / "registry" / "axis1_pillars.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        for col in ("isced_f", "ford", "cip"):
            assert "(verify)" not in row[col].lower(), f"{row['pillar_id']} {col}: {row[col]}"


def test_receipt_schema_profile_and_cancelled_enums():
    """T-UNIT-REG-26: receipt.schema.json aligns decision.profile and includes cancelled."""
    receipt = json.loads((CONTRACTS / "receipt.schema.json").read_text(encoding="utf-8"))
    payload_props = receipt["properties"]["payload"]["properties"]
    top_profiles = set(payload_props["profile"]["enum"])
    decision_props = payload_props["decision"]["properties"]
    decision_profiles = set(decision_props["profile"]["enum"])
    assert top_profiles == {"strict", "advisory", "kernel_only", "kernel_plus_policy"}
    assert decision_profiles == top_profiles
    assert "cancelled" in decision_props["release_mode"]["enum"]


def test_profiles_match_openapi_release_modes_and_tiers_weights():
    """T-UNIT-REG-27: profiles use OpenAPI ReleaseMode values and tiers defines distance weights."""
    openapi = yaml.safe_load((CONTRACTS / "openapi.yaml").read_text(encoding="utf-8"))
    valid_modes = set(openapi["components"]["headers"]["ReleaseMode"]["schema"]["enum"])

    for profile_path in sorted((CONFIG / "profiles").glob("*.yaml")):
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        if "release" in data:
            for key, mode in data["release"].items():
                assert mode in valid_modes, f"{profile_path.name} release.{key}={mode!r}"

    tiers = yaml.safe_load((CONFIG / "tiers.yaml").read_text(encoding="utf-8"))
    weights = tiers["distance_weights"]
    assert weights["w3"] > 0
    assert weights["w67"] > 0


def test_sqlite_migration_executes_and_receipts_accept_cancelled():
    """T-UNIT-REG-28: every @database section in 0001_init.sql runs and allows 'cancelled'."""
    sql = MIGRATION_0001.read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in sql.splitlines():
        if line.startswith("-- @database "):
            current = line.split()[2]
            sections[current] = []
        elif current is not None:
            sections[current].append(line)

    assert set(sections) == {"registry", "evidence", "sessions", "receipts", "ops"}

    for db_name, lines in sections.items():
        con = sqlite3.connect(":memory:")
        try:
            con.executescript("\n".join(lines))
            if db_name == "receipts":
                con.execute(
                    "INSERT INTO signing_keys (key_id, public_key_b64, valid_from_utc) "
                    "VALUES ('k1', ?, '2026-11-20T00:00:00Z')",
                    ("A" * 43 + "=",),
                )
                con.execute(
                    "INSERT INTO receipts (receipt_id, chain_id, chain_seq, previous_hash, "
                    "receipt_sha256, response_sha256, release_mode, profile, key_id, "
                    "receipt_jcs, signature_b64, anchoring_profile, sealed_utc) "
                    "VALUES ('r1', 'c1', 0, 'GENESIS', ?, ?, 'cancelled', 'strict', 'k1', "
                    "'{}', ?, 'local_worm_merkle', '2026-11-20T00:00:00Z')",
                    ("a" * 64, "b" * 64, "A" * 86 + "=="),
                )
        finally:
            con.close()


def test_model_pins_have_prices_and_cloud_embeddings():
    """T-UNIT-REG-29: model_pins.yaml pins cloud Gemini Neon/Carbon/Embedding with prices."""
    pins = yaml.safe_load((CONFIG / "model_pins.yaml").read_text(encoding="utf-8"))
    jobs = pins["jobs"]
    prices = pins["prices_usd_per_million_tokens"]

    assert jobs["embeddings"] == "gemini-embedding-001"
    assert {"gemini-4-neon", "gemini-4-carbon"} <= set(prices)
    for job_name, model_id in jobs.items():
        assert model_id in prices, f"jobs.{job_name}={model_id!r} missing from price table"
