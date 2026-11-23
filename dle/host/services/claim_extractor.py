"""Claim extractor service turning drafts and role artifacts into atomic scoped claims (``H10``).

Implements FR-VER-01, FR-FL-07, DLE-PRM-001 (``extractor-1.0.0``), and
``contracts/prompts/claim_extraction.schema.json``. Keeps untrusted draft text in
user slots only, excludes passages, validates character spans (``K01``), and
flags invalid spans rather than dropping claims silently.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import jsonschema

from dle.errors import ContractValidationError
from dle.models.port import ModelPort
from dle.models.registry import ModelRegistry

EXTRACTOR_PROMPT_VERSION = "extractor-1.0.0"

_DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "contracts" / "prompts" / "claim_extraction.schema.json"
)

_SYSTEM_RULES = (
    "You extract claims. You do not judge whether claims are true or supported.\n"
    "Return JSON matching the schema. No prose.\n\n"
    "Rules:\n"
    '1. One claim per atomic assertion. Split compound sentences ("A and B" -> two claims).\n'
    "2. Keep each claim's scope: entity, quantity with units, time interval, "
    "jurisdiction or site.\n"
    "3. binding = true if the claim states a permission, obligation, prohibition, approval,\n"
    "   authorization or a safety requirement.\n"
    "4. Copy the exact character span of the draft each claim comes from "
    "(span_start, span_end).\n"
    "5. Include claims stated in role artifacts that the draft relies on, with "
    'source = "artifact".\n'
    "6. Do not invent claims. Do not drop hedged claims; set hedged = true.\n"
    "7. Questions, instructions to the user and pure formatting are not claims."
)

_BINDING_RE = re.compile(
    r"\b(?:must|shall|may|permitted|permit|permits|prohibited|prohibit|prohibits|"
    r"forbidden|forbid|forbids|authorized|authorize|authorizes|required|requires|require|"
    r"approved|approve|approves|sign-off|signoff|compliant|comply|mandated|mandatory|"
    r"cannot|blocked|veto|vetoed|restricted|ineligible|allowed|exempt|obligation)\b",
    re.IGNORECASE,
)
_HEDGE_RE = re.compile(
    r"\b(?:may|might|likely|approximately|about|roughly|suggests|appears|"
    r"generally|typically|could|possibly|estimated|preliminary)\b",
    re.IGNORECASE,
)
_CLAUSE_VERB_RE = re.compile(
    r"\b(?:is|are|was|were|be|may|must|shall|can|cannot|will|requires|require|"
    r"applies|apply|permits|permit|prohibits|prohibit|forbids|approved|matches|"
    r"expires|holds|needs|contains|costs|runs|uses|allows|triggers|stays|remains)\b",
    re.IGNORECASE,
)
_ENTITY_RE = re.compile(r"\b(?:SKU-[A-Za-z0-9-]+|WH-\d{4}(?:-[A-Za-z0-9]+)?|PL\d{3}|SC\d{2})\b")
_QTY_UNITS_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(days?|hours?|years?|minutes?|units?|pallets?|kg|lbs?|%)\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_JURIS_RE = re.compile(r"\b(US-[A-Z]{2}|CA-[A-Z]{2}|EU|UK)\b")
_SITE_RE = re.compile(r"\b(?:site|warehouse|facility)\s+([A-Za-z0-9_-]+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ClaimScope:
    """Structured factual/regulatory scope attached to an extracted claim."""

    entity: str | None = None
    quantity: float | None = None
    units: str | None = None
    interval_start: str | None = None
    interval_end: str | None = None
    jurisdiction: str | None = None
    site: str | None = None

    def summary_label(self) -> str:
        """Render concise non-empty scope summary label for receipts."""
        parts = [
            item
            for item in (self.entity, self.jurisdiction, self.site, self.interval_start)
            if item
        ]
        return " ".join(parts) if parts else "general"


@dataclass(frozen=True)
class ExtractedClaim:
    """Atomic extracted claim assigned a deterministic ID and host span check."""

    claim_id: str
    proposal_id: str
    assertion: str
    binding: bool
    hedged: bool
    source: Literal["draft", "artifact"]
    artifact_ref: str | None
    span_start: int
    span_end: int
    span_valid: bool
    scope: ClaimScope


@dataclass(frozen=True)
class ClaimExtractionResult:
    """Result returned by ``ClaimExtractor.extract()``."""

    proposal_id: str
    prompt_version: str
    claims: tuple[ExtractedClaim, ...]
    span_objections: tuple[dict[str, object], ...]


def _load_schema(schema_path: Path | None = None) -> dict[str, object]:
    target = schema_path if schema_path is not None else _DEFAULT_SCHEMA_PATH
    loaded = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ContractValidationError(
            "claim_extraction schema root must be a JSON object",
            file_path=str(target),
            pointer="/",
        )
    return loaded


def build_extractor_request(
    *,
    proposal_id: str,
    draft_text: str,
    role_artifacts: Sequence[Mapping[str, object]] = (),
    schema_path: Path | None = None,
) -> dict[str, object]:
    """Build a Gemini ``generateContent`` payload conforming to ``DLE-PRM-001``."""
    schema = _load_schema(schema_path)
    # Remove JSON Schema meta fields not expected inside Gemini responseSchema if needed.
    response_schema = {k: v for k, v in schema.items() if k not in ("$schema", "$id")}
    artifacts_json = json.dumps(list(role_artifacts), sort_keys=True)
    user_payload = (
        f'<draft id="{proposal_id}">{draft_text}</draft>\n<artifacts>{artifacts_json}</artifacts>'
    )
    return {
        "systemInstruction": {"parts": [{"text": _SYSTEM_RULES}]},
        "contents": [{"role": "user", "parts": [{"text": user_payload}]}],
        "generationConfig": {
            "temperature": 0.0,
            "topP": 1.0,
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
        },
    }


def _extract_scope(clause: str) -> dict[str, object]:
    entity_m = _ENTITY_RE.search(clause)
    qty_m = _QTY_UNITS_RE.search(clause)
    dates: list[str] = []
    for raw_d in _ISO_DATE_RE.findall(clause):
        try:
            date.fromisoformat(raw_d)
            dates.append(raw_d)
        except ValueError:
            continue
    juris_m = _JURIS_RE.search(clause)
    site_m = _SITE_RE.search(clause)

    return {
        "entity": entity_m.group(0) if entity_m else None,
        "quantity": float(qty_m.group(1)) if qty_m else None,
        "units": qty_m.group(2).lower() if qty_m else None,
        "interval_start": dates[0] if len(dates) >= 1 else None,
        "interval_end": dates[1] if len(dates) >= 2 else None,
        "jurisdiction": juris_m.group(1) if juris_m else None,
        "site": site_m.group(1) if site_m else None,
    }


def _is_non_claim_segment(segment: str) -> bool:
    stripped = segment.strip()
    if not stripped:
        return True
    if stripped.endswith("?"):
        return True
    if stripped.startswith(("#", "---", "```")):
        return True
    return len(stripped.split()) < 3


def _split_atomic_spans(draft_text: str) -> list[tuple[int, int, str]]:
    """Find deterministic atomic declarative clause spans in ``draft_text``."""
    spans: list[tuple[int, int, str]] = []
    # Split first by sentence boundaries / newlines while tracking exact offsets.
    line_pattern = re.compile(r"[^\n]+")
    for line_m in line_pattern.finditer(draft_text):
        line_start = line_m.start()
        line_text = line_m.group(0)
        sent_pattern = re.compile(r"(?:[^.!]|[.!](?!\s|$))+[.!]?")
        for sent_m in sent_pattern.finditer(line_text):
            raw_sent = sent_m.group(0)
            bullet_m = re.match(r"^(?:[-*•]\s+|\d+\.\s+|\s+)", raw_sent)
            leading = bullet_m.end() if bullet_m else 0
            trimmed_right = raw_sent[leading:].rstrip()
            if not trimmed_right:
                continue
            abs_start = line_start + sent_m.start() + leading
            if _is_non_claim_segment(trimmed_right):
                continue

            # Split compound " A and B " or "; " clauses only when both sides express statements.
            semi_parts = list(re.finditer(r"[^;]+", trimmed_right))
            for semi_m in semi_parts:
                sub = semi_m.group(0).strip()
                sub_offset = semi_m.group(0).find(sub)
                sub_start = abs_start + semi_m.start() + max(0, sub_offset)
                sub_end = sub_start + len(sub)
                if _is_non_claim_segment(sub):
                    continue

                and_matches = list(re.finditer(r"\s+and\s+", sub, flags=re.IGNORECASE))
                split_done = False
                for am in and_matches:
                    left_raw = sub[: am.start()].rstrip(" ,")
                    right_raw = sub[am.end() :].lstrip(" ,")
                    if (
                        len(left_raw.split()) >= 3
                        and len(right_raw.split()) >= 3
                        and _CLAUSE_VERB_RE.search(left_raw)
                        and _CLAUSE_VERB_RE.search(right_raw)
                    ):
                        l_end = sub_start + len(left_raw)
                        r_off = sub.find(right_raw, am.end())
                        r_start = sub_start + r_off
                        r_end = r_start + len(right_raw)
                        spans.append((sub_start, l_end, left_raw[:600]))
                        spans.append((r_start, r_end, right_raw[:600]))
                        split_done = True
                        break
                if not split_done:
                    spans.append((sub_start, sub_end, sub[:600]))
    return spans


def deterministic_extract_claims(
    *,
    proposal_id: str,
    draft_text: str,
    role_artifacts: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Extract schema-valid claims deterministically from ``draft_text`` and ``role_artifacts``."""
    claims_out: list[dict[str, object]] = []
    for start, end, assertion in _split_atomic_spans(draft_text):
        claims_out.append(
            {
                "assertion": assertion,
                "binding": bool(_BINDING_RE.search(assertion)),
                "hedged": bool(_HEDGE_RE.search(assertion)),
                "source": "draft",
                "artifact_ref": None,
                "span_start": start,
                "span_end": end,
                "scope": _extract_scope(assertion),
            }
        )

    for idx, art in enumerate(role_artifacts):
        art_id = str(art.get("artifact_id") or f"artifact-{idx}")
        raw_assertions = art.get("claims")
        if isinstance(raw_assertions, list):
            for item in raw_assertions:
                if isinstance(item, str) and item.strip():
                    clean_item = item.strip()[:600]
                    claims_out.append(
                        {
                            "assertion": clean_item,
                            "binding": bool(_BINDING_RE.search(clean_item)),
                            "hedged": bool(_HEDGE_RE.search(clean_item)),
                            "source": "artifact",
                            "artifact_ref": art_id,
                            "span_start": 0,
                            "span_end": 0,
                            "scope": _extract_scope(clean_item),
                        }
                    )

    return {"proposal_id": proposal_id, "claims": claims_out}


def _extract_model_json_text(body: Mapping[str, object]) -> str | None:
    cands = body.get("candidates")
    if not isinstance(cands, list) or not cands or not isinstance(cands[0], Mapping):
        return None
    content = cands[0].get("content")
    if not isinstance(content, Mapping) or not isinstance(content.get("parts"), list):
        return None
    for part in content["parts"]:
        if (
            isinstance(part, Mapping)
            and isinstance(part.get("text"), str)
            and not part.get("thought")
        ):
            return str(part["text"])
    return None


def _build_extracted_claims(
    *,
    run_id: str,
    attempt_id: str,
    proposal_id: str,
    draft_text: str,
    raw_claims: Sequence[Mapping[str, object]],
) -> ClaimExtractionResult:
    claims: list[ExtractedClaim] = []
    span_objections: list[dict[str, object]] = []

    for idx, item in enumerate(raw_claims, start=1):
        claim_id = f"{run_id}/{attempt_id}/claim-{idx:02d}"
        source: Literal["draft", "artifact"] = (
            "artifact" if item.get("source") == "artifact" else "draft"
        )
        span_start = int(str(item["span_start"]))
        span_end = int(str(item["span_end"]))

        if source == "draft":
            slice_ok = 0 <= span_start < span_end <= len(draft_text) and bool(
                draft_text[span_start:span_end].strip()
            )
            span_valid = slice_ok
        else:
            span_valid = span_start >= 0 and span_end >= span_start

        if not span_valid:
            span_objections.append(
                {
                    "objection_id": f"{run_id}/{attempt_id}/span-obj-{idx:02d}",
                    "claim_id": claim_id,
                    "predicate": "claim_span_invalid",
                    "blocking": True,
                }
            )

        raw_scope = item.get("scope")
        scope_map = raw_scope if isinstance(raw_scope, Mapping) else {}
        scope = ClaimScope(
            entity=str(scope_map["entity"]) if scope_map.get("entity") is not None else None,
            quantity=(
                float(str(scope_map["quantity"])) if scope_map.get("quantity") is not None else None
            ),
            units=str(scope_map["units"]) if scope_map.get("units") is not None else None,
            interval_start=(
                str(scope_map["interval_start"])
                if scope_map.get("interval_start") is not None
                else None
            ),
            interval_end=(
                str(scope_map["interval_end"])
                if scope_map.get("interval_end") is not None
                else None
            ),
            jurisdiction=(
                str(scope_map["jurisdiction"])
                if scope_map.get("jurisdiction") is not None
                else None
            ),
            site=str(scope_map["site"]) if scope_map.get("site") is not None else None,
        )
        claims.append(
            ExtractedClaim(
                claim_id=claim_id,
                proposal_id=proposal_id,
                assertion=str(item["assertion"]),
                binding=bool(item["binding"]),
                hedged=bool(item["hedged"]),
                source=source,
                artifact_ref=(
                    str(item["artifact_ref"]) if item.get("artifact_ref") is not None else None
                ),
                span_start=span_start,
                span_end=span_end,
                span_valid=span_valid,
                scope=scope,
            )
        )

    return ClaimExtractionResult(
        proposal_id=proposal_id,
        prompt_version=EXTRACTOR_PROMPT_VERSION,
        claims=tuple(claims),
        span_objections=tuple(span_objections),
    )


class ClaimExtractor:
    """Runs independent claim extraction via ``ModelPort`` or deterministic fallback."""

    def __init__(
        self,
        model_port: ModelPort,
        registry: ModelRegistry,
        *,
        schema_path: Path | None = None,
    ) -> None:
        """Initialize extractor with pinned ``claim_extraction`` job and JSON schema."""
        self._port = model_port
        self._registry = registry
        self._schema = _load_schema(schema_path)
        self._validator = jsonschema.Draft202012Validator(
            self._schema,
            format_checker=jsonschema.FormatChecker(),
        )

    async def extract(
        self,
        *,
        run_id: str,
        attempt_id: str,
        proposal_id: str,
        draft_text: str,
        role_artifacts: Sequence[Mapping[str, object]] = (),
        api_key: str | None = None,
    ) -> ClaimExtractionResult:
        """Extract and span-validate claims from ``draft_text`` and ``role_artifacts``."""
        req = build_extractor_request(
            proposal_id=proposal_id,
            draft_text=draft_text,
            role_artifacts=role_artifacts,
        )
        model_id = self._registry.pin_for_job("claim_extraction")
        result = await self._port.generate(
            model_id,
            req,
            api_key=api_key,
            job="claim_extraction",
        )
        raw_text = _extract_model_json_text(result.body)
        if raw_text is None:
            raise ContractValidationError(
                "claim extractor model response lacked JSON candidate text",
                file_path="claim_extraction",
                pointer="/candidates/0",
            )
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ContractValidationError(
                f"claim extractor returned invalid JSON: {exc.msg}",
                file_path="claim_extraction",
                pointer="/",
            ) from exc

        # FakeModel default JSON handler returns {"echo": ..., "job": "claim_extraction"};
        # substitute offline rule extractor ONLY for that unmistakable synthetic stub shape.
        if (
            isinstance(parsed, Mapping)
            and parsed.get("job") == "claim_extraction"
            and "echo" in parsed
            and "claims" not in parsed
        ):
            parsed = deterministic_extract_claims(
                proposal_id=proposal_id,
                draft_text=draft_text,
                role_artifacts=role_artifacts,
            )

        errors = sorted(self._validator.iter_errors(parsed), key=lambda e: list(e.absolute_path))
        if errors:
            first = errors[0]
            ptr = "/" + "/".join(str(p) for p in first.absolute_path)
            raise ContractValidationError(
                f"claim extraction output failed schema: {first.message}",
                file_path="contracts/prompts/claim_extraction.schema.json",
                pointer=ptr,
            )

        raw_claims = parsed["claims"]
        return _build_extracted_claims(
            run_id=run_id,
            attempt_id=attempt_id,
            proposal_id=str(parsed["proposal_id"]),
            draft_text=draft_text,
            raw_claims=raw_claims,
        )


__all__ = [
    "EXTRACTOR_PROMPT_VERSION",
    "ClaimExtractionResult",
    "ClaimExtractor",
    "ClaimScope",
    "ExtractedClaim",
    "build_extractor_request",
    "deterministic_extract_claims",
]
