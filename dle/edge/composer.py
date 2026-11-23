"""Response composer building Gemini responses and ``X-DLE-*`` headers (`E5`).

Implements FR-API-05, FR-API-06, ADR-007, and DVSS-K11 notice rendering.
Held answers return HTTP 200 with ``finishReason: "STOP"`` and rendered notice
text from ``config/notices.yaml``; advisory notices are embedded into the
response text itself.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Literal

from dle.config.models import NoticesConfig, NoticeTemplate

DLE_API_VERSION = "1.0"


class _SafeFormatDict(dict[str, object]):
    def __missing__(self, key: str) -> str:
        return f"<{key}>"


class ResponseComposer:
    """Renders notices and formats pass-through, released, advisory, and held responses."""

    def __init__(self, notices: NoticesConfig) -> None:
        """Index notice templates by ID from ``config/notices.yaml``."""
        self._by_id: dict[str, NoticeTemplate] = {n.id: n for n in notices.notices}

    def render_notice(self, notice_id: str, **context: object) -> tuple[str, str]:
        """Render ``(badge, text)`` for ``notice_id`` with safe fallback placeholders."""
        tmpl = self._by_id.get(notice_id)
        if tmpl is None:
            return ("Notice", f"Verification notice ({notice_id}).")
        rendered = tmpl.text.format_map(_SafeFormatDict(context))
        return (tmpl.badge, rendered)

    def compose_passthrough(
        self,
        upstream_body: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, str]]:
        """Deep-copy an upstream response untouched with ``X-DLE-Release-Mode: passthrough``."""
        body = copy.deepcopy({str(k): v for k, v in upstream_body.items()})
        headers = {
            "X-DLE-Release-Mode": "passthrough",
            "X-DLE-API-Version": DLE_API_VERSION,
        }
        return body, headers

    def compose_governed(
        self,
        *,
        release_mode: Literal["released", "released_advisory", "held"],
        receipt_id: str,
        tier: int,
        body: Mapping[str, object] | None = None,
        notice_id: str | None = None,
        notice_context: Mapping[str, object] | None = None,
        hold_reason: str | None = None,
    ) -> tuple[dict[str, object], dict[str, str]]:
        """Compose a governed Gemini response body and matching ``X-DLE-*`` headers."""
        ctx = dict(notice_context) if notice_context is not None else {}
        headers: dict[str, str] = {
            "X-DLE-Release-Mode": release_mode,
            "X-DLE-Receipt": receipt_id,
            "X-DLE-Tier": str(tier),
            "X-DLE-API-Version": DLE_API_VERSION,
        }

        if release_mode == "held":
            eff_notice_id = notice_id or "NOTICE-HOLD-07"
            ctx.setdefault("receipt_id", receipt_id)
            _badge, notice_text = self.render_notice(eff_notice_id, **ctx)
            held_body: dict[str, object] = {
                "candidates": [
                    {
                        "index": 0,
                        "content": {
                            "role": "model",
                            "parts": [{"text": notice_text}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "dleMetadata": {
                    "releaseMode": "held",
                    "receiptId": receipt_id,
                    "tier": tier,
                    "holdReason": hold_reason or eff_notice_id,
                },
            }
            return held_body, headers

        out_body = copy.deepcopy({str(k): v for k, v in body.items()}) if body is not None else {}
        if release_mode == "released_advisory" and notice_id is not None:
            _badge, advisory_text = self.render_notice(notice_id, **ctx)
            _prepend_text_notice(out_body, advisory_text)

        out_body["dleMetadata"] = {
            "releaseMode": release_mode,
            "receiptId": receipt_id,
            "tier": tier,
        }
        return out_body, headers


def _prepend_text_notice(body: dict[str, object], notice_text: str) -> None:
    candidates = body.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        content = candidates[0].get("content")
        if isinstance(content, dict) and isinstance(content.get("parts"), list):
            parts = content["parts"]
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    part["text"] = f"{notice_text}\n\n{part['text']}"
                    return
            parts.insert(0, {"text": notice_text})
            return
    body["candidates"] = [
        {
            "index": 0,
            "content": {"role": "model", "parts": [{"text": notice_text}]},
            "finishReason": "STOP",
        }
    ]


__all__ = ["DLE_API_VERSION", "ResponseComposer"]
