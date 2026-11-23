"""Unit tests for JCS history-hash session resolution (P1-08, FR-SES-01..03)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dle.edge.sessions import (
    MAX_EXPLICIT_SESSION_LEN,
    InMemorySessionStore,
    resolve_session_id,
    session_id_after_response,
)
from dle.errors import SessionError


def test_turn2_matches_post_turn1_response_session_id():
    """T-UNIT-SES-01: Turn 2 incoming hash equals Turn 1 post-response hash."""
    turn1_user = {"role": "user", "parts": [{"text": "What is the cutoff policy?"}]}
    turn1_model = {"role": "model", "parts": [{"text": "Alpha is 0.05."}]}
    sys_inst = {"parts": [{"text": "Be concise."}]}

    after_t1 = session_id_after_response(
        tenant="tenant-a",
        model="dle-13axis-strict",
        system_instruction=sys_inst,
        contents=[turn1_user],
        response_content=turn1_model,
    )
    turn2_sid = resolve_session_id(
        tenant="tenant-a",
        model="models/dle-13axis-strict",
        system_instruction=sys_inst,
        contents=[turn1_user, turn1_model, {"role": "user", "parts": [{"text": "And retries?"}]}],
    )
    assert len(after_t1) == 64
    assert turn2_sid == after_t1


def test_system_instruction_model_and_tenant_isolate_sessions():
    """T-UNIT-SES-02: changing systemInstruction, model, or tenant changes session ID."""
    contents = [
        {"role": "user", "parts": [{"text": "q1"}]},
        {"role": "model", "parts": [{"text": "a1"}]},
        {"role": "user", "parts": [{"text": "q2"}]},
    ]
    base = resolve_session_id(
        tenant="t1",
        model="gemini-4-carbon",
        system_instruction={"parts": [{"text": "sys A"}]},
        contents=contents,
    )
    diff_sys = resolve_session_id(
        tenant="t1",
        model="gemini-4-carbon",
        system_instruction={"parts": [{"text": "sys B"}]},
        contents=contents,
    )
    diff_model = resolve_session_id(
        tenant="t1",
        model="gemini-4-neon",
        system_instruction={"parts": [{"text": "sys A"}]},
        contents=contents,
    )
    diff_tenant = resolve_session_id(
        tenant="t2",
        model="gemini-4-carbon",
        system_instruction={"parts": [{"text": "sys A"}]},
        contents=contents,
    )
    assert len({base, diff_sys, diff_model, diff_tenant}) == 4


def test_jcs_key_order_invariance_and_function_response_continuity():
    """T-UNIT-SES-03: key order preserves session ID and functionResponse resumes parked run."""
    turn1 = {"role": "user", "parts": [{"text": "check inventory"}]}
    call_turn = {
        "role": "model",
        "parts": [{"functionCall": {"name": "get_stock", "args": {"sku": "W1", "loc": "A"}}}],
    }

    parked_sid = session_id_after_response(
        tenant="t1",
        model="dle-13axis-strict",
        system_instruction=None,
        contents=[turn1],
        response_content=call_turn,
    )

    reordered_turn = {
        "parts": [{"functionCall": {"args": {"loc": "A", "sku": "W1"}, "name": "get_stock"}}],
        "role": "model",
    }
    resumed_sid = resolve_session_id(
        tenant="t1",
        model="dle-13axis-strict",
        system_instruction=None,
        contents=[
            turn1,
            reordered_turn,
            {
                "role": "function",
                "parts": [{"functionResponse": {"name": "get_stock", "response": {"qty": 12}}}],
            },
        ],
    )
    assert resumed_sid == parked_sid


def test_explicit_header_override_and_validation():
    """T-UNIT-SES-04: X-DLE-Session overrides hash and enforces length/non-empty rules."""
    assert (
        resolve_session_id(
            tenant="t1",
            model="gemini-4-carbon",
            system_instruction=None,
            contents=[],
            explicit_session="custom-session-42",
        )
        == "custom-session-42"
    )
    with pytest.raises(SessionError, match="empty"):
        resolve_session_id(
            tenant="t1",
            model="gemini-4-carbon",
            system_instruction=None,
            contents=[],
            explicit_session="   ",
        )
    with pytest.raises(SessionError, match="exceeds limit"):
        resolve_session_id(
            tenant="t1",
            model="gemini-4-carbon",
            system_instruction=None,
            contents=[],
            explicit_session="x" * (MAX_EXPLICIT_SESSION_LEN + 1),
        )


def test_in_memory_session_store_ttl_and_purge():
    """T-UNIT-SES-05: InMemorySessionStore tracks TTL and purges expired records cleanly."""
    store = InMemorySessionStore(expiry_hours=2.0)
    t0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    store.touch("s1", tenant="t1", model="models/gemini-4-carbon", now=t0)
    store.touch("s2", tenant="t1", model="gemini-4-neon", now=t0 + timedelta(hours=1.5))

    assert store.get("s1") is not None
    purged = store.purge_expired(now=t0 + timedelta(hours=2.5))
    assert purged == 1
    assert store.get("s1") is None
    assert store.get("s2") is not None
