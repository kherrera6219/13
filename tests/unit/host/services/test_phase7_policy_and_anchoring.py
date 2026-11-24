"""Unit and contract tests for Phase 7 Wave 7A: DVSS-P05, DVSS-P09, 52 contracts, anchoring."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from dle.config import canonicalize_jcs, load_config
from dle.edge.tools import ToolBridge
from dle.edge.translator import translate_generate_request
from dle.errors import AnchorPendingError, ContractValidationError
from dle.host.functions import FunctionRegistry, register_phase1_functions
from dle.host.services.analogy import generate_cross_domain_analogies
from dle.host.services.anchoring import (
    CustomerHostedLogAnchor,
    ExternalTransparencyLogAnchor,
    LocalWormMerkleAnchor,
)
from dle.host.services.claim_extractor import ClaimExtractor
from dle.host.services.evidence import EvidenceService
from dle.host.services.overlay import SessionTmpNode, can_cite_as_evidence
from dle.host.services.promotion import stage_quarantined_nodes
from dle.host.services.receipts import Ed25519KeyManager, ReceiptSealer
from dle.host.services.registry import load_registry
from dle.host.services.verifier import ClaimVerifier
from dle.host.workflow import DEFAULT_PHASE2_CALIBRATION, run_governed_workflow
from dle.models import DeterministicLexicalNliScorer, EmbeddingService, FakeModel, ModelRegistry
from dle.store import (
    EvidenceRepository,
    OpsRepository,
    ReceiptRepository,
    RegistryRepository,
    SessionRepository,
    open_stores,
)
from dle.tools.verify_receipt import verify_bundle_zip, verify_signed_receipt

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "config"
PILOT_DIR = CONFIG_DIR / "pilots" / "warehouse_substitution"


def _minimal_receipt_payload(*, run_id: str, utc_iso: str, profile: str) -> dict[str, object]:
    return {
        "schema_version": "3.8.0",
        "run_id": run_id,
        "utc": utc_iso,
        "chain_id": "main",
        "previous_hash": "0" * 64,
        "coordinate_manifest_sha256": "0" * 64,
        "policy_sha256": "1" * 64,
        "verifier_version": "1.0.0",
        "profile": profile,
        "sources": [],
        "attempts": [
            {
                "attempt_id": "att-0",
                "parent_id": None,
                "event": "initial",
                "reason": "baseline",
                "tier": 1,
                "hops": 1,
                "ppr_iterations": 1,
                "vertices_retained": 1,
                "graph_sha256": "2" * 64,
                "source_manifest_sha256": "0" * 64,
                "role_calls": [],
                "claims": [],
                "objections": [],
                "candidate_sha256": "3" * 64,
            }
        ],
        "calibration": {
            "artifact_id": "cal-phase6-v1",
            "artifact_sha256": "4" * 64,
            "n_cal": 100,
            "alpha": 0.05,
            "threshold": 0.29,
            "mu_0": 0.275692,
            "drift_lambda": 3.3624,
            "drift_delta": 0.02,
        },
        "decision": {
            "hard_gate": True,
            "drift_latched": False,
            "cusum": 0.0,
            "terminal_u": 0.05,
            "terminal_attempt_id": "att-0",
            "release_mode": "gate_passed",
            "profile": profile,
        },
        "response_sha256": "5" * 64,
        "function_invocations": [
            {
                "dvss_id": f"DVSS-K{idx:02d}",
                "version": "1.0.0",
                "attempt_id": "att-0",
                "seq": idx - 1,
                "level": "kernel",
                "implementation": "host",
                "input_sha256": "6" * 64,
                "output_sha256": "7" * 64,
                "outcome": "ok",
                "duration_ms": 0.1,
            }
            for idx in range(1, 13)
        ],
    }


def test_p05_quarantined_promotion_staging_and_live_registry_guard(tmp_path: Path) -> None:
    """T-UNIT-FN-P05-01..03: P05 stages valid TMP nodes with JCS digest and never touches live."""
    valid_node = SessionTmpNode(
        canonical_str="[TMP:5.TMP.11111111-1111-1111-1111-111111111111]",
        session_uuid="sess-abc-1234",
        node_uuid="11111111-1111-1111-1111-111111111111",
        label="Proposed cross-dock staging bay hypothesis",
        parent_atom="[PL:1.1.0.0]",
        depth=2,
        via_links=("[HL:3.1]",),
        anchor_atoms=("[PL:1.1.0.0]", "[TMP:5.TMP.ignored]"),
    )
    bad_non_tmp = SessionTmpNode(
        canonical_str="[ND:5.1.1]",
        session_uuid="sess-abc-1234",
        node_uuid="n-1",
        label="Cannot promote non-TMP atom",
        parent_atom="[PL:1.1.0.0]",
        depth=1,
        via_links=(),
        anchor_atoms=("[PL:1.1.0.0]",),
    )
    bad_unanchored = SessionTmpNode(
        canonical_str="[TMP:5.TMP.22222222-2222-2222-2222-222222222222]",
        session_uuid="sess-abc-1234",
        node_uuid="22222222-2222-2222-2222-222222222222",
        label="Orphan TMP node",
        parent_atom="[TMP:5.TMP.other]",
        depth=1,
        via_links=(),
        anchor_atoms=("[TMP:5.TMP.other]",),
    )

    staging_dir = tmp_path / "staging"
    res = stage_quarantined_nodes(
        session_uuid="sess-abc-1234",
        nodes=[valid_node, bad_non_tmp, bad_unanchored],
        staging_dir=staging_dir,
        staged_by="curator-1",
        evidence_refs_by_node={valid_node.canonical_str: ("src-001",)},
    )
    assert res.status == "staged_for_review"
    assert res.staged_count == 1
    assert res.rejected_count == 2
    assert res.live_registry_modified is False
    assert res.staging_path is not None and res.staging_path.is_file()

    staged_doc = json.loads(res.staging_path.read_text(encoding="utf-8"))
    assert staged_doc["reviewed"] is False
    assert staged_doc["live_registry_modified"] is False
    assert staged_doc["candidates"][0]["anchor_atoms"] == ["[PL:1.1.0.0]"]

    # Empty promotion yields empty status without writing file
    empty_res = stage_quarantined_nodes(
        session_uuid="sess-empty",
        nodes=[bad_non_tmp],
        staging_dir=staging_dir,
    )
    assert empty_res.status == "empty"
    assert empty_res.staged_count == 0
    assert empty_res.staging_path is None

    # Refuses staging inside live config/registry directory
    with pytest.raises(ContractValidationError, match="live config/registry"):
        stage_quarantined_nodes(
            session_uuid="sess-bad-target",
            nodes=[valid_node],
            staging_dir=CONFIG_DIR / "registry",
        )


def test_p09_cross_domain_analogies_and_contract_shape() -> None:
    """T-UNIT-FN-P09-01..02: P09 emits non-citable [TMP:ANALOGY:...] hypotheses cleanly."""
    cfg = load_config(CONFIG_DIR)
    snapshot = load_registry(
        CONFIG_DIR / "registry",
        overlay_dir=PILOT_DIR,
        w3=cfg.tiers.distance_weights.w3,
        w67=cfg.tiers.distance_weights.w67,
    )
    anchors = [snapshot.spine_edges[0].src]
    hyps = generate_cross_domain_analogies(
        query_anchors=anchors,
        snapshot=snapshot,
        max_analogies=4,
        domain_hint="warehouse",
    )
    assert 1 <= len(hyps) <= 4
    p09_out_schema = json.loads(
        (REPO_ROOT / "contracts" / "functions" / "p09.out.json").read_text()
    )
    jsonschema.validate({"hypotheses": [h.to_dict() for h in hyps]}, p09_out_schema)
    for h in hyps:
        assert h.is_hypothesis is True
        assert h.citable_as_evidence is False
        assert h.hypothesis_id.startswith("[TMP:ANALOGY:")
        assert can_cite_as_evidence(h.hypothesis_id) is False


@pytest.mark.asyncio
async def test_p09_orchestrator_profile_gating_advisory_vs_strict(tmp_path: Path) -> None:
    """T-UNIT-FN-P09-03: P09 executes in advisory profile and skips in strict / kernel_only."""
    cfg = load_config(CONFIG_DIR)
    snapshot = load_registry(CONFIG_DIR / "registry", overlay_dir=PILOT_DIR)
    outcomes_by_profile: dict[str, str] = {}

    for profile_name, model_name in (
        ("strict", "dle-13axis-strict"),
        ("advisory", "dle-13axis-advisory"),
        ("kernel_only", "dle-13axis-strict"),
    ):
        sub_dir = tmp_path / profile_name
        stores = open_stores(sub_dir / "db", enable_vec=False)
        try:
            model_reg = ModelRegistry(cfg.model_pins)
            fake = FakeModel(registry=model_reg)
            fn_reg = FunctionRegistry(cfg.functions, cfg.profiles)
            register_phase1_functions(fn_reg, cfg.notices)
            ev_repo = EvidenceRepository(stores.evidence, vec_enabled=False)
            sess_repo = SessionRepository(stores.sessions)
            rcpt_repo = ReceiptRepository(stores.receipts)
            reg_repo = RegistryRepository(stores.registry)
            ops_repo = OpsRepository(stores.ops)
            emb = EmbeddingService(fake, model_reg)
            ev_svc = EvidenceService(ev_repo, emb)
            ext = ClaimExtractor(fake, model_reg)
            ver = ClaimVerifier(DeterministicLexicalNliScorer(), ev_svc)
            key_mgr = Ed25519KeyManager(rcpt_repo, keys_dir=sub_dir / "keys")
            sealer = ReceiptSealer(rcpt_repo, key_mgr)

            clause = "Warehouse staging lane L-9 requires wheel chocks during pallet unloading."
            await ev_svc.register_document(
                title="Staging Rule L-9",
                authority_class="primary_text",
                content_text=clause,
                api_key="test-key",
            )
            req = translate_generate_request(
                model=model_name,
                body={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
                tenant="t-p09",
            )
            eff_req = req if profile_name != "kernel_only" else replace(req, profile="kernel_only")
            res = await run_governed_workflow(
                run_req=eff_req,
                config=cfg,
                function_registry=fn_reg,
                model_registry=model_reg,
                model_port=fake,
                evidence_service=ev_svc,
                claim_extractor=ext,
                claim_verifier=ver,
                receipt_sealer=sealer,
                ops_repo=ops_repo,
                session_repo=sess_repo,
                calibration=DEFAULT_PHASE2_CALIBRATION,
                api_key="test-key",
                registry_snapshot=snapshot,
                enable_ppr=True,
                registry_repo=reg_repo,
                tool_bridge=ToolBridge(),
                triage_override={"d": 1, "r": 0, "m": 0, "binding": False, "z_hit": False},
            )
            p09_recs = [r for r in res.function_records if r.dvss_id == "DVSS-P09"]
            assert p09_recs
            outcomes_by_profile[profile_name] = p09_recs[0].outcome
            for src in res.receipt["payload"]["sources"]:
                assert not str(src.get("source_id", "")).startswith("[TMP:ANALOGY:")
        finally:
            stores.close()

    assert outcomes_by_profile["advisory"] == "ok"
    assert outcomes_by_profile["strict"] == "skipped"
    assert outcomes_by_profile["kernel_only"] == "skipped"


def test_pluggable_transparency_log_anchoring_profiles(tmp_path: Path) -> None:
    """T-UNIT-ANCHOR-01..04: local, customer-hosted, and external log anchoring + pending guard."""
    # 1. Local WORM Merkle
    s1 = open_stores(tmp_path / "local", enable_vec=False)
    try:
        rrepo1 = ReceiptRepository(s1.receipts)
        km1 = Ed25519KeyManager(rrepo1, keys_dir=tmp_path / "local" / "keys")
        sealer1 = ReceiptSealer(rrepo1, km1, anchor_provider=LocalWormMerkleAnchor())
        p1 = _minimal_receipt_payload(
            run_id="11111111-1111-4111-8111-111111111111",
            utc_iso="2026-11-23T21:00:00Z",
            profile="strict",
        )
        rec1 = sealer1.seal_receipt(payload=p1, api_release_mode="released")
        assert rec1["envelope"]["anchoring_profile"] == "local_worm_merkle"
        assert rec1["envelope"]["verification_level"] == "locally_sealed"
        assert sealer1.get_receipt(str(p1["run_id"])) == rec1
    finally:
        s1.close()

    # 2. Customer-hosted append-only JSONL log
    s2 = open_stores(tmp_path / "cust", enable_vec=False)
    try:
        cust_log = tmp_path / "cust" / "audit.jsonl"
        rrepo2 = ReceiptRepository(s2.receipts)
        km2 = Ed25519KeyManager(rrepo2, keys_dir=tmp_path / "cust" / "keys")
        sealer2 = ReceiptSealer(
            rrepo2,
            km2,
            anchor_provider=CustomerHostedLogAnchor(log_path=cust_log, log_name="acme-worm"),
        )
        p2 = _minimal_receipt_payload(
            run_id="22222222-2222-4222-8222-222222222222",
            utc_iso="2026-11-23T21:01:00Z",
            profile="strict",
        )
        rec2 = sealer2.seal_receipt(payload=p2, api_release_mode="released")
        assert rec2["envelope"]["anchoring_profile"] == "customer_hosted_log"
        assert rec2["envelope"]["verification_level"] == "customer_anchored"
        assert rec2["envelope"]["log_id"] == "customer-hosted-log:acme-worm"
        assert cust_log.is_file() and len(cust_log.read_text().splitlines()) == 1
        assert sealer2.get_receipt(str(p2["run_id"])) == rec2

        bundle_bytes = sealer2.export_bundle(
            "2026-11-23T00:00:00Z",
            "2026-11-24T00:00:00Z",
            exported_by="auditor",
        )
        zip_p = tmp_path / "cust_bundle.zip"
        zip_p.write_bytes(bundle_bytes)
        ok, errs = verify_bundle_zip(zip_p)
        assert ok is True and errs == []
    finally:
        s2.close()

    # 3. External transparency log: confirmed succeeds; unconfirmed/mismatched refuses before insert
    s3 = open_stores(tmp_path / "ext", enable_vec=False)
    try:
        rrepo3 = ReceiptRepository(s3.receipts)
        km3 = Ed25519KeyManager(rrepo3, keys_dir=tmp_path / "ext" / "keys")
        seen_submissions: list[dict[str, object]] = []

        def _confirming_submitter(payload: Mapping[str, object]) -> Mapping[str, object]:
            seen_submissions.append(dict(payload))
            return {
                "confirmed": True,
                "inclusion_proof_ref": f"rekor:log-99#index:{payload['chain_seq']}",
                "checkpoint_sha256": str(payload["merkle_root"]),
            }

        sealer3 = ReceiptSealer(
            rrepo3,
            km3,
            anchor_provider=ExternalTransparencyLogAnchor(
                external_log_id="sigstore-rekor-prod",
                submitter=_confirming_submitter,
            ),
        )
        p3 = _minimal_receipt_payload(
            run_id="33333333-3333-4333-8333-333333333333",
            utc_iso="2026-11-23T21:02:00Z",
            profile="strict",
        )
        rec3 = sealer3.seal_receipt(payload=p3, api_release_mode="released")
        assert len(seen_submissions) == 1
        assert rec3["envelope"]["anchoring_profile"] == "external_transparency_log"
        assert rec3["envelope"]["verification_level"] == "externally_anchored"
        assert sealer3.get_receipt(str(p3["run_id"])) == rec3

        pub_b64 = km3.get_public_key_b64(km3.active_key_id)
        assert pub_b64 is not None
        ok_sig, errs_sig = verify_signed_receipt(rec3, public_key_b64=pub_b64)
        assert ok_sig is True and errs_sig == []

        # Unconfirmed external anchor MUST raise AnchorPendingError and never store a receipt
        sealer3_fail = ReceiptSealer(
            rrepo3,
            km3,
            anchor_provider=ExternalTransparencyLogAnchor(
                external_log_id="sigstore-rekor-prod",
                submitter=lambda _p: {"confirmed": False},
            ),
        )
        p4 = _minimal_receipt_payload(
            run_id="44444444-4444-4444-8444-444444444444",
            utc_iso="2026-11-23T21:03:00Z",
            profile="strict",
        )
        with pytest.raises(AnchorPendingError, match="did not confirm inclusion"):
            sealer3_fail.seal_receipt(payload=p4, api_release_mode="released")
        assert sealer3_fail.get_receipt(str(p4["run_id"])) is None
        assert isinstance(canonicalize_jcs(p1), bytes)
    finally:
        s3.close()


def test_all_26_dvss_functions_have_paired_contracts() -> None:
    """T-CONTRACT-26FN-01: Every DVSS function (K01..K12, P01..P14) has .in and .out JSON."""
    cfg = load_config(CONFIG_DIR)
    fn_dir = REPO_ROOT / "contracts" / "functions"
    assert len(cfg.functions.functions) == 26
    for fn in cfg.functions.functions:
        stem = fn.id.removeprefix("DVSS-").lower()
        assert (fn_dir / f"{stem}.in.json").is_file(), f"missing {stem}.in.json for {fn.id}"
        assert (fn_dir / f"{stem}.out.json").is_file(), f"missing {stem}.out.json for {fn.id}"
