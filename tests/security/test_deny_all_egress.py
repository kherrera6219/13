"""Security test attesting deny-by-default egress across the full governed workflow.

Implements DLE-SEC-002 §2, NFR-SEC-03, and NFR-PRIV-01: verifies that executing
``run_governed_workflow`` backed by ``GeminiAdapter`` + ``EgressClient`` under
a logging proxy transport touches ONLY ``generativelanguage.googleapis.com:443``,
blocks unlisted hosts/ports/non-HTTPS with ``EgressDenied`` (``DLE-E1101``),
records metadata-only entries into ``ops.db.egress_log``, and passes AST egress import scan.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from dle.config import load_config
from dle.edge.tools import ToolBridge
from dle.edge.translator import translate_generate_request
from dle.errors import EgressDenied
from dle.host.functions import FunctionRegistry, register_phase1_functions
from dle.host.services.claim_extractor import ClaimExtractor
from dle.host.services.evidence import EvidenceService
from dle.host.services.intake import IntakeRouter, load_failure_centroids
from dle.host.services.receipts import Ed25519KeyManager, ReceiptSealer
from dle.host.services.registry import load_registry
from dle.host.services.verifier import ClaimVerifier
from dle.host.workflow import DEFAULT_PHASE2_CALIBRATION, run_governed_workflow
from dle.models import (
    DeterministicLexicalNliScorer,
    EmbeddingService,
    ModelRegistry,
)
from dle.models.egress import EgressClient, EgressEvent
from dle.models.fake import FakeModel, build_fake_embedding_vector
from dle.models.gemini import GeminiAdapter
from dle.store import (
    EvidenceRepository,
    OpsRepository,
    ReceiptRepository,
    RegistryRepository,
    SessionRepository,
    open_stores,
)
from dle.tools.check_egress_imports import check_egress_imports

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


@pytest.mark.asyncio
async def test_deny_all_egress_attestation_across_governed_workflow(tmp_path: Path) -> None:
    """DLE-SEC-002 §2: governed execution contacts only Gemini HTTPS:443 via EgressClient."""
    assert check_egress_imports(REPO_ROOT) == []

    cfg = load_config(CONFIG_DIR)
    model_reg = ModelRegistry(cfg.model_pins)
    seen_targets: list[tuple[str, str, int]] = []
    upstream_stub = FakeModel()
    canary_secret = "AIza" + "SyDenyAllProxyCanary9988776655"
    canary_clause = "Gate S-77 operates at standard atmospheric pressure."

    def _logging_proxy(request: httpx.Request) -> httpx.Response:
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        seen_targets.append((request.url.scheme, request.url.host or "", int(port)))
        path_str = request.url.path
        body = json.loads(request.content.decode("utf-8")) if request.content else {}

        if path_str.endswith(":embedContent"):
            vec = build_fake_embedding_vector(body)
            return httpx.Response(200, json={"embedding": {"values": vec}})

        sys_parts = body.get("systemInstruction", {}).get("parts", [{}])
        raw_sys = str(sys_parts[0].get("text", "")).lower() if sys_parts else ""
        if "mandate:" in raw_sys or "you are acting as" in raw_sys:
            job = "personas"
        elif "triage" in raw_sys or "r-score" in raw_sys:
            job = "intake"
        elif "claim" in raw_sys or "extract" in raw_sys:
            job = "claim_extraction"
        else:
            job = "writer"
        model_id = path_str.rsplit("/models/", 1)[-1].split(":", 1)[0]
        return httpx.Response(200, json=upstream_stub._build_default_generate(model_id, body, job))

    stores = open_stores(tmp_path / "data", enable_vec=False)
    try:
        ops_repo = OpsRepository(stores.ops)
        ev_repo = EvidenceRepository(stores.evidence, vec_enabled=False)
        sess_repo = SessionRepository(stores.sessions)
        rcpt_repo = ReceiptRepository(stores.receipts)
        reg_repo = RegistryRepository(stores.registry)

        def _sink(ev: EgressEvent) -> None:
            ops_repo.record_egress(
                host=ev.host,
                bytes_out=ev.bytes_out,
                bytes_in=ev.bytes_in,
                is_allowed=ev.is_allowed,
                logged_utc=ev.logged_utc,
            )

        async with EgressClient(
            cfg.egress,
            sink=_sink,
            transport=httpx.MockTransport(_logging_proxy),
        ) as egress:
            gemini = GeminiAdapter(egress, model_reg, api_key=canary_secret)
            emb = EmbeddingService(gemini, model_reg)
            ev_svc = EvidenceService(ev_repo, emb)
            extractor = ClaimExtractor(gemini, model_reg)
            verifier = ClaimVerifier(DeterministicLexicalNliScorer(), ev_svc)
            fn_reg = FunctionRegistry(cfg.functions, cfg.profiles)
            register_phase1_functions(fn_reg, cfg.notices)
            key_mgr = Ed25519KeyManager(rcpt_repo, keys_dir=tmp_path / "keys")
            sealer = ReceiptSealer(rcpt_repo, key_mgr)
            snapshot = load_registry(
                CONFIG_DIR / "registry",
                overlay_dir=CONFIG_DIR / "pilots" / "warehouse_substitution",
            )
            centroid_cat = load_failure_centroids(
                CONFIG_DIR / "intake" / "dev_failure_centroids.yaml"
            )
            intake_router = IntakeRouter(
                tiers_config=cfg.tiers,
                model_registry=model_reg,
                model_port=FakeModel(registry=model_reg),
                embedding_service=emb,
                centroid_catalog=centroid_cat,
            )

            await ev_svc.register_document(
                title="Egress Attestation Primary Spec",
                authority_class="primary_text",
                content_text=canary_clause,
                valid_from="2026-11-01",
                api_key=canary_secret,
            )
            req = translate_generate_request(
                model="dle-13axis-strict",
                body={"contents": [{"role": "user", "parts": [{"text": canary_clause}]}]},
                tenant="egress-audit",
            )
            res = await run_governed_workflow(
                run_req=req,
                config=cfg,
                function_registry=fn_reg,
                model_registry=model_reg,
                model_port=gemini,
                evidence_service=ev_svc,
                claim_extractor=extractor,
                claim_verifier=verifier,
                receipt_sealer=sealer,
                ops_repo=ops_repo,
                session_repo=sess_repo,
                calibration=DEFAULT_PHASE2_CALIBRATION,
                api_key=canary_secret,
                registry_snapshot=snapshot,
                enable_ppr=True,
                registry_repo=reg_repo,
                tool_bridge=ToolBridge(),
                intake_router=intake_router,
                triage_override={"d": 1, "r": 1, "m": 0, "binding": False, "z_hit": False},
            )
            assert res.release_mode in ("released", "held")
            assert res.notice_id != "NOTICE-HOLD-07"
            assert len(seen_targets) >= 5

            # Verify every single transport attempt hit ONLY allowed Gemini HTTPS:443
            assert seen_targets
            assert set(seen_targets) == {("https", "generativelanguage.googleapis.com", 443)}

            # Verify unlisted hosts, wrong ports, and cleartext HTTP are blocked fail-closed
            for blocked_url in (
                "https://evil.example.com/exfil",
                "http://generativelanguage.googleapis.com/v1beta/models",
                "https://generativelanguage.googleapis.com:8443/v1beta/models",
                "http://169.254.169.254/latest/meta-data",
            ):
                with pytest.raises(EgressDenied):
                    await egress.request("GET", blocked_url)

            # Verify no blocked URL ever touched transport
            assert set(seen_targets) == {("https", "generativelanguage.googleapis.com", 443)}

        rows = ops_repo._conn.execute("SELECT host, is_allowed FROM egress_log").fetchall()
        assert len(rows) == len(seen_targets) + 4
        allowed_rows = [r for r in rows if r["is_allowed"]]
        denied_rows = [r for r in rows if not r["is_allowed"]]
        assert len(allowed_rows) == len(seen_targets)
        assert len(denied_rows) == 4
        assert all(r["host"] == "generativelanguage.googleapis.com" for r in allowed_rows)
        raw_db_dump = json.dumps([dict(r) for r in rows])
        assert canary_secret not in raw_db_dump
        assert canary_clause not in raw_db_dump
    finally:
        stores.close()
