"""Unit tests for request translator and DVSS-K01 validation (P1-09, GC-26)."""

from __future__ import annotations

import pytest

from dle.edge.translator import normalize_model_id, translate_generate_request
from dle.errors import ContractValidationError


def test_translate_preserves_unknown_fields_on_passthrough_and_governed_models():
    """T-UNIT-EDGE-01: unmodelled Gemini fields survive round-trip unchanged."""
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Summarize warehouse terms", "customHint": {"k": 1}}],
            }
        ],
        "systemInstruction": {"parts": [{"text": "Cite clauses"}]},
        "tools": [{"functionDeclarations": [{"name": "lookup", "parameters": {"type": "object"}}]}],
        "futureGeminiFlag": {"nested": ["a", "b"], "enabled": True},
    }
    req = translate_generate_request(
        model="models/gemini-4-carbon",
        body=payload,
        tenant="tenant-1",
    )
    assert req.model == "gemini-4-carbon"
    assert req.is_governed is False
    assert req.profile is None
    assert req.raw_body["futureGeminiFlag"] == {"nested": ["a", "b"], "enabled": True}
    assert req.raw_body["contents"][0]["parts"][0]["customHint"] == {"k": 1}

    # Mutating original caller dict does not alter frozen RunRequest copy.
    payload["futureGeminiFlag"]["enabled"] = False  # type: ignore[index]
    assert req.raw_body["futureGeminiFlag"]["enabled"] is True  # type: ignore[index]

    gov = translate_generate_request(
        model="dle-13axis-strict",
        body={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
        tenant="tenant-1",
    )
    assert gov.is_governed is True
    assert gov.profile == "strict"


def test_translate_detects_function_responses_in_latest_turn():
    """T-UNIT-EDGE-02: identifies incoming functionResponse parts cleanly."""
    req = translate_generate_request(
        model="gemini-4-neon",
        body={
            "contents": [
                {"role": "user", "parts": [{"text": "stock check"}]},
                {"role": "model", "parts": [{"functionCall": {"name": "get_stock", "args": {}}}]},
                {
                    "role": "function",
                    "parts": [{"functionResponse": {"name": "get_stock", "response": {"qty": 4}}}],
                },
            ]
        },
        tenant="t1",
    )
    assert req.has_function_responses is True


@pytest.mark.parametrize(
    ("bad_body", "expected_pointer"),
    [
        ("not-an-object", "/"),
        ({}, "/contents"),
        ({"contents": []}, "/contents"),
        ({"contents": [{"role": "system", "parts": [{"text": "x"}]}]}, "/contents/0/role"),
        ({"contents": [{"role": "user", "parts": "bad"}]}, "/contents/0/parts"),
        (
            {"contents": [{"role": "model", "parts": [{"functionCall": {"name": ""}}]}]},
            "/contents/0/parts/0/functionCall",
        ),
        (
            {
                "contents": [
                    {
                        "role": "function",
                        "parts": [{"functionResponse": {"name": "fn", "response": "bad"}}],
                    }
                ]
            },
            "/contents/0/parts/0/functionResponse",
        ),
        (
            {"contents": [{"role": "user", "parts": [{"text": "ok"}]}], "systemInstruction": []},
            "/systemInstruction",
        ),
        ({"contents": [{"role": "user", "parts": [{"text": "ok"}]}], "tools": ["bad"]}, "/tools/0"),
    ],
)
def test_translate_rejects_malformed_requests_with_json_pointer(bad_body, expected_pointer):
    """T-UNIT-EDGE-03: malformed payloads fail DVSS-K01 with ContractValidationError pointer."""
    with pytest.raises(ContractValidationError) as exc_info:
        translate_generate_request(model="gemini-4-carbon", body=bad_body, tenant="t1")
    assert exc_info.value.pointer == expected_pointer


def test_normalize_model_id_and_alt_validation():
    """T-UNIT-EDGE-04: rejects empty model IDs and invalid alt query values."""
    with pytest.raises(ContractValidationError):
        normalize_model_id("models/ ")
    with pytest.raises(ContractValidationError) as exc_info:
        translate_generate_request(
            model="gemini-4-carbon",
            body={"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
            tenant="t1",
            is_streaming=True,
            alt="xml",
        )
    assert exc_info.value.pointer == "/alt"
