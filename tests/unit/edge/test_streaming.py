"""Unit tests for SSE keepalive streaming and cancellation (P1-13, NFR-PERF-02)."""

from __future__ import annotations

import asyncio
import json

import pytest

from dle.edge.streaming import split_response_chunks, stream_governed_sse


@pytest.mark.asyncio
async def test_slow_gate_emits_keepalives_then_chunks_with_final_metadata():
    """T-COMPAT-STREAM-01: keepalives precede released chunks and receipt metadata."""

    async def slow_gate():
        await asyncio.sleep(0.08)
        body = {
            "candidates": [
                {
                    "index": 0,
                    "content": {"role": "model", "parts": [{"text": "A" * 25}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"totalTokenCount": 10},
            "dleMetadata": {
                "releaseMode": "released_advisory",
                "receiptId": "rcpt-stream-1",
                "tier": 1,
            },
        }
        return body, {"X-DLE-Tier": "1"}

    frames = [
        frame
        async for frame in stream_governed_sse(
            slow_gate(), keepalive_interval_s=0.02, chunk_size=10
        )
    ]
    keepalives = [f for f in frames if f == ": keepalive\n\n"]
    data_frames = [json.loads(f[6:]) for f in frames if f.startswith("data: ")]

    assert len(keepalives) >= 2
    assert len(data_frames) == 3
    assert (
        "".join(c["candidates"][0]["content"]["parts"][0]["text"] for c in data_frames) == "A" * 25
    )
    assert "dleMetadata" not in data_frames[0]
    assert data_frames[-1]["dleMetadata"]["receiptId"] == "rcpt-stream-1"


@pytest.mark.asyncio
async def test_held_gate_emits_stop_hold_notice_and_handles_cancel():
    """T-COMPAT-STREAM-02: held stream emits notice only; client cancel triggers callback."""

    async def held_gate():
        await asyncio.sleep(0.01)
        return (
            {
                "candidates": [
                    {
                        "index": 0,
                        "content": {"role": "model", "parts": [{"text": "Held: internal error."}]},
                        "finishReason": "STOP",
                    }
                ],
                "dleMetadata": {"releaseMode": "held", "receiptId": "rcpt-h", "tier": 2},
            },
            {},
        )

    frames = [
        f async for f in stream_governed_sse(held_gate(), keepalive_interval_s=0.05, chunk_size=100)
    ]
    assert len(frames) == 1
    chunk = json.loads(frames[0][6:])
    assert chunk["dleMetadata"]["releaseMode"] == "held"
    assert split_response_chunks(chunk, chunk_size=50)[0]["dleMetadata"]["tier"] == 2

    cancelled = False

    def mark_cancelled() -> None:
        nonlocal cancelled
        cancelled = True

    async def stalled_gate():
        await asyncio.sleep(5.0)
        return {}, {}

    stream = stream_governed_sse(
        stalled_gate(), keepalive_interval_s=0.02, on_cancel=mark_cancelled
    )
    first = await anext(stream)
    assert first == ": keepalive\n\n"
    await stream.aclose()
    assert cancelled is True
