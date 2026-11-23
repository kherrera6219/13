"""SSE streaming with periodic keepalives while governed verification runs.

Implements FR-API-07, NFR-PERF-02, and ADR-004. Streams SSE comment lines
(``: keepalive``) at least every 10 s while the gate runs, and only emits
``GenerateContentResponse`` chunks after a release/hold decision is reached.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping

from dle.observability import get_logger

DEFAULT_KEEPALIVE_INTERVAL_S = 8.0


def split_response_chunks(
    response_body: Mapping[str, object],
    *,
    chunk_size: int = 120,
) -> list[dict[str, object]]:
    """Split a single text candidate into progressive chunks plus final metadata chunk."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    cloned = copy.deepcopy({str(k): v for k, v in response_body.items()})
    candidates = cloned.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        return [cloned]

    first_cand = candidates[0]
    content = first_cand.get("content")
    if not isinstance(content, dict) or not isinstance(content.get("parts"), list):
        return [cloned]

    parts = content["parts"]
    if (
        len(parts) != 1
        or not isinstance(parts[0], dict)
        or not isinstance(parts[0].get("text"), str)
    ):
        return [cloned]

    full_text = parts[0]["text"]
    if len(full_text) <= chunk_size:
        return [cloned]

    slices = [full_text[i : i + chunk_size] for i in range(0, len(full_text), chunk_size)]
    role = content.get("role", "model")
    index = first_cand.get("index", 0)

    chunks: list[dict[str, object]] = []
    for piece in slices[:-1]:
        chunks.append(
            {
                "candidates": [
                    {
                        "index": index,
                        "content": {"role": role, "parts": [{"text": piece}]},
                    }
                ]
            }
        )

    final_chunk = copy.deepcopy(cloned)
    final_cand = final_chunk["candidates"]
    if isinstance(final_cand, list) and final_cand and isinstance(final_cand[0], dict):
        final_content = final_cand[0].get("content")
        if isinstance(final_content, dict):
            final_content["parts"] = [{"text": slices[-1]}]
    chunks.append(final_chunk)
    return chunks


async def stream_governed_sse(
    gate_awaitable: Awaitable[tuple[dict[str, object], dict[str, str]]],
    *,
    keepalive_interval_s: float = DEFAULT_KEEPALIVE_INTERVAL_S,
    chunk_size: int = 120,
    on_cancel: Callable[[], None] | None = None,
) -> AsyncIterator[str]:
    """Emit SSE keepalives until ``gate_awaitable`` completes, then stream JSON chunks."""
    if keepalive_interval_s <= 0.0 or keepalive_interval_s > 10.0:
        raise ValueError("keepalive_interval_s must be in (0, 10] seconds (NFR-PERF-02)")
    log = get_logger("dle.edge.streaming")

    async def _run_gate() -> tuple[dict[str, object], dict[str, str]]:
        return await gate_awaitable

    task = asyncio.create_task(_run_gate())
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=keepalive_interval_s)
            if not task.done():
                yield ": keepalive\n\n"
        response_body, _headers = task.result()
        for chunk in split_response_chunks(response_body, chunk_size=chunk_size):
            yield f"data: {json.dumps(chunk)}\n\n"
    except (asyncio.CancelledError, GeneratorExit):
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        if on_cancel is not None:
            on_cancel()
        log.info("stream.cancelled")
        raise


__all__ = [
    "DEFAULT_KEEPALIVE_INTERVAL_S",
    "split_response_chunks",
    "stream_governed_sse",
]
