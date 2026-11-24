"""Unit & engine tests for H2 Hybrid Intake Router (DVSS-K10) and ModelCallBudget."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from dle.config import load_config
from dle.edge.translator import translate_generate_request
from dle.host.functions import FunctionContext, FunctionRegistry, register_phase1_functions
from dle.host.services import (
    DEONTIC_PREDICATES,
    ClaimExtractor,
    ClaimVerifier,
    Ed25519KeyManager,
    EvidenceService,
    IntakeRouter,
    ModelCallBudget,
    ReceiptSealer,
    band_pillar_count,
    load_failure_centroids,
    load_registry,
    score_r_rules,
)
from dle.host.workflow import DEFAULT_PHASE2_CALIBRATION, run_governed_workflow
from dle.models import DeterministicLexicalNliScorer, EmbeddingService, FakeModel, ModelRegistry
from dle.store import (
    EvidenceRepository,
    OpsRepository,
    ReceiptRepository,
    SessionRepository,
    open_stores,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "config"
CENTROID_PATH = CONFIG_DIR / "intake" / "dev_failure_centroids.yaml"
CHALLENGE_50_PATH = REPO_ROOT / "offline" / "dev_sets" / "intake_challenge_dev_50.jsonl"
K10_IN_SCHEMA = json.loads(
    (REPO_ROOT / "contracts" / "functions" / "k10.in.json").read_text("utf-8")
)
K10_OUT_SCHEMA = json.loads(
    (REPO_ROOT / "contracts" / "functions" / "k10.out.json").read_text("utf-8")
)
K10_IN_VAL = jsonschema.Draft202012Validator(K10_IN_SCHEMA)
K10_OUT_VAL = jsonschema.Draft202012Validator(K10_OUT_SCHEMA)


def _make_router() -> tuple[IntakeRouter, FakeModel, ModelRegistry]:
    cfg = load_config(CONFIG_DIR)
    reg = ModelRegistry(cfg.model_pins)
    fake = FakeModel(registry=reg)
    emb = EmbeddingService(fake, reg)
    catalog = load_failure_centroids(CENTROID_PATH)
    router = IntakeRouter(
        tiers_config=cfg.tiers,
        model_registry=reg,
        model_port=fake,
        embedding_service=emb,
        centroid_catalog=catalog,
    )
    return router, fake, reg


def test_d_band_pillar_boundaries_and_r_rules_floor() -> None:
    """T-UNIT-TIER-01..02: Verify D bands (0..6 pillars) and auditable R rules floor."""
    assert [band_pillar_count(n) for n in range(7)] == [0, 0, 1, 2, 2, 3, 3]

    r0, reasons0 = score_r_rules(query_str="What height are standard warehouse shelves?")
    assert r0 == 0 and reasons0 == ()

    r1, _ = score_r_rules(query_str="Summarize internal warehouse policy guidance.")
    assert r1 == 1

    r2_src, reasons2 = score_r_rules(
        query_str="Check item note.",
        matched_sources=[{"authorityClass": "binding_instrument"}],
    )
    assert r2_src == 2 and "binding_source" in reasons2

    r2_mesh, reasons_mesh = score_r_rules(
        query_str="Check mesh entry.",
        coordinate={"axis_7_spiderweb": [{"id": "[MESH:7.9]"}]},
    )
    assert r2_mesh == 2 and "axis7_crosswalk" in reasons_mesh

    r3_jur, _ = score_r_rules(
        query_str="Check multi jurisdiction.",
        coordinate={"axis_12_jurisdiction": [{"id": "[JUR:12.1]"}, {"id": "[JUR:12.2]"}]},
    )
    assert r3_jur == 3


@pytest.mark.asyncio
async def test_r_model_cannot_lower_r_rules_and_m_band_boundaries() -> None:
    """T-UNIT-TIER-02..03: Model cannot lower R_rules; M bands 0..3 route properly."""
    router, _fake, _reg = _make_router()

    dec_floor = await router.evaluate(
        query_str="Standard safety SOP policy lookup.",
        matched_sources=[{"authorityClass": "binding_instrument"}],
        override_model_scores=(0, 0, False),
        override_z=(0, 0.1, None),
    )
    assert dec_floor.r_rules == 2
    assert dec_floor.r_model == 0
    assert dec_floor.r_final == 2
    assert dec_floor.b == 1
    assert dec_floor.tier >= 2

    m_queries = [
        ("What is the width of Depot 4 gate?", 0),
        ("Compare Candidate A versus Candidate B latency.", 1),
        ("Resolve exemption timing depending on prior period rule.", 2),
        ("Simulate cascading scenario under worst-case outage.", 3),
    ]
    for query, expected_m in m_queries:
        dec = await router.evaluate(
            query_str=query,
            override_z=(0, 0.1, None),
        )
        assert dec.m == expected_m, (query, dec)


@pytest.mark.asyncio
async def test_all_b_triggers_z_hit_on_demand_roles_and_rationale_redaction() -> None:
    """T-UNIT-TIER-04..08: Verify B triggers, Z hit, role sets, redaction, and K10 schema."""
    router, _fake, _reg = _make_router()

    for pred in DEONTIC_PREDICATES:
        dec = await router.evaluate(
            query_str=f"Operators {pred} inspect bracket daily.",
            override_model_scores=(0, 0, False),
            override_z=(0, 0.1, None),
        )
        assert pred in dec.deontic_hits
        assert dec.b == 1 and dec.s_eff >= 3
        assert "regulator" in dec.active_roles

    dec_tool = await router.evaluate(
        query_str="Check widget weight.",
        consequential_tool_hit=True,
        override_model_scores=(0, 0, False),
        override_z=(0, 0.1, None),
    )
    assert dec_tool.b == 1 and dec_tool.tier >= 2

    dec_z = await router.evaluate(
        query_str="Benign wording.",
        override_model_scores=(0, 0, False),
        override_z=(1, 0.88, "bypass_safety_controls"),
    )
    assert dec_z.z == 1 and dec_z.s_eff == 6 and dec_z.tier == 3
    assert dec_z.active_roles == ("scholar", "practitioner", "regulator", "harmonizer")

    dec_t2_mesh = await router.evaluate(
        query_str="Compare technical crosswalk note.",
        coordinate={
            "axis_1_pillars": [{"id": "[PL:1.1.0.0]"}, {"id": "[PL:1.2.0.0]"}],
            "axis_7_spiderweb": [{"id": "[MESH:7.9]"}],
        },
        override_model_scores=(0, 1, False),
        override_z=(0, 0.1, None),
    )
    assert dec_t2_mesh.tier == 2
    assert "harmonizer" in dec_t2_mesh.active_roles

    dec_t3_relevant = await router.evaluate(
        query_str="Analyze open system properties.",
        coordinate={"axis_1_pillars": [{"id": f"[PL:1.{i}.0.0]"} for i in range(1, 6)]},
        override_model_scores=(1, 2, False),
        override_z=(0, 0.1, None),
    )
    assert dec_t3_relevant.s == 6 and dec_t3_relevant.b == 0 and dec_t3_relevant.z == 0
    assert dec_t3_relevant.tier == 3
    assert "harmonizer" not in dec_t3_relevant.active_roles
    assert dec_t3_relevant.rationale
    public = dec_t3_relevant.to_public_metadata()
    assert "rationale" not in public

    cfg = load_config(CONFIG_DIR)
    fn_reg = FunctionRegistry(cfg.functions, cfg.profiles)
    register_phase1_functions(fn_reg, cfg.notices)
    k10_in = dec_z.to_k10_payload()
    assert not list(K10_IN_VAL.iter_errors(k10_in))
    k10_res = fn_reg.invoke(
        "DVSS-K10",
        FunctionContext(run_id="r-k10", attempt_id="att-0", profile="strict", payload=k10_in),
    )
    assert not list(K10_OUT_VAL.iter_errors(k10_res.output))


@pytest.mark.asyncio
async def test_dev_challenge_set_50_tier3_recall_and_benign_specificity() -> None:
    """T-ENG-TIER-01: >= 95% Tier-3 recall on 50-item dev challenge set; benign stays Tier 1/2."""
    router, _fake, _reg = _make_router()
    items = [
        json.loads(line)
        for line in CHALLENGE_50_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(items) == 50

    tier3_hits = 0
    for item in items:
        dec = await router.evaluate(query_str=str(item["query"]))
        if dec.tier == 3 and len(dec.active_roles) == 4:
            tier3_hits += 1

    recall = tier3_hits / len(items)
    assert recall >= 0.95, f"Expected >= 95% recall on 50-item challenge set, got {recall:.2%}"

    benign_controls = [
        "What hours is Cafeteria B open on Fridays?",
        "Which connector pin carries DC return on Module 4?",
        "List the dimensions of shipping pallet type C.",
        "Compare throughput of Candidate A versus Candidate B.",
        "What weight limit is printed on aluminum bracket B-12?",
        "What is the serial prefix for North warehouse scanners?",
    ]
    for q in benign_controls:
        dec = await router.evaluate(query_str=q)
        assert dec.tier < 3 and dec.z == 0, (q, dec)


def test_model_call_budget_tier_ceilings() -> None:
    """T-UNIT-TIER-09: Verify 9/21, 18/22, and 18 call ceilings in ModelCallBudget."""
    cfg = load_config(CONFIG_DIR)
    b1 = ModelCallBudget(cfg.tiers, initial_tier=1)
    assert b1.limit == 9 and b1.remaining() == 9
    assert b1.on_escalate(next_tier=2) == 21

    b2 = ModelCallBudget(cfg.tiers, initial_tier=2)
    assert b2.limit == 18
    assert b2.on_escalate(next_tier=3) == 22

    b3 = ModelCallBudget(cfg.tiers, initial_tier=3)
    assert b3.limit == 18 and b3.can_spend(18) and not b3.can_spend(19)


@pytest.mark.asyncio
async def test_workflow_intake_router_budget_redaction_and_real_cost_metering(
    tmp_path: Path,
) -> None:
    """T-ENG-TIER-02: End-to-end governed run wires H2 intake, budget cap, and positive USD cost."""
    cfg = load_config(CONFIG_DIR)
    reg = ModelRegistry(cfg.model_pins)
    fake = FakeModel(registry=reg)
    emb = EmbeddingService(fake, reg)
    router = IntakeRouter(
        tiers_config=cfg.tiers,
        model_registry=reg,
        model_port=fake,
        embedding_service=emb,
        centroid_catalog=load_failure_centroids(CENTROID_PATH),
    )
    fn_reg = FunctionRegistry(cfg.functions, cfg.profiles)
    register_phase1_functions(fn_reg, cfg.notices)
    stores = open_stores(tmp_path / "db", enable_vec=False)
    try:
        ev_svc = EvidenceService(EvidenceRepository(stores.evidence, vec_enabled=False), emb)
        await ev_svc.register_document(
            title="RF Spec",
            authority_class="primary_text",
            content_text="Candidate B RF link budget maintains 5 GHz MCS9 rate.",
            api_key="test-key",
        )
        req = translate_generate_request(
            model="dle-13axis-strict",
            body={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": "Candidate B RF link budget maintains 5 GHz MCS9 rate."}
                        ],
                    }
                ]
            },
            tenant="t1",
        )
        res = await run_governed_workflow(
            run_req=req,
            config=cfg,
            function_registry=fn_reg,
            model_registry=reg,
            model_port=fake,
            evidence_service=ev_svc,
            claim_extractor=ClaimExtractor(fake, reg),
            claim_verifier=ClaimVerifier(DeterministicLexicalNliScorer(), ev_svc),
            receipt_sealer=ReceiptSealer(
                ReceiptRepository(stores.receipts),
                Ed25519KeyManager(ReceiptRepository(stores.receipts), keys_dir=tmp_path / "keys"),
            ),
            ops_repo=OpsRepository(stores.ops),
            session_repo=SessionRepository(stores.sessions),
            calibration=DEFAULT_PHASE2_CALIBRATION,
            api_key="test-key",
            registry_snapshot=load_registry(CONFIG_DIR / "registry"),
            intake_router=router,
        )
        meta = res.body["dleMetadata"]
        assert isinstance(meta, dict)
        assert "intake" in meta
        assert "rationale" not in meta["intake"]
        summary = meta["runSummary"]
        assert summary["modelCallsUsed"] >= 3
        assert summary["modelCallsUsed"] <= summary["modelCallBudget"]
        assert summary["costUsd"] > 0.0

        daily = OpsRepository(stores.ops).cost_by_tier_daily(days=7)
        assert len(daily) == 1 and daily[0]["totalUsd"] > 0.0
    finally:
        stores.close()
