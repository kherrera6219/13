"""Unit tests for ResponseComposer headers, STOP holds, and notice embedding (P1-12)."""

from __future__ import annotations

from pathlib import Path

from dle.config import load_config
from dle.edge.composer import DLE_API_VERSION, ResponseComposer

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_composer_hold_returns_stop_with_notice_and_headers():
    """T-CONTRACT-RESP-01: held answers return STOP, notice text, and X-DLE-* headers."""
    cfg = load_config(REPO_ROOT / "config")
    composer = ResponseComposer(cfg.notices)

    body, headers = composer.compose_governed(
        release_mode="held",
        receipt_id="00000000-0000-4000-8000-000000000010",
        tier=2,
        notice_id="NOTICE-HOLD-06",
    )
    assert headers == {
        "X-DLE-Release-Mode": "held",
        "X-DLE-Receipt": "00000000-0000-4000-8000-000000000010",
        "X-DLE-Tier": "2",
        "X-DLE-API-Version": DLE_API_VERSION,
    }
    assert body["candidates"][0]["finishReason"] == "STOP"
    assert "did not respond" in body["candidates"][0]["content"]["parts"][0]["text"]
    assert body["dleMetadata"]["releaseMode"] == "held"


def test_composer_advisory_notice_embedded_and_passthrough_untouched():
    """T-CONTRACT-RESP-02: advisory notice prepends text; passthrough leaves body unchanged."""
    cfg = load_config(REPO_ROOT / "config")
    composer = ResponseComposer(cfg.notices)

    draft = {
        "candidates": [
            {
                "index": 0,
                "content": {"role": "model", "parts": [{"text": "Draft answer."}]},
                "finishReason": "STOP",
            }
        ],
        "extraField": "kept",
    }
    adv_body, adv_headers = composer.compose_governed(
        release_mode="released_advisory",
        receipt_id="rcpt-1",
        tier=3,
        body=draft,
        notice_id="NOTICE-ADV-02",
    )
    assert adv_headers["X-DLE-Release-Mode"] == "released_advisory"
    text = adv_body["candidates"][0]["content"]["parts"][0]["text"]
    assert "recalibrated" in text
    assert "Draft answer." in text

    pt_body, pt_headers = composer.compose_passthrough(draft)
    assert pt_headers["X-DLE-Release-Mode"] == "passthrough"
    assert pt_body == draft
