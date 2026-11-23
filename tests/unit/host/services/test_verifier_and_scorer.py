"""Unit tests for H13 Scorer (DVSS-K08, F-SCORE-01) and H12 ClaimVerifier (DVSS-P04)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import jsonschema
import pytest

from dle.config import load_config
from dle.host.services import (
    ClaimScope,
    ClaimVerifier,
    EvidenceService,
    ExtractedClaim,
    ScoredClaim,
    compute_terminal_u,
    detect_contradictions,
    source_age_decay,
)
from dle.models import DeterministicLexicalNliScorer, EmbeddingService, FakeModel, ModelRegistry
from dle.store import EvidenceRepository, open_stores


def test_source_age_decay_and_terminal_u_match_white_paper_examples() -> None:
    """T-UNIT-FN-K08-01: reproduces white paper §16a exact worked values for b_i and u."""
    b1 = source_age_decay(
        provenance_prior=0.95, active_in_scope=True, age_years=0.3, decay_lambda=0.05
    )
    b2 = source_age_decay(
        provenance_prior=1.00, active_in_scope=True, age_years=0.5, decay_lambda=0.05
    )
    b3 = source_age_decay(
        provenance_prior=1.00, active_in_scope=True, age_years=1.0, decay_lambda=0.01
    )

    assert b1 == pytest.approx(0.9359, abs=1e-4)
    assert b2 == pytest.approx(0.9753, abs=1e-4)
    assert b3 == pytest.approx(0.9900, abs=1e-4)
    assert (
        source_age_decay(
            provenance_prior=1.0, active_in_scope=False, age_years=0.0, decay_lambda=0.05
        )
        == 0.0
    )

    claims = [
        ScoredClaim(
            claim_id="c1",
            proposal_id="p0",
            assertion="Clause in executed contract",
            binding=True,
            scope_label="general",
            passage_ids=("p1",),
            entailment=0.972,
            provenance=0.95,
            belief=b1,
            support_z=0.95 * 0.972,
            contradiction=0.01,
            authority_status="verified",
            span_start=0,
            span_end=20,
        ),
        ScoredClaim(
            claim_id="c2",
            proposal_id="p0",
            assertion="Provision in primary text",
            binding=True,
            scope_label="general",
            passage_ids=("p2",),
            entailment=0.990,
            provenance=1.00,
            belief=b2,
            support_z=0.990,
            contradiction=0.01,
            authority_status="verified",
            span_start=21,
            span_end=40,
        ),
        ScoredClaim(
            claim_id="c3",
            proposal_id="p0",
            assertion="Definition in primary text",
            binding=False,
            scope_label="general",
            passage_ids=("p3",),
            entailment=0.9666,
            provenance=1.00,
            belief=b3,
            support_z=0.9666,
            contradiction=0.01,
            authority_status="not_applicable",
            span_start=41,
            span_end=60,
        ),
    ]

    score_clean = compute_terminal_u(claims, open_objections=0, total_objections=2)
    assert score_clean.u == pytest.approx(0.0547, abs=5e-4)
    assert score_clean.weakest_claim_id == "c1"

    score_half = compute_terminal_u(claims, open_objections=1, total_objections=2)
    assert score_half.u == pytest.approx(0.1297, abs=5e-4)

    empty_score = compute_terminal_u([], open_objections=0, total_objections=0)
    assert empty_score.u == 1.0

    # Validate k08 contract schema pair.
    in_s = json.loads(Path("contracts/functions/k08.in.json").read_text(encoding="utf-8"))
    out_s = json.loads(Path("contracts/functions/k08.out.json").read_text(encoding="utf-8"))
    jsonschema.validate(
        {"provenance_prior": 0.95, "active_in_scope": True, "age_years": 0.3, "decay_lambda": 0.05},
        in_s,
    )
    jsonschema.validate({"belief": round(b1, 4)}, out_s)


@pytest.mark.asyncio
async def test_verifier_contradiction_detection_and_grounding_metadata() -> None:
    """H12 verifies entailed claims, emits DVSS-P04 contradictions, and builds groundingMetadata."""
    bundle = open_stores(None, enable_vec=True)
    try:
        cfg = load_config(Path("config"))
        reg = ModelRegistry(cfg.model_pins)
        emb = EmbeddingService(FakeModel(registry=reg), reg)
        ev_svc = EvidenceService(EvidenceRepository(bundle.evidence, vec_enabled=True), emb)
        await ev_svc.register_document(
            title="Primary Policy WH-2026",
            authority_class="primary_text",
            valid_from="2026-01-01",
            content_text="SKU-4429-B may substitute for SKU-4429-A under policy WH-2026.",
            source_id="src-wh",
        )
        retrieved = await ev_svc.retrieve(query="SKU-4429-B substitute WH-2026")
        nli = DeterministicLexicalNliScorer()
        verifier = ClaimVerifier(nli, ev_svc)

        draft = (
            "SKU-4429-B is permitted for SKU-4429-A under policy WH-2026. "
            "SKU-4429-B is prohibited under policy WH-2026."
        )
        c1 = ExtractedClaim(
            claim_id="r1/a0/claim-01",
            proposal_id="p0",
            assertion="SKU-4429-B is permitted for SKU-4429-A under policy WH-2026",
            binding=True,
            hedged=False,
            source="draft",
            artifact_ref=None,
            span_start=0,
            span_end=60,
            span_valid=True,
            scope=ClaimScope(entity="SKU-4429-B"),
        )
        c2 = ExtractedClaim(
            claim_id="r1/a0/claim-02",
            proposal_id="p0",
            assertion="SKU-4429-B is prohibited for SKU-4429-A under policy WH-2026",
            binding=True,
            hedged=False,
            source="draft",
            artifact_ref=None,
            span_start=62,
            span_end=len(draft),
            span_valid=True,
            scope=ClaimScope(entity="SKU-4429-B"),
        )

        direct_contras = detect_contradictions([c1, c2], nli)
        assert len(direct_contras) == 1

        res = verifier.verify(
            claims=[c1, c2],
            passages=retrieved.passages,
            draft_text=draft,
            as_of=date(2026, 7, 1),
        )
        assert res.scored_claims[0].support_z > 0.70
        assert res.scored_claims[0].authority_status == "verified"
        assert len(res.contradictions) >= 1
        assert len(res.grounding_metadata["groundingChunks"]) >= 1  # type: ignore[arg-type]
        assert res.grounding_metadata["groundingSupports"]  # type: ignore[index]
        first_chunk = res.grounding_metadata["groundingChunks"][0]  # type: ignore[index]
        assert first_chunk["retrievedContext"]["uri"].startswith("dle://source/src-wh@rev-1#")

        p04_in = json.loads(Path("contracts/functions/p04.in.json").read_text(encoding="utf-8"))
        p04_out = json.loads(Path("contracts/functions/p04.out.json").read_text(encoding="utf-8"))
        jsonschema.validate({"claim_count": 2, "threshold": 0.65}, p04_in)
        jsonschema.validate(
            {
                "contradictions": [
                    {
                        "claim_a_id": direct_contras[0].claim_a_id,
                        "claim_b_id": direct_contras[0].claim_b_id,
                        "reason": direct_contras[0].reason,
                        "score": direct_contras[0].score,
                    }
                ]
            },
            p04_out,
        )
    finally:
        bundle.close()
