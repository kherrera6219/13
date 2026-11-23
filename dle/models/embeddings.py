"""Gemini cloud embedding adapter (``M4``, ADR-011 D3).

Implements dense text embedding generation via ``ModelPort.embed`` pinned to
``gemini-embedding-001`` in ``config/model_pins.yaml``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from dle.errors import ModelUnavailable
from dle.models.port import ModelPort
from dle.models.registry import ModelRegistry


def _l2_normalize(values: Sequence[float]) -> list[float]:
    if not values:
        raise ModelUnavailable("embedding response returned empty vector")
    floats: list[float] = []
    for item in values:
        val = float(item)
        if not math.isfinite(val):
            raise ModelUnavailable("embedding response returned non-finite coordinate")
        floats.append(val)
    norm = math.sqrt(sum(v * v for v in floats))
    if norm <= 0.0:
        raise ModelUnavailable("embedding vector norm must be positive")
    return [v / norm for v in floats]


def _extract_embedding_values(body: Mapping[str, object]) -> list[float]:
    raw_emb = body.get("embedding")
    if isinstance(raw_emb, Mapping) and isinstance(raw_emb.get("values"), list):
        return _l2_normalize([float(x) for x in raw_emb["values"]])
    raw_embs = body.get("embeddings")
    if isinstance(raw_embs, list) and raw_embs and isinstance(raw_embs[0], Mapping):
        vals = raw_embs[0].get("values")
        if isinstance(vals, list):
            return _l2_normalize([float(x) for x in vals])
    raise ModelUnavailable("upstream embedContent response missing 'embedding.values'")


class EmbeddingService:
    """Produces normalized embeddings using the pinned ``embeddings`` model."""

    def __init__(self, model_port: ModelPort, registry: ModelRegistry) -> None:
        """Bind service to a ``ModelPort`` and ``ModelRegistry``."""
        self._port = model_port
        self._registry = registry

    async def embed_text(self, text: str, *, api_key: str | None = None) -> list[float]:
        """Embed a single text string with ``gemini-embedding-001``."""
        model_id = self._registry.pin_for_job("embeddings")
        payload: dict[str, object] = {
            "content": {"parts": [{"text": text}]},
        }
        result = await self._port.embed(model_id, payload, api_key=api_key)
        return _extract_embedding_values(result.body)

    async def embed_batch(
        self,
        texts: Sequence[str],
        *,
        api_key: str | None = None,
    ) -> list[list[float]]:
        """Embed an ordered sequence of texts into normalized vectors."""
        vectors: list[list[float]] = []
        for item in texts:
            vectors.append(await self.embed_text(item, api_key=api_key))
        return vectors


__all__ = ["EmbeddingService"]
