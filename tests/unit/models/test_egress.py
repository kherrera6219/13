"""Unit tests for allowlisted EgressClient (P1-04, NFR-SEC-03, NFR-PRIV-01)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest

from dle.config import load_config
from dle.errors import EgressDenied
from dle.models.egress import EgressClient, EgressEvent
from dle.observability import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_allowed_host_succeeds_logs_sizes_without_secrets():
    """T-UNIT-SEC-01: allowlisted Gemini host transfers payload and never logs bodies/keys."""
    buf = io.StringIO()
    configure_logging(stream=buf, level="INFO")

    seen_events: list[EgressEvent] = []
    canary_header_val = "AIza" + "SyFakeHeaderAndQueryCanary987654"
    canary_prompt = "PROPRIETARY_PROMPT_CANARY_123"
    canary_reply = "PROPRIETARY_RESPONSE_CANARY_456"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "generativelanguage.googleapis.com"
        return httpx.Response(200, json={"reply": canary_reply})

    cfg = load_config(REPO_ROOT / "config")
    async with EgressClient(
        cfg.egress,
        sink=seen_events.append,
        transport=httpx.MockTransport(handler),
    ) as client:
        assert client.is_allowed("https://generativelanguage.googleapis.com/v1beta/models")
        resp = await client.request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-4-neon:generateContent",
            headers={"x-goog-api-key": canary_header_val},
            params={"key": canary_header_val},
            json={"prompt": canary_prompt},
        )
        assert resp.status_code == 200

    assert len(seen_events) == 1
    ev = seen_events[0]
    assert ev.host == "generativelanguage.googleapis.com"
    assert ev.port == 443
    assert ev.is_allowed is True
    assert ev.bytes_out > 0
    assert ev.bytes_in > 0
    assert ev.duration_ms >= 0.0

    raw_logs = buf.getvalue()
    assert canary_header_val not in raw_logs
    assert canary_prompt not in raw_logs
    assert canary_reply not in raw_logs
    record = json.loads(raw_logs.strip())
    assert record["event"] == "egress.completed"
    assert record["host"] == "generativelanguage.googleapis.com"
    assert record["bytes_out"] == ev.bytes_out
    assert record["bytes_in"] == ev.bytes_in


@pytest.mark.asyncio
async def test_unlisted_host_wrong_port_and_http_raise_egress_denied():
    """T-UNIT-SEC-02: deny-by-default blocks unlisted hosts, ports, and non-HTTPS schemes."""
    buf = io.StringIO()
    configure_logging(stream=buf, level="INFO")
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    events: list[EgressEvent] = []
    async with EgressClient(
        [("generativelanguage.googleapis.com", 443)],
        sink=events.append,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(EgressDenied) as exc_info:
            await client.request("GET", "https://evil.example/exfiltrate")
        assert exc_info.value.host == "evil.example"
        assert exc_info.value.port == 443

        with pytest.raises(EgressDenied):
            await client.request("GET", "https://generativelanguage.googleapis.com:8443/v1")

        with pytest.raises(EgressDenied):
            await client.request("GET", "http://generativelanguage.googleapis.com/v1")

    assert called is False
    assert len(events) == 3
    assert all(not ev.is_allowed for ev in events)
    assert "egress.denied" in buf.getvalue()


@pytest.mark.asyncio
async def test_redirects_not_followed_and_stream_enforces_allowlist():
    """T-UNIT-SEC-03: 302 redirects are not followed and stream() enforces allowlist."""
    seen: list[EgressEvent] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"location": "https://evil.example/steal"})
        return httpx.Response(200, content=b"data: chunk1\n\ndata: chunk2\n\n")

    async with EgressClient(
        [("generativelanguage.googleapis.com", 443)],
        sink=seen.append,
        transport=httpx.MockTransport(handler),
    ) as client:
        redirect_resp = await client.request(
            "GET", "https://generativelanguage.googleapis.com/redirect"
        )
        assert redirect_resp.status_code == 302

        async with client.stream(
            "POST", "https://generativelanguage.googleapis.com/stream", json={"ok": True}
        ) as stream_resp:
            body = await stream_resp.aread()
            assert b"chunk1" in body

        with pytest.raises(EgressDenied):
            async with client.stream("GET", "https://not-allowed.example/s"):
                pass

    assert len(seen) == 3
    assert seen[0].is_allowed is True
    assert seen[1].is_allowed is True and seen[1].bytes_in > 0
    assert seen[2].is_allowed is False


@pytest.mark.asyncio
async def test_http_error_logs_exception_class_not_query_secrets():
    """T-UNIT-SEC-04: upstream transport errors record failure without leaking query params."""
    buf = io.StringIO()
    configure_logging(stream=buf, level="INFO")
    canary_query_val = "AIza" + "SyTransportLeakGuard9999999"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    events: list[EgressEvent] = []
    async with EgressClient(
        [("generativelanguage.googleapis.com", 443)],
        sink=events.append,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(httpx.ConnectTimeout):
            await client.request(
                "GET",
                f"https://generativelanguage.googleapis.com/v1?key={canary_query_val}",
            )

    assert len(events) == 1
    assert events[0].is_allowed is True
    assert events[0].bytes_in == 0
    assert canary_query_val not in buf.getvalue()
    assert "ConnectTimeout" in buf.getvalue()
