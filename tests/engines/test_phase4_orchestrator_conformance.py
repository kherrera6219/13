"""End-to-end 12-step FROST orchestrator conformance tests (Phase 4 Wave 4B, paper §18b)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import jsonschema
import pytest

from dle.config import DleConfig, load_config
from dle.config.models import ConsequentialFunctionFlag, FunctionFlagsConfig
from dle.edge.sessions import session_id_after_response
from dle.edge.tools import ToolBridge
from dle.edge.translator import translate_generate_request
from dle.host.frost import FROST_LAYERS, STEP_IDS
from dle.host.functions import FunctionRegistry, register_phase1_functions
from dle.host.services import (
    ClaimExtractor,
    ClaimVerifier,
    Ed25519KeyManager,
    EvidenceService,
    ReceiptSealer,
    load_reference_catalog,
    load_registry,
)
from dle.host.workflow import DEFAULT_PHASE2_CALIBRATION, run_governed_workflow
from dle.models import (
    DeterministicLexicalNliScorer,
    EgressClient,
    EmbeddingService,
    GeminiAdapter,
    ModelRegistry,
)
from dle.models.fake import FakeModel
from dle.store import (
    EvidenceRepository,
    OpsRepository,
    ReceiptRepository,
    RegistryRepository,
    SessionRepository,
    open_stores,
)
from tests.gemini_compat.fake_upstream import FakeUpstream

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
PILOT_DIR = CONFIG_DIR / "pilots" / "warehouse_substitution"
RECEIPT_SCHEMA = json.loads((REPO_ROOT / "contracts" / "receipt.schema.json").read_text("utf-8"))
RECEIPT_VALIDATOR = jsonschema.Draft202012Validator(
    RECEIPT_SCHEMA, format_checker=jsonschema.FormatChecker()
)


class _EngineEnv:
    def __init__(self, tmp_path: Path, *, cfg: DleConfig | None = None, model_port=None) -> None:
        self.config = cfg or load_config(CONFIG_DIR)
        self.model_registry = ModelRegistry(self.config.model_pins)
        self.model_port = model_port or FakeModel(registry=self.model_registry)
        self.fn_registry = FunctionRegistry(self.config.functions, self.config.profiles)
        register_phase1_functions(self.fn_registry, self.config.notices)
        self.fn_registry.self_check()
        self.tool_bridge = ToolBridge()

        self.stores = open_stores(tmp_path / "db", enable_vec=False)
        self.ev_repo = EvidenceRepository(self.stores.evidence, vec_enabled=False)
        self.sess_repo = SessionRepository(self.stores.sessions)
        self.rcpt_repo = ReceiptRepository(self.stores.receipts)
        self.reg_repo = RegistryRepository(self.stores.registry)
        self.ops_repo = OpsRepository(self.stores.ops)

        self.embeddings = EmbeddingService(self.model_port, self.model_registry)
        self.ev_service = EvidenceService(self.ev_repo, self.embeddings)
        self.extractor = ClaimExtractor(self.model_port, self.model_registry)
        self.verifier = ClaimVerifier(DeterministicLexicalNliScorer(), self.ev_service)
        self.key_mgr = Ed25519KeyManager(self.rcpt_repo, keys_dir=tmp_path / "keys")
        self.sealer = ReceiptSealer(self.rcpt_repo, self.key_mgr)
        self.snapshot = load_registry(CONFIG_DIR / "registry", overlay_dir=PILOT_DIR)
        self.ref_catalog = load_reference_catalog(
            CONFIG_DIR / "reference" / "manifest.yaml",
            ref_dir=CONFIG_DIR / "reference",
        )

    def close(self) -> None:
        self.stores.close()


@pytest.mark.asyncio
async def test_phase4_straight_run_frost_layers_profiles_and_receipt(tmp_path: Path) -> None:
    """T-ENG-WF-01: Straight run records all 12 steps, 10 FROST layers & 3.8.0 receipt."""
    env = _EngineEnv(tmp_path)
    try:
        clause = "Candidate B RF link budget maintains 5 GHz MCS9 rate in corridor testing."
        await env.ev_service.register_document(
            title="RF Test Spec",
            authority_class="primary_text",
            content_text=clause,
            api_key="test-key",
        )

        req = translate_generate_request(
            model="dle-13axis-strict",
            body={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
            tenant="t1",
        )
        res = await run_governed_workflow(
            run_req=req,
            config=env.config,
            function_registry=env.fn_registry,
            model_registry=env.model_registry,
            model_port=env.model_port,
            evidence_service=env.ev_service,
            claim_extractor=env.extractor,
            claim_verifier=env.verifier,
            receipt_sealer=env.sealer,
            ops_repo=env.ops_repo,
            session_repo=env.sess_repo,
            calibration=DEFAULT_PHASE2_CALIBRATION,
            api_key="test-key",
            registry_snapshot=env.snapshot,
            enable_ppr=True,
            registry_repo=env.reg_repo,
            reference_catalog=env.ref_catalog,
            tool_bridge=env.tool_bridge,
            triage_override={"d": 1, "r": 0, "m": 0, "binding": False, "z_hit": False},
        )
        assert res.release_mode == "released"
        assert res.escalated is False and res.retries == 0
        assert {str(s["stepId"]) for s in res.steps} == set(STEP_IDS)
        assert {str(s["layerId"]) for s in res.steps} == set(FROST_LAYERS)
        assert res.personas and str(res.personas[0]["profileId"]).startswith("[ROLE:8.")

        rcpt_errors = list(RECEIPT_VALIDATOR.iter_errors(res.receipt))
        assert not rcpt_errors, rcpt_errors[0].message
        meta = res.body["dleMetadata"]
        assert isinstance(meta, dict)
        assert meta["runSummary"]["attemptsCount"] == 1
        assert len(meta["steps"]) >= 12
        personas_meta = meta["personas"]
        assert isinstance(personas_meta, list) and len(personas_meta) >= 1
        for p_entry in personas_meta:
            assert isinstance(p_entry, dict)
            assert isinstance(p_entry.get("findings"), list)
    finally:
        env.close()


@pytest.mark.asyncio
async def test_phase4_one_time_binding_escalation_carries_objections(tmp_path: Path) -> None:
    """T-ENG-WF-02 (§18 F8/F10): Tier 1 binding draft escalates once with Regulator active."""
    env = _EngineEnv(tmp_path)
    try:
        clause = (
            "Candidate B replacement in North warehouse must comply with Change Order policy "
            "and requires buyer approval."
        )
        await env.ev_service.register_document(
            title="Warehouse Purchase Clause",
            authority_class="primary_text",
            content_text=clause,
            api_key="test-key",
        )
        req = translate_generate_request(
            model="dle-13axis-strict",
            body={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
            tenant="t1",
        )
        res = await run_governed_workflow(
            run_req=req,
            config=env.config,
            function_registry=env.fn_registry,
            model_registry=env.model_registry,
            model_port=env.model_port,
            evidence_service=env.ev_service,
            claim_extractor=env.extractor,
            claim_verifier=env.verifier,
            receipt_sealer=env.sealer,
            ops_repo=env.ops_repo,
            session_repo=env.sess_repo,
            calibration=DEFAULT_PHASE2_CALIBRATION,
            api_key="test-key",
            registry_snapshot=env.snapshot,
            enable_ppr=True,
            registry_repo=env.reg_repo,
            reference_catalog=env.ref_catalog,
            triage_override={"d": 0, "r": 0, "m": 0, "binding": False, "z_hit": False},
        )
        assert res.escalated is True
        assert res.tier >= 2
        assert res.retries == 0
        attempts = res.receipt["payload"]["attempts"]
        assert len(attempts) == 2
        assert attempts[0]["event"] == "initial"
        assert attempts[1]["event"] == "tier_escalation"
        axes_att1 = {ax for rc in attempts[1]["role_calls"] for ax in rc["role_axes"]}
        assert 10 in axes_att1
        assert not list(RECEIPT_VALIDATOR.iter_errors(res.receipt))
    finally:
        env.close()


@pytest.mark.asyncio
async def test_phase4_cutoff_blind_two_retry_cap_and_replay_invariance(tmp_path: Path) -> None:
    """T-ENG-WF-03 (§18 F13): <= 2 retries identical regardless of cutoff 0.01 vs 0.90."""
    from dataclasses import replace

    async def _run_with_cutoff(sub_dir: Path, threshold: float):
        env = _EngineEnv(sub_dir)
        try:
            await env.ev_service.register_document(
                title="Unrelated Doc",
                authority_class="primary_text",
                content_text="Cafeteria hours run Monday to Friday.",
                api_key="test-key",
            )
            for idx in (1, 2, 3):
                await env.ev_service.register_document(
                    title=f"Supplemental {idx}",
                    authority_class="primary_text",
                    content_text=f"Annex supplemental_{idx} notes pending review.",
                    api_key="test-key",
                )
            req = translate_generate_request(
                model="dle-13axis-strict",
                body={
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": "Verify ungrounded orbital cargo schedule."}],
                        }
                    ]
                },
                tenant="t1",
            )
            cal = replace(DEFAULT_PHASE2_CALIBRATION, threshold=threshold)
            return await run_governed_workflow(
                run_req=req,
                config=env.config,
                function_registry=env.fn_registry,
                model_registry=env.model_registry,
                model_port=env.model_port,
                evidence_service=env.ev_service,
                claim_extractor=env.extractor,
                claim_verifier=env.verifier,
                receipt_sealer=env.sealer,
                ops_repo=env.ops_repo,
                session_repo=env.sess_repo,
                calibration=cal,
                api_key="test-key",
                registry_snapshot=env.snapshot,
                enable_ppr=True,
                triage_override={"d": 1, "r": 0, "m": 0, "binding": False, "z_hit": False},
                retry_sources=("supplemental_1", "supplemental_2", "supplemental_3"),
            )
        finally:
            env.close()

    res_strict = await _run_with_cutoff(tmp_path / "strict_cut", 0.01)
    res_loose = await _run_with_cutoff(tmp_path / "loose_cut", 0.90)
    assert res_strict.retries == 2 and res_loose.retries == 2
    assert len(res_strict.receipt["payload"]["attempts"]) == 3
    assert [a["hops"] for a in res_strict.receipt["payload"]["attempts"]] == [1, 2, 3]
    assert res_strict.terminal_u == pytest.approx(res_loose.terminal_u)
    assert [a["event"] for a in res_strict.receipt["payload"]["attempts"]] == [
        "initial",
        "retry",
        "retry",
    ]
    assert not list(RECEIPT_VALIDATOR.iter_errors(res_strict.receipt))


@pytest.mark.asyncio
async def test_phase4_blinded_assurance_runs_before_advocates(tmp_path: Path) -> None:
    """T-ENG-WF-04 (FR-QP-06): Blinded mode executes axes 10/11 before axes 8/9."""
    from dle.config.models import ProfileConfig

    base_cfg = load_config(CONFIG_DIR)
    blinded_strict = ProfileConfig.model_validate(
        {
            **base_cfg.profiles["strict"].model_dump(),
            "blinded_assurance_roles": True,
        }
    )
    cfg = base_cfg.model_copy(update={"profiles": {**base_cfg.profiles, "strict": blinded_strict}})
    fake = FakeModel()
    env = _EngineEnv(tmp_path, cfg=cfg, model_port=fake)
    try:
        clause = "North warehouse Candidate B wireless access point requires acceptance testing."
        await env.ev_service.register_document(
            title="Warehouse Spec",
            authority_class="primary_text",
            content_text=clause,
            api_key="test-key",
        )
        req = translate_generate_request(
            model="dle-13axis-strict",
            body={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
            tenant="t1",
        )
        res = await run_governed_workflow(
            run_req=req,
            config=env.config,
            function_registry=env.fn_registry,
            model_registry=env.model_registry,
            model_port=fake,
            evidence_service=env.ev_service,
            claim_extractor=env.extractor,
            claim_verifier=env.verifier,
            receipt_sealer=env.sealer,
            ops_repo=env.ops_repo,
            session_repo=env.sess_repo,
            calibration=DEFAULT_PHASE2_CALIBRATION,
            api_key="test-key",
            registry_snapshot=env.snapshot,
            enable_ppr=True,
            triage_override={"d": 3, "r": 2, "m": 2, "binding": True, "z_hit": True},
        )
        assert res.release_mode == "released"
        persona_calls = [c for c in fake.calls if c.job == "personas"]
        assert len(persona_calls) == 4
        call_roles = []
        for c in persona_calls:
            txt = json.dumps(c.payload)
            if '"axis":8' in txt or '\\"axis\\":8' in txt:
                call_roles.append(8)
            elif '"axis":9' in txt or '\\"axis\\":9' in txt:
                call_roles.append(9)
            elif '"axis":10' in txt or '\\"axis\\":10' in txt:
                call_roles.append(10)
            else:
                call_roles.append(11)
        assert call_roles[:2] == [10, 11]
        assert call_roles[2:] == [8, 9]
        tier3_meta = res.body["dleMetadata"]
        assert isinstance(tier3_meta, dict)
        for p_entry in tier3_meta["personas"]:
            assert isinstance(p_entry["findings"], list)
    finally:
        env.close()


@pytest.mark.asyncio
async def test_phase4_governed_step4_tool_park_resume_and_consequential_flag(
    tmp_path: Path,
) -> None:
    """T-ENG-WF-05 (FR-TOOL-02..05): Step-4 parks tool call, resumes, flags consequential Po."""
    base_cfg = load_config(CONFIG_DIR)
    flagged_cfg = base_cfg.model_copy(
        update={
            "function_flags": FunctionFlagsConfig(
                schema_version="1.0.0",
                consequential_functions=(
                    ConsequentialFunctionFlag(
                        name="submit_purchase_order",
                        reason="Creates a financial commitment",
                    ),
                ),
            )
        }
    )
    fake = FakeModel()
    env = _EngineEnv(tmp_path, cfg=flagged_cfg, model_port=fake)
    try:
        fake.enqueue_response(
            {
                "candidates": [
                    {
                        "index": 0,
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "id": "call-po-1",
                                        "name": "submit_purchase_order",
                                        "args": {"vendor": "B", "amount": 4200},
                                    }
                                }
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": "gemini-4-carbon-001",
            }
        )
        turn1 = {"role": "user", "parts": [{"text": "Submit purchase order for Candidate B."}]}
        tools_decl = [
            {
                "functionDeclarations": [
                    {"name": "submit_purchase_order", "parameters": {"type": "object"}}
                ]
            }
        ]
        req1 = translate_generate_request(
            model="dle-13axis-strict",
            body={"contents": [turn1], "tools": tools_decl},
            tenant="t1",
        )
        park_res = await run_governed_workflow(
            run_req=req1,
            config=env.config,
            function_registry=env.fn_registry,
            model_registry=env.model_registry,
            model_port=fake,
            evidence_service=env.ev_service,
            claim_extractor=env.extractor,
            claim_verifier=env.verifier,
            receipt_sealer=env.sealer,
            ops_repo=env.ops_repo,
            session_repo=env.sess_repo,
            calibration=DEFAULT_PHASE2_CALIBRATION,
            api_key="test-key",
            registry_snapshot=env.snapshot,
            tool_bridge=env.tool_bridge,
            tenant="t1",
        )
        assert park_res.release_mode == "passthrough"
        assert env.tool_bridge.count() == 1
        model_turn = park_res.body["candidates"][0]["content"]  # type: ignore[index]
        next_sid = session_id_after_response(
            tenant="t1",
            model=req1.model,
            system_instruction=None,
            contents=req1.contents,
            response_content=model_turn,
        )
        assert env.sess_repo.get_session(next_sid) is not None

        # Resume after app executes submit_purchase_order; triggers Regulator review.
        turn2_fn = {
            "role": "function",
            "parts": [
                {
                    "functionResponse": {
                        "id": "call-po-1",
                        "name": "submit_purchase_order",
                        "response": {"result": "Purchase order PO-900 confirmed."},
                    }
                }
            ],
        }
        req2 = translate_generate_request(
            model="dle-13axis-strict",
            body={
                "contents": [turn1, model_turn, turn2_fn],
                "tools": tools_decl,
            },
            tenant="t1",
        )
        resumed = await run_governed_workflow(
            run_req=req2,
            config=env.config,
            function_registry=env.fn_registry,
            model_registry=env.model_registry,
            model_port=fake,
            evidence_service=env.ev_service,
            claim_extractor=env.extractor,
            claim_verifier=env.verifier,
            receipt_sealer=env.sealer,
            ops_repo=env.ops_repo,
            session_repo=env.sess_repo,
            calibration=DEFAULT_PHASE2_CALIBRATION,
            api_key="test-key",
            registry_snapshot=env.snapshot,
            tool_bridge=env.tool_bridge,
            tenant="t1",
            triage_override={"d": 0, "r": 0, "m": 0, "binding": False, "z_hit": False},
        )
        assert env.tool_bridge.count() == 0
        assert resumed.escalated is True
        meta = resumed.body["dleMetadata"]
        assert isinstance(meta, dict)
        assert meta["runSummary"]["consequentialTools"] == ["submit_purchase_order"]
        assert not list(RECEIPT_VALIDATOR.iter_errors(resumed.receipt))
    finally:
        env.close()


@pytest.mark.asyncio
async def test_phase4_fake_upstream_gemini_replay_parity(tmp_path: Path) -> None:
    """T-ENG-WF-06: Verify §18 Phase 4 workflow against Gemini compat FakeUpstream."""
    cfg = load_config(CONFIG_DIR)
    reg = ModelRegistry(cfg.model_pins)
    upstream = FakeUpstream(registry=reg)
    env = _EngineEnv(tmp_path, cfg=cfg, model_port=upstream)
    try:
        clause = "Dual pressure relief valves certified under ISO 9001 are mandatory."
        await env.ev_service.register_document(
            title="Transit Valve Clause",
            authority_class="primary_text",
            content_text=clause,
            api_key="test-key",
        )
        req = translate_generate_request(
            model="dle-13axis-strict",
            body={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
            tenant="t1",
        )
        res = await run_governed_workflow(
            run_req=req,
            config=env.config,
            function_registry=env.fn_registry,
            model_registry=reg,
            model_port=upstream,
            evidence_service=env.ev_service,
            claim_extractor=env.extractor,
            claim_verifier=env.verifier,
            receipt_sealer=env.sealer,
            ops_repo=env.ops_repo,
            session_repo=env.sess_repo,
            calibration=DEFAULT_PHASE2_CALIBRATION,
            api_key="test-key",
            registry_snapshot=env.snapshot,
            enable_ppr=True,
        )
        assert res.release_mode == "released"
        assert any(r.job == "personas" for r in upstream.recorded_requests)
        assert any(r.job == "writer" for r in upstream.recorded_requests)
        upstream_meta = res.body["dleMetadata"]
        assert isinstance(upstream_meta, dict)
        assert all(isinstance(p.get("findings"), list) for p in upstream_meta["personas"])
        assert not list(RECEIPT_VALIDATOR.iter_errors(res.receipt))
    finally:
        env.close()


@pytest.mark.skipif(
    not os.environ.get("DLE_LIVE_GEMINI_API_KEY"),
    reason="Set DLE_LIVE_GEMINI_API_KEY to run live Gemini API conformance",
)
@pytest.mark.asyncio
async def test_phase4_live_gemini_conformance_opt_in(tmp_path: Path) -> None:
    """T-ENG-WF-07: Opt-in §18 Phase 4 live Gemini conformance via GeminiAdapter."""
    live_key = os.environ["DLE_LIVE_GEMINI_API_KEY"]
    cfg = load_config(CONFIG_DIR)
    reg = ModelRegistry(cfg.model_pins)
    async with EgressClient(allowlist=cfg.egress) as egress:
        gemini_port = GeminiAdapter(egress=egress, registry=reg, api_key=live_key)
        env = _EngineEnv(tmp_path, cfg=cfg, model_port=gemini_port)
        try:
            clause = "Candidate B RF link budget maintains 5 GHz MCS9 rate in corridor testing."
            await env.ev_service.register_document(
                title="Live Gemini Spec",
                authority_class="primary_text",
                content_text=clause,
                api_key="test-key",
            )
            req = translate_generate_request(
                model="dle-13axis-strict",
                body={"contents": [{"role": "user", "parts": [{"text": clause}]}]},
                tenant="t1",
            )
            res = await run_governed_workflow(
                run_req=req,
                config=env.config,
                function_registry=env.fn_registry,
                model_registry=reg,
                model_port=gemini_port,
                evidence_service=env.ev_service,
                claim_extractor=env.extractor,
                claim_verifier=env.verifier,
                receipt_sealer=env.sealer,
                ops_repo=env.ops_repo,
                session_repo=env.sess_repo,
                calibration=DEFAULT_PHASE2_CALIBRATION,
                api_key=live_key,
                registry_snapshot=env.snapshot,
                enable_ppr=True,
                registry_repo=env.reg_repo,
                reference_catalog=env.ref_catalog,
            )
            assert {str(s["stepId"]) for s in res.steps} == set(STEP_IDS)
            assert not list(RECEIPT_VALIDATOR.iter_errors(res.receipt))
        finally:
            env.close()
