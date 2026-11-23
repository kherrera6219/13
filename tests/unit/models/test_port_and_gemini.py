"""Unit tests for ModelPort, GeminiAdapter retries/errors, and FakeModel (P1-05)."""

from __future__ import annotations

import math
from pathlib import Path

import httpx
import pytest

from dle.config import load_config
from dle.errors import AuthError, ModelUnavailable, UpstreamApiError
from dle.models import EgressClient, FakeModel, GeminiAdapter, ModelPort, ModelRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_registry(*, calibrated: dict[str, str] | None = None) -> ModelRegistry:
    cfg = load_config(REPO_ROOT / "config")
    return ModelRegistry(cfg.model_pins, calibrated_versions=calibrated)


@pytest.mark.asyncio
async def test_gemini_adapter_retries_503_twice_then_succeeds():
    """T-UNIT-MODEL-01: 503 twice then 200 succeeds and records 3 attempts."""
    attempts = 0
    canary_key = "AIza" + "SyUnitRetryCanaryKey1234567890"

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"error": {"message": "busy", "status": "UNAVAILABLE"}})
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "ok"}]},
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": "gemini-4-neon-001",
            },
        )

    reg = _make_registry()
    async with EgressClient(
        [("generativelanguage.googleapis.com", 443)],
        transport=httpx.MockTransport(handler),
    ) as egress:
        adapter: ModelPort = GeminiAdapter(
            egress,
            reg,
            api_key=canary_key,
            base_backoff_s=0.0,
        )
        result = await adapter.generate("gemini-4-neon", {"contents": []})

    assert result.attempts == 3
    assert result.model_version == "gemini-4-neon-001"
    assert reg.observed_versions["gemini-4-neon"] == "gemini-4-neon-001"


@pytest.mark.asyncio
async def test_gemini_adapter_raises_model_unavailable_and_passes_through_4xx():
    """T-UNIT-MODEL-02: 3 consecutive 503s raise ModelUnavailable; 429 fails immediately."""
    reg = _make_registry()
    canary_key = "AIza" + "SyUnitErrorCanaryKey1234567890"

    always_503_calls = 0

    def fail_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal always_503_calls
        always_503_calls += 1
        return httpx.Response(503)

    async with EgressClient(
        [("generativelanguage.googleapis.com", 443)],
        transport=httpx.MockTransport(fail_handler),
    ) as egress:
        adapter = GeminiAdapter(egress, reg, api_key=canary_key, base_backoff_s=0.0)
        with pytest.raises(ModelUnavailable, match="3 attempts"):
            await adapter.generate("gemini-4-carbon", {"contents": []})
    assert always_503_calls == 3

    rate_limit_calls = 0

    def limit_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal rate_limit_calls
        rate_limit_calls += 1
        return httpx.Response(
            429,
            json={
                "error": {"code": 429, "message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}
            },
        )

    async with EgressClient(
        [("generativelanguage.googleapis.com", 443)],
        transport=httpx.MockTransport(limit_handler),
    ) as egress:
        adapter = GeminiAdapter(egress, reg, api_key=canary_key, base_backoff_s=0.0)
        with pytest.raises(UpstreamApiError) as exc_info:
            await adapter.generate("gemini-4-carbon", {"contents": []})
        assert exc_info.value.http_status == 429
        assert exc_info.value.gemini_status == "RESOURCE_EXHAUSTED"
        with pytest.raises(AuthError):
            await GeminiAdapter(egress, reg).generate("gemini-4-carbon", {"contents": []})
    assert rate_limit_calls == 1


@pytest.mark.asyncio
async def test_gemini_adapter_stream_and_fake_model_behavior():
    """T-UNIT-MODEL-03: GeminiAdapter parses SSE stream and FakeModel satisfies ModelPort."""
    reg = _make_registry(calibrated={"gemini-4-carbon": "gemini-4-carbon-001"})
    canary_key = "AIza" + "SyUnitStreamCanaryKey123456789"
    sse_payload = (
        b'data: {"candidates":[{"content":{"role":"model","parts":[{"text":"hi "}]}}],'
        b'"modelVersion":"gemini-4-carbon-002"}\n\n'
        b'data: {"candidates":[{"content":{"role":"model","parts":[{"text":"there"}]},'
        b'"finishReason":"STOP"}],"modelVersion":"gemini-4-carbon-002"}\n\n'
    )

    def stream_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_payload)

    async with EgressClient(
        [("generativelanguage.googleapis.com", 443)],
        transport=httpx.MockTransport(stream_handler),
    ) as egress:
        adapter = GeminiAdapter(egress, reg, api_key=canary_key, base_backoff_s=0.0)
        chunks = [
            chunk async for chunk in adapter.stream_generate("gemini-4-carbon", {"contents": []})
        ]
    assert len(chunks) == 2
    assert reg.drift_latched is True

    fake = FakeModel()
    assert await fake.is_reachable() is True
    page1 = await fake.list_models(page_size=2)
    assert len(page1.body["models"]) == 2
    page2 = await fake.list_models(page_size=2, page_token=str(page1.body["nextPageToken"]))
    assert len(page2.body["models"]) == 1

    gen = await fake.generate(
        "gemini-4-neon",
        {
            "contents": [{"role": "user", "parts": [{"text": "hello world"}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
    )
    assert '"echo": "hello world"' in gen.body["candidates"][0]["content"]["parts"][0]["text"]

    streamed = [
        chunk
        async for chunk in fake.stream_generate(
            "gemini-4-carbon",
            {"contents": [{"role": "user", "parts": [{"text": "stream test message"}]}]},
        )
    ]
    assert len(streamed) == 2
    tokens = await fake.count_tokens(
        "gemini-4-carbon",
        {"contents": [{"role": "user", "parts": [{"text": "one two three"}]}]},
    )
    assert tokens.body["totalTokens"] == 6

    emb = await fake.embed(
        "gemini-embedding-001",
        {"content": {"parts": [{"text": "warehouse substitution"}]}},
    )
    vec = emb.body["embedding"]["values"]
    assert math.isclose(math.sqrt(sum(v * v for v in vec)), 1.0, rel_tol=1e-4)
