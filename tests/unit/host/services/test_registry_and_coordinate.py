"""Unit and contract tests for Phase 3 Wave 3A (H3 Registry, O2 Release CLI, H4 K02/K06/P01)."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import jsonschema
import pytest

from dle.errors import ContractValidationError
from dle.host.services.coordinate import (
    evaluate_temporal_applicability,
    parse_atom,
    parse_coordinate,
    propose_anchors_from_query,
    resolve_jurisdiction_precedence,
)
from dle.host.services.registry import load_registry
from dle.store import RegistryRepository, open_stores
from dle.tools.registry_release import main as release_cli_main

REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTRY_DIR = REPO_ROOT / "config" / "registry"
PILOT_DIR = REPO_ROOT / "config" / "pilots" / "warehouse_substitution"
FIXTURE_REG_DIR = REPO_ROOT / "tests" / "fixtures" / "registry"
CONTRACTS_FN = REPO_ROOT / "contracts" / "functions"


def _validate_fn_contract(fn_name: str, direction: str, payload: dict[str, object]) -> None:
    schema = json.loads((CONTRACTS_FN / f"{fn_name}.{direction}.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=payload, schema=schema)


def _flatten_coordinate_atoms(coord_doc: dict[str, object]) -> list[str]:
    atoms: list[str] = []
    for key, val in coord_doc.items():
        if key.startswith("axis_") and key != "axis_13_temporal" and isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and isinstance(item.get("canonical_str"), str):
                    atoms.append(item["canonical_str"])
    return atoms


def test_h3_load_registry_production_pilot_fixture_guard_and_retired(tmp_path: Path) -> None:
    """T-UNIT-H3-01: Empty production JSONLs, D4 pilot, fixture guard, and retired exclusion."""
    prod_snap = load_registry(REGISTRY_DIR)
    assert len(prod_snap.pillars) >= 118
    assert len(prod_snap.sectors) == 20
    assert len(prod_snap.links) == 0
    assert prod_snap.resolve_pillar_alias("PL101") == ("PL020", True)
    assert prod_snap.resolve_pillar_alias("[PL:1.101.0.0]") == ("[PL:1.20.0.0]", True)

    with pytest.raises(ContractValidationError, match="fixture"):
        load_registry(REGISTRY_DIR, overlay_dir=FIXTURE_REG_DIR, allow_fixtures=False)

    pilot_snap = load_registry(REGISTRY_DIR, overlay_dir=PILOT_DIR, w3=1.5, w67=2.0)
    assert "[LINK:3.17]" in pilot_snap.links
    assert len(pilot_snap.branches) == 4
    assert len(pilot_snap.nodes) == 4
    assert "[HUB:6.7]" in pilot_snap.hubs
    assert "[MESH:7.9]" in pilot_snap.meshes
    assert "[JUR:12.1]" in pilot_snap.jurisdictions
    assert len(pilot_snap.intervals) == 4
    assert len(pilot_snap.spine_edges) > 0
    assert len(pilot_snap.manifest_sha256) == 64

    with pytest.raises(ValueError, match="strictly positive"):
        load_registry(REGISTRY_DIR, w3=0.0)

    # Retired record exclusion vs replay lookup.
    retired_dir = tmp_path / "retired_overlay"
    retired_dir.mkdir()
    (retired_dir / "axis4_branches.jsonl").write_text(
        json.dumps(
            {
                "branch_id": "[BR:4.1.27.99]",
                "root": "PL027",
                "parent": None,
                "label": "Deprecated wireless branch",
                "depth": 1,
                "status": "retired",
                "owner": "owner",
                "valid_from": "2020-01-01",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ret_snap = load_registry(REGISTRY_DIR, overlay_dir=retired_dir)
    assert "[BR:4.1.27.99]" not in ret_snap.branches
    assert "[BR:4.1.27.99]" in ret_snap.retired_ids
    assert ret_snap.is_known_atom("[BR:4.1.27.99]", include_retired=False) is False
    assert ret_snap.is_known_atom("[BR:4.1.27.99]", include_retired=True) is True


def test_registry_repository_and_cli_release_round_trip(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """T-UNIT-H3-02 & O2: Repository & release CLI persist unique active release."""
    db_dir = tmp_path / "db"
    code = release_cli_main(
        [
            "--registry-dir",
            str(REGISTRY_DIR),
            "--overlay-dir",
            str(PILOT_DIR),
            "--db-dir",
            str(db_dir),
            "--release-id",
            "rel-wh-pilot-001",
            "--approved-by",
            "warehouse-lead",
        ]
    )
    assert code == 0
    out_summary = json.loads(capsys.readouterr().out)
    assert out_summary["release_id"] == "rel-wh-pilot-001"
    assert out_summary["atom_count"] >= 150
    assert out_summary["edge_count"] > 0

    stores = open_stores(db_dir, enable_vec=False)
    try:
        repo = RegistryRepository(stores.registry)
        active = repo.get_active_release()
        assert active is not None
        assert active["release_id"] == "rel-wh-pilot-001"
        assert repo.get_release("rel-wh-pilot-001") is not None
        axis1 = repo.list_atoms("rel-wh-pilot-001", axis_id=1)
        assert any(a["canonical_str"] == "[PL:1.101.0.0]" and a["status"] == "alias" for a in axis1)
        assert len(repo.list_spine_edges("rel-wh-pilot-001")) == out_summary["edge_count"]
        assert len(repo.list_crosswalks("rel-wh-pilot-001", axis_id=3)) == 1

        # Second release flips is_active cleanly without violating unique partial index.
        snap = load_registry(REGISTRY_DIR, overlay_dir=PILOT_DIR)
        atoms, edges, cws = snap.to_db_rows()
        repo.publish_release(
            release_id="rel-wh-pilot-002",
            manifest_sha256=snap.manifest_sha256,
            created_utc="2026-11-22T23:00:00Z",
            approved_by="warehouse-lead",
            atoms=atoms,
            spine_edges=edges,
            crosswalks=cws,
            activate=True,
        )
        new_active = repo.get_active_release()
        assert new_active is not None and new_active["release_id"] == "rel-wh-pilot-002"
    finally:
        stores.close()


@pytest.mark.parametrize(
    "fixture_name",
    ["coordinate_warehouse.json", "coordinate_storage_procurement.json"],
)
def test_dvss_k02_coordinate_parsing_against_paper_fixtures(fixture_name: str) -> None:
    """T-UNIT-FN-K02-01..03: Coordinate parser matches 3.7.1 contract & paper §04b fixtures."""
    fx_snap = load_registry(REGISTRY_DIR, overlay_dir=FIXTURE_REG_DIR, allow_fixtures=True)
    raw_doc = json.loads((REPO_ROOT / "tests" / "fixtures" / fixture_name).read_text("utf-8"))
    anchors = _flatten_coordinate_atoms(raw_doc)
    raw_intervals = [
        json.loads(line)
        for line in (FIXTURE_REG_DIR / "axis13_intervals.jsonl").read_text("utf-8").splitlines()
        if line.strip() and '"status"' in line
    ]
    determined = [rec for rec in raw_intervals if rec.get("determination") != "unknown"][:1]

    is_warehouse = fixture_name == "coordinate_warehouse.json"
    in_payload = {
        "proposed_anchors": anchors,
        "registry_manifest_sha256": fx_snap.manifest_sha256,
        "as_of": "2026-06-01",
        "binding_claim": is_warehouse,
    }
    _validate_fn_contract("k02", "in", in_payload)

    res = parse_coordinate(
        proposed_anchors=anchors,
        snapshot=fx_snap,
        as_of=date(2026, 6, 1),
        temporal_records=determined,
        binding_claim=is_warehouse,
        allow_widen_instants=False,
        explicit_slot_states=raw_doc["slot_states"],
        explicit_jurisdiction_state=raw_doc["jurisdiction_state"],
    )
    assert res.uncertain_matches == ()
    assert res.coordinate["schema_version"] == "3.7.1"
    assert res.coordinate["jurisdiction_state"] == raw_doc["jurisdiction_state"]
    if is_warehouse:
        assert set(res.activated_roles) == {"scholar", "practitioner", "regulator", "harmonizer"}
        assert 1 in res.active_axes and 7 in res.active_axes and 13 in res.active_axes
    else:
        assert res.activated_roles == ("scholar",)
        assert res.active_axes == (1, 13)

    out_payload = {
        "coordinate": res.coordinate,
        "uncertain_matches": [
            {"raw_atom": u.raw_atom, "reason": u.reason} for u in res.uncertain_matches
        ],
        "active_axes": list(res.active_axes),
        "activated_roles": list(res.activated_roles),
        "open_dependencies": [
            {
                "axis_id": d.axis_id,
                "slot": d.slot,
                "reason": d.reason,
                "subject": d.subject,
            }
            for d in res.open_dependencies
        ],
    }
    _validate_fn_contract("k02", "out", out_payload)


def test_dvss_k02_aliases_uncertain_tmp_dependencies_and_anchor_proposer() -> None:
    """T-UNIT-FN-K02-04..06: Alias rewrite, A1 guard, TMP atoms, and binding dependencies."""
    pilot_snap = load_registry(REGISTRY_DIR, overlay_dir=PILOT_DIR)
    session_uuid = str(uuid.uuid4())
    unknown_iv = pilot_snap.intervals["[TIME:13.4]"]

    res = parse_coordinate(
        proposed_anchors=[
            "[PL:1.101.0.0]",  # Alias -> [PL:1.20.0.0]
            "[PL:1.27.1.0]",  # Invalid non-zero Axis 1 member (A1)
            "not-an-atom",
            f"[TMP:5.TMP.{session_uuid}]",
            "[HUB:6.7]",
            "[MESH:7.9]",
        ],
        snapshot=pilot_snap,
        as_of=date(2026, 6, 1),
        temporal_records=[unknown_iv],
        binding_claim=True,
        session_uuid=session_uuid,
    )
    assert ("[PL:1.101.0.0]", "[PL:1.20.0.0]") in res.alias_rewrites
    assert any(u.raw_atom == "[PL:1.27.1.0]" for u in res.uncertain_matches)
    assert any(u.raw_atom == "not-an-atom" for u in res.uncertain_matches)
    assert res.coordinate["jurisdiction_state"] == "unknown"
    assert res.coordinate["slot_states"]["axis_10_regulator"] == "unknown"  # type: ignore[index]
    assert res.coordinate["slot_states"]["axis_11_compliance"] == "unknown"  # type: ignore[index]
    dep_axes = {d.axis_id for d in res.open_dependencies}
    assert {10, 11, 12, 13} <= dep_axes
    assert "regulator" in res.activated_roles and "harmonizer" in res.activated_roles

    # Propose anchors for warehouse substitution query
    proposed = propose_anchors_from_query(
        "Replace Candidate A wireless access point with Candidate B in North warehouse switch",
        pilot_snap,
    )
    assert "[NODE:5.42]" in proposed
    assert "[JUR:12.1]" in proposed
    assert any(a.startswith("[PL:") for a in proposed)

    with pytest.raises(ValueError, match="Axis 1"):
        parse_atom("[PL:1.28.1.0]")


def test_dvss_k06_temporal_boundary_superseded_and_conflict() -> None:
    """T-UNIT-FN-K06-01..04: Half-open boundary, historical replay, unknown & overlap conflict."""
    pilot_snap = load_registry(REGISTRY_DIR, overlay_dir=PILOT_DIR)
    all_ivs = list(pilot_snap.intervals.values())

    in_payload = {"as_of": "2026-01-01", "intervals": all_ivs}
    _validate_fn_contract("k06", "in", in_payload)

    # 2025-06-01 historical query picks [TIME:13.1]
    res_2025 = evaluate_temporal_applicability(all_ivs, as_of=date(2025, 6, 1))
    assert [r["interval_id"] for r in res_2025.applicable] == ["[TIME:13.1]"]
    assert res_2025.has_unknown_dependency is True

    # 2026-01-01 boundary belongs exclusively to successor [TIME:13.2]
    res_boundary = evaluate_temporal_applicability(all_ivs, as_of=date(2026, 1, 1))
    assert [r["interval_id"] for r in res_boundary.applicable] == ["[TIME:13.2]"]

    # 2026-06-01 includes [TIME:13.2] and widened instant observation [TIME:13.3]
    res_2026 = evaluate_temporal_applicability(all_ivs, as_of=date(2026, 6, 1))
    app_ids = {r["interval_id"] for r in res_2026.applicable}
    assert app_ids == {"[TIME:13.2]", "[TIME:13.3]"}
    assert any(ex.reason == "unknown_valid_time" for ex in res_2026.excluded)
    _validate_fn_contract(
        "k06",
        "out",
        {
            "applicable": list(res_2026.applicable),
            "excluded": [
                {
                    "interval_id": e.interval_id,
                    "subject": e.subject,
                    "scope": e.scope,
                    "reason": e.reason,
                }
                for e in res_2026.excluded
            ],
            "conflicts": [],
        },
    )

    # Overlapping versions for same (subject, kind) produce explicit conflict error
    overlap_a = {
        "interval_id": "[TIME:13.91]",
        "subject": "[HUB:6.7]#purchase-clause",
        "claim_scope": "overlap-a",
        "kind": "effective",
        "granularity": "date",
        "start": "2026-01-01",
        "end": "2026-09-01",
        "time_zone": "UTC",
        "determination": "stated",
        "recorded_at": "2026-11-20T00:00:00Z",
        "status": "verified",
    }
    overlap_b = {
        **overlap_a,
        "interval_id": "[TIME:13.92]",
        "claim_scope": "overlap-b",
        "start": "2026-06-01",
        "end": "2027-01-01",
    }
    conflict_res = evaluate_temporal_applicability([overlap_a, overlap_b], as_of=date(2026, 7, 1))
    assert len(conflict_res.conflicts) == 1
    assert conflict_res.applicable == ()


def test_dvss_p01_jurisdiction_precedence_and_conflict() -> None:
    """T-UNIT-FN-P01-01..03: Authority hierarchy, filtering, and equal-rank conflict detection."""
    pilot_snap = load_registry(REGISTRY_DIR, overlay_dir=PILOT_DIR)
    jur = pilot_snap.jurisdictions["[JUR:12.1]"]
    hub_arms = [
        {
            "arm_id": "site-arm",
            "authority": "North warehouse site owner",
            "nexus_kind": "site_owner",
            "citation": "Site Plan §5",
            "relation": "requires",
            "jurisdiction": "US-CA",
            "valid_from": "2026-01-01",
        },
        {
            "arm_id": "fed-arm",
            "authority": "OSHA",
            "nexus_kind": "federal_agency",
            "citation": "29 CFR 1910",
            "relation": "requires",
            "jurisdiction": "US",
            "valid_from": "2026-01-01",
        },
        {
            "arm_id": "tx-arm",
            "authority": "Texas State Agency",
            "nexus_kind": "state_agency",
            "citation": "TX-01",
            "relation": "permits",
            "jurisdiction": "US-TX",
            "valid_from": "2026-01-01",
        },
        {
            "arm_id": "unscoped-arm",
            "authority": "Buyer",
            "citation": "Clause 14.2",
            "relation": "requires",
            "jurisdiction": "unscoped",
        },
    ]

    _validate_fn_contract(
        "p01",
        "in",
        {
            "as_of": "2026-06-01",
            "jurisdiction_record": jur,
            "hub_arms": hub_arms,
            "binding_claim": True,
        },
    )

    res = resolve_jurisdiction_precedence(
        jurisdiction_record=jur,
        hub_arms=hub_arms,
        as_of=date(2026, 6, 1),
        hub_id="[HUB:6.7]",
        binding_claim=True,
    )
    assert res.jurisdiction_state == "specified"
    assert [a.arm_id for a in res.ordered_arms] == ["fed-arm", "site-arm", "unscoped-arm"]
    assert res.excluded_arms == (("tx-arm", "jurisdiction_mismatch:US-TX"),)
    assert res.review_items == ()

    # Equal precedence permits vs prohibits conflict opens review item
    conflicting = [
        {
            "arm_id": "state-allow",
            "authority": "CA Dept",
            "nexus_kind": "state_agency",
            "citation": "CA-1",
            "relation": "permits",
            "jurisdiction": "US-CA",
        },
        {
            "arm_id": "state-deny",
            "authority": "CA Board",
            "nexus_kind": "state_agency",
            "citation": "CA-2",
            "relation": "prohibits",
            "jurisdiction": "US-CA",
        },
    ]
    res_conflict = resolve_jurisdiction_precedence(
        jurisdiction_record=jur,
        hub_arms=conflicting,
        as_of=date(2026, 6, 1),
        binding_claim=True,
    )
    assert len(res_conflict.review_items) == 1
    assert res_conflict.review_items[0].reason == "equal_precedence_authority_conflict"

    _validate_fn_contract(
        "p01",
        "out",
        {
            "jurisdiction_state": res_conflict.jurisdiction_state,
            "ordered_arms": [
                {
                    "arm_id": a.arm_id,
                    "authority": a.authority,
                    "nexus_kind": a.nexus_kind,
                    "rank": a.rank,
                    "relation": a.relation,
                    "citation": a.citation,
                    "jurisdiction": a.jurisdiction,
                }
                for a in res_conflict.ordered_arms
            ],
            "excluded_arms": [
                {"arm_id": arm_id, "reason": reason}
                for arm_id, reason in res_conflict.excluded_arms
            ],
            "review_items": [
                {"reason": r.reason, "arm_ids": list(r.arm_ids)} for r in res_conflict.review_items
            ],
        },
    )
