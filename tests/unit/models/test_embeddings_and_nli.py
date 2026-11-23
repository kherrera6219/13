"""Unit tests for M4 Gemini embeddings adapter and M3 NLI scorers."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pytest

from dle.config import load_config
from dle.errors import ConfigError, ModelUnavailable
from dle.models import (
    DeterministicLexicalNliScorer,
    EmbeddingService,
    FakeModel,
    ModelCallResult,
    ModelRegistry,
    OnnxNliScorer,
)


class _BrokenEmbedModel(FakeModel):
    async def embed(
        self,
        model: str,
        payload: object,
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        del model, payload, api_key
        return ModelCallResult(body={"unexpected": {}}, status_code=200, attempts=1)


@pytest.mark.asyncio
async def test_embedding_service_produces_normalized_vectors() -> None:
    """M4 EmbeddingService resolves gemini-embedding-001 and L2-normalizes vectors."""
    cfg = load_config(Path("config"))
    reg = ModelRegistry(cfg.model_pins)
    fake = FakeModel(registry=reg)
    svc = EmbeddingService(fake, reg)

    vec = await svc.embed_text("Cold chain SKU-4429 substitution approved")
    assert len(vec) == 8
    norm = math.sqrt(sum(v * v for v in vec))
    assert norm == pytest.approx(1.0, abs=1e-5)
    assert fake.calls[-1].model == "gemini-embedding-001"

    batch = await svc.embed_batch(["clause A", "clause B"])
    assert len(batch) == 2 and batch[0] != batch[1]

    broken_svc = EmbeddingService(_BrokenEmbedModel(registry=reg), reg)
    with pytest.raises(ModelUnavailable):
        await broken_svc.embed_text("broken upstream payload")


def test_deterministic_lexical_nli_scorer() -> None:
    """DeterministicLexicalNliScorer separates entailment, contradiction, and neutral."""
    scorer = DeterministicLexicalNliScorer()
    assert scorer.is_loaded is True

    entailed = scorer.score(
        "Warehouse policy WH-2026 permits substituting SKU-4429-B for SKU-4429-A.",
        "SKU-4429-B may substitute for SKU-4429-A under policy WH-2026.",
    )
    contradicted = scorer.score(
        "Warehouse policy WH-2026 prohibits substituting SKU-4429-B without signoff.",
        "SKU-4429-B is permitted without signoff under policy WH-2026.",
    )
    unrelated = scorer.score(
        "Warehouse policy WH-2026 covers pallet stacking clearances.",
        "Oceanic shipping tariffs take effect in November.",
    )

    assert entailed.entailment > 0.70 and entailed.contradiction < 0.15
    assert contradicted.contradiction > 0.70 and contradicted.entailment < 0.20
    assert unrelated.neutral > 0.70
    for score in scorer.score_batch([("p", "p"), ("not allowed here", "allowed here")]):
        assert score.entailment + score.contradiction + score.neutral == pytest.approx(
            1.0, abs=1e-4
        )


class _StubInput:
    def __init__(self, name: str) -> None:
        self.name = name


class _StubOnnxSession:
    def get_inputs(self) -> list[_StubInput]:
        return [_StubInput("input_ids"), _StubInput("attention_mask")]

    def run(self, _outputs: object, feeds: dict[str, object]) -> list[np.ndarray]:
        assert "input_ids" in feeds
        return [np.asarray([[3.0, 0.2, -1.0]], dtype=np.float32)]


def test_onnx_nli_scorer_verifies_sha256_fail_closed(tmp_path: Path) -> None:
    """ADR-006 OnnxNliScorer refuses mismatched SHA-256 and scores logits via softmax."""
    model_file = tmp_path / "deberta.onnx"
    raw_bytes = b"synthetic-onnx-payload-bytes"
    model_file.write_bytes(raw_bytes)
    good_sha = hashlib.sha256(raw_bytes).hexdigest()

    with pytest.raises(ConfigError, match="SHA-256 mismatch"):
        OnnxNliScorer(
            model_path=model_file,
            expected_sha256="0" * 64,
            session=_StubOnnxSession(),
        )

    scorer = OnnxNliScorer(
        model_path=model_file,
        expected_sha256=good_sha,
        session=_StubOnnxSession(),
    )
    assert scorer.is_loaded is True
    out = scorer.score("premise text", "hypothesis text")
    assert out.entailment > 0.90
    assert out.entailment + out.contradiction + out.neutral == pytest.approx(1.0, abs=1e-4)
