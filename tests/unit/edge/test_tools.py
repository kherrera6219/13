"""Unit tests for ToolBridge parallel function calls and TTL purge (P1-11)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dle.edge.tools import ToolBridge, extract_function_calls


def test_parallel_function_calls_preserve_order_and_ids():
    """T-UNIT-TOOLB-01: parallel functionCall parts preserve exact order, IDs, and args."""
    response = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "id": "call-1",
                                "name": "get_stock",
                                "args": {"sku": "A"},
                            }
                        },
                        {
                            "functionCall": {
                                "id": "call-2",
                                "name": "get_price",
                                "args": {"sku": "B"},
                            }
                        },
                    ],
                },
                "finishReason": "STOP",
            }
        ]
    }
    calls = extract_function_calls(response)
    assert len(calls) == 2
    assert [c["id"] for c in calls] == ["call-1", "call-2"]
    assert [c["name"] for c in calls] == ["get_stock", "get_price"]


def test_tool_bridge_park_resume_and_ttl_purge():
    """T-UNIT-TOOLB-02: parked runs resume once and expired parked runs are purged."""
    bridge = ToolBridge(expiry_hours=1.0)
    t0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    parked = bridge.park(
        run_id="run-1",
        session_id="sess-next-1",
        pending_calls=({"id": "c1", "name": "lookup", "args": {}},),
        run_state={"step": "passthrough", "model": "gemini-4-carbon"},
        now=t0,
    )
    assert parked.run_id == "run-1"
    assert bridge.count() == 1

    # Expired session is purged before resume.
    bridge.park(
        run_id="run-expired",
        session_id="sess-old",
        pending_calls=(),
        run_state={},
        now=t0 - timedelta(hours=2),
    )
    assert bridge.count() == 2

    resumed = bridge.resume("sess-next-1", now=t0 + timedelta(minutes=30))
    assert resumed is not None
    assert resumed.run_id == "run-1"
    assert bridge.count() == 0
    assert bridge.purge_expired(now=t0) == 0
