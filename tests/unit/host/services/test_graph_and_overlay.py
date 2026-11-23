"""Unit and contract tests for Phase 3 Wave 3B (H6 DVSS-K07/P06 and H7 DVSS-P03 USKD overlay)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import jsonschema
import pytest

from dle.host.services.graph import (
    align_crosswalk_terms,
    effective_hop_budget,
    expand_bounded_ppr,
)
from dle.host.services.overlay import MAX_BRANCH_DEPTH, SessionOverlay, can_cite_as_evidence
from dle.host.services.registry import SpineEdge, load_registry

REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTRY_DIR = REPO_ROOT / "config" / "registry"
PILOT_DIR = REPO_ROOT / "config" / "pilots" / "warehouse_substitution"
CONTRACTS_FN = REPO_ROOT / "contracts" / "functions"


def _validate_fn_contract(fn_name: str, direction: str, payload: dict[str, object]) -> None:
    schema = json.loads((CONTRACTS_FN / f"{fn_name}.{direction}.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=payload, schema=schema)


def test_dvss_p03_session_overlay_bounds_evidence_and_clear() -> None:
    """T-UNIT-FN-P03-01..04: Depth <= 7, TMP IDs never citeable as evidence, clear_on_seal."""
    sid = str(uuid.uuid4())
    overlay = SessionOverlay(sid)

    branch_node = overlay.add_branch_candidate(
        label="PoE switch bank check",
        parent_atom="[PL:1.27.0.0]",
        depth=MAX_BRANCH_DEPTH,
        via_links=["[LINK:3.17]"],
    )
    assert branch_node.canonical_str.startswith("[TMP:5.TMP.")
    assert branch_node.is_hypothesis is True
    assert branch_node.status == "synthetic_derived"
    assert can_cite_as_evidence(branch_node.canonical_str) is False
    assert can_cite_as_evidence("[NODE:5.42]") is True

    hyp = overlay.synthesize_hypothesis(
        label="Candidate B exceeds PoE per-port limit",
        anchor_atoms=["[NODE:5.42]", "[NODE:5.43]"],
        via_links=["[LINK:3.17]"],
    )
    assert len(overlay.list_nodes()) == 2
    assert len(overlay.overlay_edges()) >= 4

    in_payload = {
        "session_uuid": sid,
        "label": hyp.label,
        "anchor_atoms": list(hyp.anchor_atoms),
        "depth": 1,
        "via_links": list(hyp.via_links),
    }
    _validate_fn_contract("p03", "in", in_payload)
    _validate_fn_contract(
        "p03",
        "out",
        {
            "canonical_str": hyp.canonical_str,
            "is_hypothesis": True,
            "citeable_as_evidence": can_cite_as_evidence(hyp.canonical_str),
            "status": hyp.status,
            "depth": hyp.depth,
        },
    )

    with pytest.raises(ValueError, match="depth"):
        overlay.add_branch_candidate(label="too deep", parent_atom="[PL:1.27.0.0]", depth=8)

    cleared = overlay.clear_on_seal()
    assert cleared == 2
    assert overlay.list_nodes() == ()
    assert overlay.overlay_edges() == ()


def test_dvss_k07_deterministic_ppr_and_hop_budgets() -> None:
    """T-UNIT-FN-K07-01..03: Determinism, convergence, Tier/retry hops <= 4, warehouse pilot."""
    pilot_snap = load_registry(REGISTRY_DIR, overlay_dir=PILOT_DIR, w3=1.0, w67=1.0)
    assert effective_hop_budget(tier=1, retry_count=0) == 1
    assert effective_hop_budget(tier=2, retry_count=0) == 2
    assert effective_hop_budget(tier=2, retry_count=1) == 3
    assert effective_hop_budget(tier=3, retry_count=2) == 4
    assert effective_hop_budget(tier=3, retry_count=5) == 4

    in_payload = {
        "anchors": ["[NODE:5.42]", "[PL:1.28.0.0]"],
        "tier": 2,
        "retry_count": 0,
        "damping": 0.85,
        "max_iterations": 80,
        "tolerance": 1.76e-6,
        "max_vertices": 250,
    }
    _validate_fn_contract("k07", "in", in_payload)

    res1 = expand_bounded_ppr(
        anchors=["[NODE:5.42]", "[PL:1.28.0.0]"],
        snapshot=pilot_snap,
        tier=2,
        retry_count=0,
    )
    res2 = expand_bounded_ppr(
        anchors=["[NODE:5.42]", "[PL:1.28.0.0]"],
        snapshot=pilot_snap,
        tier=2,
        retry_count=0,
    )
    assert res1.graph_sha256 == res2.graph_sha256
    assert res1.converged is True
    assert 1 <= res1.ppr_iterations <= 80
    assert res1.effective_hops == 2

    v_ids = {v.vertex_id for v in res1.vertices}
    assert "[NODE:5.42]" in v_ids
    assert "[NODE:5.43]" in v_ids
    assert "[HUB:6.7]" in v_ids
    assert "[MESH:7.9]" in v_ids

    out_payload = {
        "vertices": [
            {
                "vertex_id": v.vertex_id,
                "axis_id": v.axis_id,
                "score": v.score,
                "hop": v.hop,
                "distance": v.distance,
                "synthetic": v.synthetic,
                "token_cost": v.token_cost,
            }
            for v in res1.vertices
        ],
        "edges": [
            {
                "src": e.src,
                "dst": e.dst,
                "edge_type": e.edge_type,
                "weight": e.weight,
                "predicate": e.predicate,
            }
            for e in res1.edges
        ],
        "ppr_iterations": res1.ppr_iterations,
        "converged": res1.converged,
        "effective_hops": res1.effective_hops,
        "graph_sha256": res1.graph_sha256,
        "pruned_count": res1.pruned_count,
        "reserved_synthetic_used": res1.reserved_synthetic_used,
    }
    _validate_fn_contract("k07", "out", out_payload)


def test_dvss_k07_caps_synthetic_reservation_and_weights(tmp_path: Path) -> None:
    """T-UNIT-FN-K07-04..06: <= 250 cap, token/edge budget, reserved TMP slots, w3 weighting."""
    pilot_snap = load_registry(REGISTRY_DIR, overlay_dir=PILOT_DIR, w3=2.0, w67=1.0)
    overlay = SessionOverlay("sess-p3-reserve")
    tmp_node = overlay.synthesize_hypothesis(
        label="Ephemeral capacity probe",
        anchor_atoms=["[NODE:5.42]"],
    )

    tight = expand_bounded_ppr(
        anchors=["[NODE:5.42]"],
        snapshot=pilot_snap,
        tier=2,
        overlay=overlay,
        max_vertices=3,
        max_edges=2,
        max_tokens=200,
        reserved_synthetic_slots=2,
    )
    assert len(tight.vertices) <= 3
    assert len(tight.edges) <= 2
    assert tight.reserved_synthetic_used == 1
    assert any(v.vertex_id == tmp_node.canonical_str and v.synthetic for v in tight.vertices)
    assert tight.pruned_count > 0

    # Synthetic wide graph > 250 vertices still hard-capped at 250.
    many_edges = tuple(
        SpineEdge(src="[PL:1.27.0.0]", dst=f"[NODE:5.{i}]", edge_type="node_anchor", weight=1.0)
        for i in range(100, 390)
    )
    large_snap = type(pilot_snap)(
        manifest_sha256=pilot_snap.manifest_sha256,
        pillars=pilot_snap.pillars,
        pillars_by_id=pilot_snap.pillars_by_id,
        pillar_aliases=pilot_snap.pillar_aliases,
        sectors=pilot_snap.sectors,
        sectors_by_id=pilot_snap.sectors_by_id,
        naics_crosswalk=pilot_snap.naics_crosswalk,
        links=pilot_snap.links,
        branches=pilot_snap.branches,
        nodes=pilot_snap.nodes,
        hubs=pilot_snap.hubs,
        meshes=pilot_snap.meshes,
        jurisdictions=pilot_snap.jurisdictions,
        intervals=pilot_snap.intervals,
        all_records_by_id=pilot_snap.all_records_by_id,
        retired_ids=pilot_snap.retired_ids,
        spine_edges=many_edges,
        crosswalks=pilot_snap.crosswalks,
    )
    capped = expand_bounded_ppr(
        anchors=["[PL:1.27.0.0]"],
        snapshot=large_snap,
        tier=2,
        max_vertices=300,  # Should be clamped cleanly at <= 250 per spec
        max_tokens=100_000,
    )
    assert len(capped.vertices) == 250


def test_dvss_p06_crosswalk_alignment_and_tensions() -> None:
    """T-UNIT-FN-P06-01..02: Groups overlaps/equivalences while preserving conflicts/depends_on."""
    pilot_snap = load_registry(REGISTRY_DIR, overlay_dir=PILOT_DIR)
    atoms = ["[NODE:5.42]", "[NODE:5.43]", "[HUB:6.7]", "[MESH:7.9]"]
    _validate_fn_contract("p06", "in", {"atoms": atoms})

    aligned = align_crosswalk_terms(atoms=atoms, snapshot=pilot_snap)
    assert any(
        "[HUB:6.7]#purchase-clause" in grp.related_atoms and "overlaps" in grp.relations
        for grp in aligned.groups
    )
    assert any(item.relation == "depends_on" for item in aligned.unresolved)

    _validate_fn_contract(
        "p06",
        "out",
        {
            "groups": [
                {
                    "canonical_atom": g.canonical_atom,
                    "related_atoms": list(g.related_atoms),
                    "relations": list(g.relations),
                }
                for g in aligned.groups
            ],
            "unresolved": [
                {
                    "from_atom": u.from_atom,
                    "to_atom": u.to_atom,
                    "relation": u.relation,
                    "reason": u.reason,
                }
                for u in aligned.unresolved
            ],
        },
    )
