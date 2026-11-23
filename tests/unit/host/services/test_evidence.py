"""Unit tests for H5 EvidenceService (DVSS-K05, DVSS-K06, contracts/functions/k05)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import jsonschema
import pytest

from dle.config import load_config
from dle.errors import ContractValidationError
from dle.host.services import EvidenceService
from dle.models import EmbeddingService, FakeModel, ModelRegistry
from dle.store import EvidenceRepository, open_stores
from dle.temporal import Interval


def _build_service() -> tuple[EvidenceService, object]:
    bundle = open_stores(None, enable_vec=True)
    cfg = load_config(Path("config"))
    reg = ModelRegistry(cfg.model_pins)
    emb = EmbeddingService(FakeModel(registry=reg), reg)
    svc = EvidenceService(EvidenceRepository(bundle.evidence, vec_enabled=True), emb)
    return svc, bundle


@pytest.mark.asyncio
async def test_k05_register_hybrid_retrieve_and_idempotency() -> None:
    """T-UNIT-FN-K05-01..02: register chunks + FTS5/vec hybrid retrieve + idempotency cache."""
    svc, bundle = _build_service()
    try:
        src = await svc.register_document(
            title="Cold Chain SOP WH-2026",
            authority_class="binding_instrument",
            jurisdiction="US-TX",
            valid_from="2026-01-01",
            valid_to=None,
            content_text=(
                "SKU-4429-B may substitute for SKU-4429-A when cold-chain packaging matches.\n\n"
                "QA lead sign-off is required before staging substituted pallets."
            ),
        )
        assert src["authorityClass"] == "binding_instrument"

        first = await svc.retrieve(
            query="SKU-4429-B cold-chain substitution",
            scope_interval=Interval(date(2026, 6, 1), date(2026, 6, 2), "date"),
            idempotency_key="idem-k05-1",
        )
        assert first.attempted is True
        assert first.from_cache is False
        assert len(first.passages) >= 1
        assert "SKU-4429-B" in first.passages[0].text

        second = await svc.retrieve(
            query="SKU-4429-B cold-chain substitution",
            idempotency_key="idem-k05-1",
        )
        assert second.attempted is False
        assert second.from_cache is True
        assert [p.passage_id for p in second.passages] == [p.passage_id for p in first.passages]
    finally:
        bundle.close()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_k06_temporal_filtering_and_boundary_days() -> None:
    """T-UNIT-FN-K05-03: K06 excludes superseded passages on boundary day and keeps historical."""
    svc, bundle = _build_service()
    try:
        await svc.register_document(
            title="Legacy Rule 2025",
            authority_class="binding_instrument",
            valid_from="2025-01-01",
            valid_to="2026-06-01",
            content_text="Legacy SKU-4429 substitution rule for 2025 operations.",
            source_id="src-legacy",
        )
        await svc.register_document(
            title="Current Rule 2026",
            authority_class="binding_instrument",
            valid_from="2026-06-01",
            valid_to=None,
            content_text="Current SKU-4429 substitution rule effective June 2026.",
            source_id="src-current",
        )

        # Boundary day 2026-06-01: [2025-01-01, 2026-06-01) is excluded; [2026-06-01, None) is kept.
        current_res = await svc.retrieve(
            query="SKU-4429 substitution rule",
            scope_interval=Interval(date(2026, 6, 1), date(2026, 6, 2), "date"),
            idempotency_key="scope-current",
        )
        assert {p.source_id for p in current_res.passages} == {"src-current"}
        assert any(
            item["passage_id"].startswith("src-legacy@") for item in current_res.excluded_temporal
        )

        # Historical query in 2025 recovers legacy rule.
        past_res = await svc.retrieve(
            query="SKU-4429 substitution rule",
            scope_interval=Interval(date(2025, 10, 1), date(2025, 10, 2), "date"),
            idempotency_key="scope-past",
        )
        assert {p.source_id for p in past_res.passages} == {"src-legacy"}

        with pytest.raises(ContractValidationError):
            await svc.register_document(
                title="Inverted Interval",
                authority_class="primary_text",
                valid_from="2026-06-01",
                valid_to="2026-06-01",
                content_text="Empty interval",
            )
    finally:
        bundle.close()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_k05_binding_authority_check_and_contract_schemas() -> None:
    """T-UNIT-FN-K05-04..05: verify_binding_authority statuses & k05 schema validation."""
    svc, bundle = _build_service()
    try:
        await svc.register_document(
            title="Blog Commentary",
            authority_class="unhydrated_synthesis",
            valid_from="2026-01-01",
            content_text="Commentary claiming SKU-4429 substitution is fine.",
            source_id="src-blog",
        )
        res = await svc.retrieve(query="SKU-4429 substitution")

        missing_auth = svc.verify_binding_authority(
            claim_id="c1",
            assertion="SKU-4429 substitution is authorized",
            binding=True,
            passages=res.passages,
        )
        assert missing_auth.status == "not_found"

        unavail = svc.verify_binding_authority(
            claim_id="c1",
            assertion="SKU-4429 substitution is authorized",
            binding=True,
            passages=res.passages,
            source_unavailable=True,
        )
        assert unavail.status == "unavailable"

        non_binding = svc.verify_binding_authority(
            claim_id="c2",
            assertion="Warehouse operates 24 hours",
            binding=False,
            passages=res.passages,
        )
        assert non_binding.status == "not_applicable"

        await svc.register_document(
            title="Signed Approval SOP",
            authority_class="binding_instrument",
            valid_from="2026-01-01",
            content_text="Approved binding rule: SKU-4429 substitution authorized with signoff.",
            source_id="src-sop",
        )
        res2 = await svc.retrieve(query="SKU-4429 substitution authorized", idempotency_key="r2")
        verified = svc.verify_binding_authority(
            claim_id="c1",
            assertion="SKU-4429 substitution is authorized",
            binding=True,
            passages=res2.passages,
        )
        assert verified.status == "verified"
        assert verified.supporting_passage_ids

        # Validate contract I/O payloads against k05.in.json and k05.out.json
        in_schema = json.loads(Path("contracts/functions/k05.in.json").read_text(encoding="utf-8"))
        out_schema = json.loads(
            Path("contracts/functions/k05.out.json").read_text(encoding="utf-8")
        )
        jsonschema.validate(
            {
                "mode": "retrieve",
                "idempotency_key": "r2",
                "query": "SKU-4429 substitution authorized",
                "scope_start": "2026-06-01",
                "scope_end": None,
                "limit": 8,
            },
            in_schema,
        )
        jsonschema.validate(
            {
                "idempotency_key": res2.idempotency_key,
                "attempted": res2.attempted,
                "succeeded": res2.succeeded,
                "from_cache": res2.from_cache,
                "passages": [
                    {
                        "passage_id": p.passage_id,
                        "source_id": p.source_id,
                        "authority_class": p.authority_class,
                        "revision": p.revision,
                        "locator": p.locator,
                        "content_sha256": p.content_sha256,
                        "valid_from": p.valid_from,
                        "valid_to": p.valid_to,
                        "active_in_scope": p.active_in_scope,
                        "score": p.score,
                    }
                    for p in res2.passages
                ],
                "authority_checks": [
                    {
                        "claim_id": verified.claim_id,
                        "status": verified.status,
                        "supporting_passage_ids": list(verified.supporting_passage_ids),
                    }
                ],
            },
            out_schema,
        )
    finally:
        bundle.close()  # type: ignore[attr-defined]
