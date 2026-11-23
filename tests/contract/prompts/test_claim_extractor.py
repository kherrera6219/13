"""Golden prompt contract tests for H10 ClaimExtractor (DLE-PRM-001, 30 cases)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from dle.config import load_config
from dle.errors import ContractValidationError
from dle.host.services import ClaimExtractor, build_extractor_request
from dle.models import FakeModel, ModelRegistry

# 30 frozen (draft, expected_claims) pairs including §18 warehouse claims S1, P1, R1-c1.
FROZEN_30_CASES: tuple[tuple[str, list[tuple[str, bool]]], ...] = (
    (
        "SKU-4429-B may substitute for SKU-4429-A under policy WH-2026-Q4.",
        [("SKU-4429-B", True)],
    ),
    (
        "Facility A stores cold pallets at 4 C.",
        [("Facility A stores cold pallets", False)],
    ),
    (
        "QA lead sign-off is required before staging substituted pallets.",
        [("sign-off is required", True)],
    ),
    (
        "SKU-1002-A is currently in stock and SKU-1002-B is approved as reserve.",
        [("SKU-1002-A is currently in stock", False), ("SKU-1002-B is approved", True)],
    ),
    (
        "Emergency shipments must carry lot traceability labels under US-TX rules.",
        [("must carry lot traceability", True)],
    ),
    (
        "Standard ambient docks operate 24 hours per day.",
        [("operate 24 hours", False)],
    ),
    (
        "Unlisted vendors are prohibited from cold-chain pallet swaps.",
        [("prohibited", True)],
    ),
    (
        "Warehouse zone B holds 120 pallets per bay.",
        [("Warehouse zone B holds 120 pallets", False)],
    ),
    (
        "Temperature telemetry suggests cold storage stays below 5 C.",
        [("Temperature telemetry suggests", False)],
    ),
    (
        "Hazardous drum transfers shall remain suspended during dock maintenance.",
        [("shall remain suspended", True)],
    ),
    (
        "Pallet weight averages 450 kg across outbound loads.",
        [("Pallet weight averages 450 kg", False)],
    ),
    (
        "Subcontractor drivers cannot enter bonded cages without escort authorization.",
        [("cannot enter bonded cages", True)],
    ),
    (
        "Dock 4 received 18 containers on 2026-10-15.",
        [("Dock 4 received 18 containers", False)],
    ),
    (
        "Batch release must wait until NLI verification completes.",
        [("must wait", True)],
    ),
    (
        "Annual inventory reconciliation runs during Q4.",
        [("inventory reconciliation runs", False)],
    ),
    (
        "Export pallets for EU destinations require phytosanitary certification.",
        [("require phytosanitary certification", True)],
    ),
    (
        "Packaging spec v3.13 uses recycled fiberboard trays.",
        [("Packaging spec v3.13 uses", False)],
    ),
    (
        "Operators are allowed to substitute SKU-7780-B for SKU-7780-A with QA notice.",
        [("allowed to substitute", True)],
    ),
    (
        "Conveyor line 3 runs at 60 units per minute.",
        [("Conveyor line 3 runs", False)],
    ),
    (
        "Expired lot codes are forbidden in hospital deliveries.",
        [("forbidden", True)],
    ),
    (
        "Warehouse supervisor review takes approximately 2 hours.",
        [("takes approximately 2 hours", False)],
    ),
    (
        "Binding policy WH-2026-Q4 applies to all refrigerated orders.",
        [("WH-2026-Q4 applies", False)],
    ),
    (
        "Damaged wraps must be quarantined in bay 9 before inspection.",
        [("must be quarantined", True)],
    ),
    (
        "Audit archives remain immutable for 7 years.",
        [("remain immutable for 7 years", False)],
    ),
    (
        "Non-compliant shipments are blocked until QA signoff.",
        [("signoff", True)],
    ),
    (
        "Forklift batteries charge in bay 12 overnight.",
        [("charge in bay 12", False)],
    ),
    (
        "Retail returns are restricted to inspected lots under CA-ON guidelines.",
        [("restricted", True)],
    ),
    (
        "Receiving dock logs record arrival UTC timestamps.",
        [("Receiving dock logs record", False)],
    ),
    (
        "Cold-chain excursions must trigger an immediate quarantine hold.",
        [("must trigger an immediate quarantine", True)],
    ),
    (
        "# Summary\n\nShould we verify lot codes?\n\nPrimary policy WH-2026 permits lot reboxing.",
        [("permits lot reboxing", True)],
    ),
)


def test_extractor_request_security_and_schema() -> None:
    """DLE-PRM-001: untrusted draft stays in user tag, never system; no passages sent."""
    req = build_extractor_request(
        proposal_id="prop-1",
        draft_text="Draft sentence under test.",
        role_artifacts=[{"artifact_id": "art-1", "claims": ["Artifact statement applies."]}],
    )
    sys_parts = req["systemInstruction"]["parts"]  # type: ignore[index]
    user_parts = req["contents"][0]["parts"]  # type: ignore[index]
    assert "Draft sentence" not in sys_parts[0]["text"]
    assert '<draft id="prop-1">Draft sentence under test.</draft>' in user_parts[0]["text"]
    assert "passages" not in user_parts[0]["text"].lower()
    assert req["generationConfig"]["temperature"] == 0.0  # type: ignore[index]
    assert req["generationConfig"]["responseMimeType"] == "application/json"  # type: ignore[index]


@pytest.mark.asyncio
async def test_claim_extractor_golden_30_recall_and_span_validity() -> None:
    """Measured over 30 frozen pairs: recall >= 0.95, binding recall >= 0.98, 100% span valid."""
    cfg = load_config(Path("config"))
    reg = ModelRegistry(cfg.model_pins)
    fake = FakeModel(registry=reg)
    extractor = ClaimExtractor(fake, reg)

    total_expected = 0
    matched_claims = 0
    total_binding = 0
    matched_binding = 0

    for idx, (draft_text, expected) in enumerate(FROZEN_30_CASES):
        res = await extractor.extract(
            run_id="run-golden",
            attempt_id=f"att-{idx}",
            proposal_id=f"p-{idx}",
            draft_text=draft_text,
        )
        assert all(c.span_valid for c in res.claims)
        assert not res.span_objections
        for c in res.claims:
            assert draft_text[c.span_start : c.span_end].strip() != ""

        for expected_sub, expected_binding in expected:
            total_expected += 1
            if expected_binding:
                total_binding += 1
            hit = next((c for c in res.claims if expected_sub in c.assertion), None)
            if hit is not None:
                matched_claims += 1
                if not expected_binding or hit.binding:
                    matched_binding += 1

    claim_recall = matched_claims / total_expected
    binding_recall = matched_binding / total_binding
    assert claim_recall >= 0.95
    assert binding_recall >= 0.98


@pytest.mark.asyncio
async def test_claim_extractor_flags_invalid_spans_and_rejects_bad_schema() -> None:
    """Invalid spans remain flagged with objections; malformed LLM JSON fails closed."""
    cfg = load_config(Path("config"))
    reg = ModelRegistry(cfg.model_pins)
    fake = FakeModel(registry=reg)
    extractor = ClaimExtractor(fake, reg)

    schema = json.loads(
        Path("contracts/prompts/claim_extraction.schema.json").read_text(encoding="utf-8")
    )
    bad_span_payload = {
        "proposal_id": "p-bad",
        "claims": [
            {
                "assertion": "Valid sentence from draft.",
                "binding": False,
                "hedged": False,
                "source": "draft",
                "artifact_ref": None,
                "span_start": 999,
                "span_end": 1005,
                "scope": {
                    "entity": None,
                    "quantity": None,
                    "units": None,
                    "interval_start": None,
                    "interval_end": None,
                    "jurisdiction": None,
                    "site": None,
                },
            }
        ],
    }
    jsonschema.validate(bad_span_payload, schema)
    fake.enqueue_response(
        {"candidates": [{"content": {"parts": [{"text": json.dumps(bad_span_payload)}]}}]}
    )
    out = await extractor.extract(
        run_id="r-span",
        attempt_id="att-0",
        proposal_id="p-bad",
        draft_text="Short draft.",
    )
    assert len(out.claims) == 1
    assert out.claims[0].span_valid is False
    assert len(out.span_objections) == 1
    assert out.span_objections[0]["predicate"] == "claim_span_invalid"

    fake.enqueue_response({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})
    with pytest.raises(ContractValidationError):
        await extractor.extract(
            run_id="r-err",
            attempt_id="att-0",
            proposal_id="p-err",
            draft_text="Short draft.",
        )
