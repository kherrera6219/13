"""Migrated 21-test §18 / Appendix G DVSS acceptance suite (P1-20, FR-FN-01, FR-RCPT-03)."""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import jsonschema
import pytest

from dle.config import load_config
from dle.errors import ContractValidationError
from dle.host.functions import FunctionRegistry, register_phase1_functions
from dle.host.services.pilot import (
    CoordinateResolver,
    DriftMonitor,
    PilotClaim,
    PilotObjection,
    PilotPassage,
    PilotPipeline,
    RetryAttemptInput,
    calibrate_crc,
    compute_nonconformity,
    load_coordinate_schema,
    pack_hydrated,
    ppr,
)
from dle.temporal import Interval

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "contracts"
FIXTURES = REPO_ROOT / "tests" / "fixtures"


def _make_pipeline(*, mu_0: float = 0.05, drift_lambda: float = 0.25) -> PilotPipeline:
    cfg = load_config(REPO_ROOT / "config")
    reg = FunctionRegistry(cfg.functions, cfg.profiles)
    register_phase1_functions(reg, cfg.notices)
    reg.self_check()
    return PilotPipeline(
        function_registry=reg,
        policy_sha256=cfg.policy_sha256,
        drift_monitor=DriftMonitor(mu_0=mu_0, drift_lambda=drift_lambda),
    )


def _good_claim(
    claim_id: str = "c1",
    *,
    binding: bool = False,
    p: float = 1.0,
    e: float = 0.99,
) -> PilotClaim:
    return PilotClaim(
        claim_id=claim_id,
        proposal_id="B/1",
        assertion="All constraints satisfied.",
        binding=binding,
        scope="default",
        passage_ids=("src-pilot-1@2026-01#s1",),
        provenance=p,
        entailment=e,
        belief=0.99,
    )


def test_01_duplicate_address_and_registry():
    """§18 F1: duplicate address keeps distinct records; ambiguous address requires version."""
    resolver = CoordinateResolver(load_coordinate_schema(REPO_ROOT))
    resolver.register_record("[NODE:5.42]", "rec-a", registry_version="v1")
    resolver.register_record("[NODE:5.42]", "rec-b", registry_version="v1")
    assert [r.record_id for r in resolver.lookup("[NODE:5.42]")] == ["rec-a", "rec-b"]

    with pytest.raises(ContractValidationError, match="registry_version"):
        resolver.register_record("[LEGACY:5.10]", "rec-legacy", is_ambiguous=True)
    resolver.register_record(
        "[LEGACY:5.10]", "rec-legacy-v2", is_ambiguous=True, registry_version="2026.2"
    )
    assert len(resolver.lookup("[LEGACY:5.10]", registry_version="2026.2")) == 1


def test_02_sector_codes_preserve_native_strings():
    """§18 F2: native codes with leading zeros and letters round-trip through surrogate map."""
    resolver = CoordinateResolver(load_coordinate_schema(REPO_ROOT))
    for native in ("01", "08", "31-33", "48-49A"):
        surrogate = resolver.register_sector(native)
        assert resolver.resolve_sector(surrogate) == native


def test_03_unique_temporary_nodes_and_provenance():
    """§18 F3: two TMP nodes in one session get unique IDs and are non-authoritative."""
    resolver = CoordinateResolver(load_coordinate_schema(REPO_ROOT))
    sess = "11111111-1111-4111-8111-111111111111"
    t1 = resolver.create_temp_node(sess)
    t2 = resolver.create_temp_node(sess)
    assert t1["node_uuid"] != t2["node_uuid"]
    assert t1["canonical_str"] != t2["canonical_str"]
    assert t1["authoritative"] is False and t2["authoritative"] is False


def test_04_root_and_empty_anchors():
    """§18 F4: single root gets unit mass; empty usable seeds trigger hard hold."""
    scores, _iters = ppr({}, {"root": 1.0})
    assert scores["root"] == pytest.approx(1.0)

    pipe = _make_pipeline()
    res = pipe.execute(
        profile="strict",
        cutoff=0.08,
        triage_input={"d": 0, "r": 0, "m": 0},
        attempts_plan=[RetryAttemptInput(claims=())],
        has_usable_seeds=False,
    )
    assert res.api_release_mode == "held"
    assert res.receipt_release_mode == "hard_veto_block"


def test_05_hydration_limits():
    """§18 F5: post-hydration packing enforces 250 vertices, edges, tokens, and 4 hops."""
    base = [(f"n-{i:03d}", 1.0 / (i + 1), 1, 2, 10) for i in range(240)]
    hydrated = [(f"h-{i:03d}", 0.5 / (i + 1), 2, 2, 10) for i in range(35)]
    retained = pack_hydrated([*base, *hydrated])
    assert len(retained) == 250
    over_hop = pack_hydrated([("too-far", 1.0, 5, 1, 10)])
    assert over_hop == []


def test_06_historical_scope():
    """§18 F6: past scope retains expired clause effective during that historical period."""
    resolver = CoordinateResolver(load_coordinate_schema(REPO_ROOT))
    old_clause = PilotPassage(
        passage_id="c-2023@1#s1",
        source_id="c-2023",
        revision="1",
        locator="s1",
        text="Legacy clause",
        interval=Interval(date(2023, 1, 1), date(2024, 1, 1), "date"),
        scope="historical",
    )
    renewal = PilotPassage(
        passage_id="c-2026@1#s1",
        source_id="c-2026",
        revision="1",
        locator="s1",
        text="Current renewal",
        interval=Interval(date(2026, 1, 1), None, "date"),
        scope="renewal",
    )
    hits_2023 = resolver.filter_by_scope(
        [old_clause, renewal], Interval(date(2023, 6, 1), date(2023, 7, 1), "date")
    )
    assert [p.passage_id for p in hits_2023] == ["c-2023@1#s1"]


def test_07_binding_escalates_once():
    """§18 F8: Tier 1 binding draft escalates once with Regulator active."""
    pipe = _make_pipeline()
    res = pipe.execute(
        profile="strict",
        cutoff=0.08,
        triage_input={"d": 0, "r": 0, "m": 0, "binding": False},
        attempts_plan=[
            RetryAttemptInput(
                claims=(_good_claim(binding=True),),
                draft_text="Binding obligation applies.",
            )
        ],
    )
    assert len(res.attempts) == 2
    assert res.attempts[0]["event"] == "initial"
    assert res.attempts[1]["event"] == "tier_escalation"
    assert res.attempts[1]["tier"] >= 2
    assert 10 in res.attempts[1]["role_calls"][0]["role_axes"]


def test_08_retry_independent_of_cutoff():
    """§18 F13: cutoff choice never alters retry trajectory or terminal candidate."""
    plan = [
        RetryAttemptInput(
            claims=(_good_claim(p=0.95, e=0.95),),
            recoverable_gap="missing_annex",
            authorized_next_source="src-annex-2",
            draft_text="Draft pass 0",
        ),
        RetryAttemptInput(
            claims=(_good_claim(p=1.0, e=0.98),),
            draft_text="Draft pass 1 with annex",
        ),
    ]
    res_loose = _make_pipeline().execute(
        profile="strict", cutoff=0.15, triage_input={"d": 1, "r": 0, "m": 0}, attempts_plan=plan
    )
    res_strict = _make_pipeline().execute(
        profile="strict", cutoff=0.01, triage_input={"d": 1, "r": 0, "m": 0}, attempts_plan=plan
    )
    assert len(res_loose.attempts) == 2 and len(res_strict.attempts) == 2
    assert res_loose.terminal_attempt_id == res_strict.terminal_attempt_id
    assert res_loose.terminal_u == pytest.approx(res_strict.terminal_u)


def test_09_empty_claims_and_unresolved_veto():
    """§18 F14: empty claim set or unresolved blocking objection causes hard hold."""
    pipe = _make_pipeline()
    res_empty = pipe.execute(
        profile="strict",
        cutoff=0.5,
        triage_input={"d": 0, "r": 0, "m": 0},
        attempts_plan=[RetryAttemptInput(claims=())],
    )
    assert res_empty.api_release_mode == "held"

    res_veto = pipe.execute(
        profile="strict",
        cutoff=0.5,
        triage_input={"d": 1, "r": 1, "m": 1},
        attempts_plan=[
            RetryAttemptInput(
                claims=(_good_claim(),),
                new_objections=(
                    PilotObjection(
                        objection_id="R1",
                        role_axis=10,
                        proposal_id="B/1",
                        blocking=True,
                        predicate="missing signed authorization",
                        state="open",
                    ),
                ),
            )
        ],
    )
    assert res_veto.api_release_mode == "held"
    assert res_veto.receipt["payload"]["decision"]["hard_gate"] is False


def test_10_drift_updates_once_and_controls_release():
    """§18 F15: CUSUM updates once per terminal run and latches subsequent strict runs."""
    pipe = _make_pipeline(mu_0=0.02, drift_lambda=0.01)
    # Force nonconformity above mu_0 + delta + lambda = 0.05 via weak entailment
    r1 = pipe.execute(
        profile="strict",
        cutoff=0.50,
        triage_input={"d": 0, "r": 0, "m": 0},
        attempts_plan=[RetryAttemptInput(claims=(_good_claim(p=0.85, e=0.80),), draft_text="ok")],
    )
    assert pipe.drift.is_latched is True
    assert r1.api_release_mode == "held"
    assert r1.receipt_release_mode == "review_required"


def test_11_tampering_and_missing_anchor():
    """§18 F17: modified returned text or missing anchor fails receipt verification."""
    pipe = _make_pipeline()
    res = pipe.execute(
        profile="strict",
        cutoff=0.20,
        triage_input={"d": 0, "r": 0, "m": 0},
        attempts_plan=[RetryAttemptInput(claims=(_good_claim(),), draft_text="Clean output.")],
    )
    assert pipe.sealer.verify(res.receipt, res.returned_text) is True
    assert pipe.sealer.verify(res.receipt, "Tampered output.") is False

    pending = pipe.execute(
        profile="strict",
        cutoff=0.20,
        triage_input={"d": 0, "r": 0, "m": 0},
        attempts_plan=[RetryAttemptInput(claims=(_good_claim(),), draft_text="Clean output.")],
        inclusion_proof_ref=None,
    )
    assert pipe.sealer.verify(pending.receipt, pending.returned_text, require_anchor=True) is False


def test_12_slot_states_order_and_duplicates():
    """§18 F12: rejects duplicate atoms and slots omitting both atoms and explicit state."""
    resolver = CoordinateResolver(load_coordinate_schema(REPO_ROOT))
    valid_coord = json.loads((FIXTURES / "coordinate_warehouse.json").read_text(encoding="utf-8"))
    resolver.validate_coordinate(valid_coord)

    dup_coord = copy.deepcopy(valid_coord)
    dup_coord["axis_2_sectors"].append(dup_coord["axis_2_sectors"][0])
    with pytest.raises(ContractValidationError):
        resolver.validate_coordinate(dup_coord)

    missing_slot = copy.deepcopy(valid_coord)
    del missing_slot["slot_states"]["axis_4_branches"]
    with pytest.raises(ContractValidationError):
        resolver.validate_coordinate(missing_slot)


def test_13_router_floors_and_risk_hit():
    """§18 F7: failure-centroid Z hit forces Tier 3 and all four roles even when S = 0."""
    pipe = _make_pipeline()
    res = pipe.execute(
        profile="strict",
        cutoff=0.20,
        triage_input={"d": 0, "r": 0, "m": 0, "binding": False, "z_hit": True},
        attempts_plan=[RetryAttemptInput(claims=(_good_claim(),))],
    )
    assert res.attempts[0]["tier"] == 3
    assert set(res.attempts[0]["role_calls"][0]["role_axes"]) == {8, 9, 10, 11}


def test_14_tier1_objection_carried_on_escalation():
    """§18 F9: objection opened in Tier 1 carries forward across binding escalation."""
    pipe = _make_pipeline()
    res = pipe.execute(
        profile="strict",
        cutoff=0.20,
        triage_input={"d": 0, "r": 0, "m": 0},
        attempts_plan=[
            RetryAttemptInput(
                claims=(_good_claim(binding=True),),
                new_objections=(
                    PilotObjection(
                        objection_id="H1",
                        role_axis=11,
                        proposal_id="B/1",
                        blocking=True,
                        predicate="acceptance schedule required",
                        state="open",
                    ),
                ),
            )
        ],
    )
    assert len(res.attempts) == 2
    assert any(
        o["objection_id"] == "H1" and o["state"] == "open" for o in res.attempts[1]["objections"]
    )
    assert res.api_release_mode == "held"


def test_15_binding_claim_activates_regulator():
    """§18 F10: Tier 2 binding draft without Regulator escalates with Regulator active."""
    pipe = _make_pipeline()
    res = pipe.execute(
        profile="strict",
        cutoff=0.20,
        triage_input={"d": 1, "r": 1, "m": 1, "binding": False},
        attempts_plan=[RetryAttemptInput(claims=(_good_claim(binding=True),))],
    )
    assert len(res.attempts) == 2
    assert 10 not in res.attempts[0]["role_calls"][0]["role_axes"]
    assert 10 in res.attempts[1]["role_calls"][0]["role_axes"]


def test_16_blocking_objection_first_seen_closed():
    """§18 F11: blocking objection first appearing closed stays open without verifier evidence."""
    pipe = _make_pipeline()
    res = pipe.execute(
        profile="strict",
        cutoff=0.50,
        triage_input={"d": 0, "r": 0, "m": 0},
        attempts_plan=[
            RetryAttemptInput(
                claims=(_good_claim(),),
                new_objections=(
                    PilotObjection(
                        objection_id="R2",
                        role_axis=10,
                        proposal_id="B/1",
                        blocking=True,
                        predicate="unverified assertion of waiver",
                        state="closed",
                        closure_evidence=(),
                        verifier_closed=False,
                    ),
                ),
            )
        ],
    )
    assert res.attempts[0]["objections"][0]["state"] == "open"
    assert res.api_release_mode == "held"


def test_17_warnings_are_in_the_hashed_response():
    """§18 F16: advisory release under latched drift includes warning inside response hash."""
    pipe = _make_pipeline(mu_0=0.01, drift_lambda=0.005)
    pipe.drift.is_latched = True
    res = pipe.execute(
        profile="advisory",
        cutoff=0.50,
        triage_input={"d": 0, "r": 0, "m": 0},
        attempts_plan=[
            RetryAttemptInput(claims=(_good_claim(),), draft_text="Core advisory text.")
        ],
        drift_updates_override=True,
    )
    assert res.api_release_mode == "released_advisory"
    assert res.receipt_release_mode == "annotated_release_drift_warning"
    assert "recalibrated" in res.returned_text
    assert pipe.sealer.verify(res.receipt, res.returned_text) is True
    assert pipe.sealer.verify(res.receipt, "Core advisory text.") is False


def test_18_local_anchoring_profile():
    """§18 F18: local_worm_merkle profile reports verification_level='locally_sealed'."""
    pipe = _make_pipeline()
    res = pipe.execute(
        profile="strict",
        cutoff=0.20,
        triage_input={"d": 0, "r": 0, "m": 0},
        attempts_plan=[RetryAttemptInput(claims=(_good_claim(),), draft_text="Sealed answer.")],
        anchoring_profile="local_worm_merkle",
    )
    assert res.receipt["envelope"]["verification_level"] == "locally_sealed"


def test_crc_finite_sample_threshold():
    """§16b CRC check: n=300, alpha=0.01 with losses 0, 2, 3 selects middle threshold."""
    selected = calibrate_crc(
        [(0.04, 0.0), (0.08, 2.0), (0.12, 3.0)],
        n_cal=300,
        alpha=0.01,
    )
    assert selected == 0.08


def test_ppr_two_nodes():
    """§06 PageRank check: deterministic two-node graph converges cleanly within 80 iterations."""
    adj = {"a": [("b", 1.0)], "b": [("a", 1.0)]}
    scores, iters = ppr(adj, {"a": 1.0}, damping=0.85, max_iterations=80, tolerance=1.76e-6)
    assert 1 <= iters <= 80
    assert scores["a"] + scores["b"] == pytest.approx(1.0)
    assert scores["a"] > scores["b"] > 0.4


def test_terminal_score_example():
    """§16a worked example: u = 0.0547 (d = 0) and u = 0.1297 (d = 0.5)."""
    c1 = PilotClaim("c1", "P1", "clause", True, "s", ("p1",), 0.95, 0.972, belief=0.9359)
    c2 = PilotClaim("c2", "P1", "statute", True, "s", ("p2",), 1.00, 0.990, belief=0.9753)
    c3 = PilotClaim("c3", "P1", "defn", False, "s", ("p3",), 1.00, 0.9666, belief=0.9900)

    u_clean, ok = compute_nonconformity(
        [c1, c2, c3],
        [{"state": "closed"}, {"state": "closed"}],
    )
    assert ok is True
    assert u_clean == pytest.approx(0.0547, abs=1e-4)

    u_open, _ = compute_nonconformity(
        [c1, c2, c3],
        [{"state": "open"}, {"state": "closed"}],
    )
    assert u_open == pytest.approx(0.1297, abs=1e-4)


def test_pilot_receipts_validate_schema_3_8_0_and_zero_ka_ids_in_dle():
    """P1-20 gate: pilot receipts match 3.8.0 schema with K10/K11/K12 records; zero KA-0 in dle/."""
    pipe = _make_pipeline()
    res = pipe.execute(
        profile="strict",
        cutoff=0.20,
        triage_input={"d": 0, "r": 0, "m": 0},
        attempts_plan=[
            RetryAttemptInput(claims=(_good_claim(binding=True),), draft_text="Sealed.")
        ],
    )

    receipt_schema = json.loads((CONTRACTS / "receipt.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        receipt_schema, format_checker=jsonschema.FormatChecker()
    )
    errors = sorted(validator.iter_errors(res.receipt), key=str)
    assert not errors, f"Receipt validation error: {errors[0].message}"

    invoked_ids = {rec["dvss_id"] for rec in res.receipt["payload"]["function_invocations"]}
    assert {"DVSS-K10", "DVSS-K11", "DVSS-K12"} <= invoked_ids
    assert len(res.receipt["payload"]["function_invocations"]) >= 12

    ka_prefix = "KA-" + "0"
    for py_path in sorted((REPO_ROOT / "dle").rglob("*.py")):
        assert ka_prefix not in py_path.read_text(encoding="utf-8"), (
            f"Found legacy KA-0 in {py_path}"
        )
