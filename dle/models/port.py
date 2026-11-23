"""Model port abstraction decoupling middleware logic from Gemini transport.

Implements FR-API-03 and NFR-REL-02. Both the live ``GeminiAdapter`` and
the deterministic offline ``FakeModel`` satisfy ``ModelPort``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ModelCallResult:
    """Normalized upstream response envelope returned by ``ModelPort`` calls."""

    body: dict[str, object]
    status_code: int = 200
    attempts: int = 1
    model_version: str | None = None


class ModelPort(Protocol):
    """Port interface for model discovery, generation, streaming, token counting, and embeddings."""

    async def list_models(
        self,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """List available upstream models with optional pagination."""
        ...

    async def get_model(
        self,
        model: str,
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """Fetch metadata for one model ID (without or with ``models/`` prefix)."""
        ...

    async def generate(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
        job: str = "passthrough",
    ) -> ModelCallResult:
        """Run non-streaming ``generateContent`` for a given model and request body."""
        ...

    def stream_generate(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
        job: str = "passthrough",
    ) -> AsyncIterator[dict[str, object]]:
        """Stream ``generateContent`` JSON chunks from upstream."""
        ...

    async def count_tokens(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """Forward ``countTokens`` to upstream."""
        ...

    async def embed(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """Invoke ``embedContent`` for text embeddings."""
        ...

    async def is_reachable(self) -> bool:
        """Return whether the backing model endpoint is currently reachable."""
        ...


__all__ = ["ModelCallResult", "ModelPort"]
