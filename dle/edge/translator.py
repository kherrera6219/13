"""Request translator converting Gemini payloads into validated ``RunRequest``s.

Implements FR-API-01, FR-TOOL-01, DVSS-K01 boundary validation, and GC-26
unknown-field pass-through preservation.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from dle.edge.sessions import resolve_session_id
from dle.errors import ContractValidationError

GOVERNED_MODELS: dict[str, str] = {
    "dle-13axis-strict": "strict",
    "dle-13axis-advisory": "advisory",
}

VALID_CONTENT_ROLES: frozenset[str] = frozenset({"user", "model", "function"})
VALID_STREAM_ALTS: frozenset[str] = frozenset({"sse", "json"})


@dataclass(frozen=True)
class RunRequest:
    """Validated internal request model with untouched ``raw_body`` for pass-through."""

    run_id: str
    session_id: str
    tenant: str
    model: str
    is_governed: bool
    profile: str | None
    raw_body: dict[str, object]
    contents: tuple[dict[str, object], ...]
    system_instruction: dict[str, object] | None
    tools: tuple[dict[str, object], ...]
    has_function_responses: bool
    is_streaming: bool
    alt: str | None


def normalize_model_id(model: str) -> str:
    """Strip an optional ``models/`` prefix and validate non-empty model identifier."""
    normalized = model.strip().removeprefix("models/").strip()
    if not normalized:
        raise ContractValidationError(
            "model identifier must not be empty",
            file_path="request",
            pointer="/model",
        )
    return normalized


def _validate_part(part: object, *, turn_idx: int, part_idx: int) -> None:
    if not isinstance(part, Mapping):
        raise ContractValidationError(
            "content part must be a JSON object",
            file_path="request",
            pointer=f"/contents/{turn_idx}/parts/{part_idx}",
        )
    if "functionCall" in part and part["functionCall"] is not None:
        fc = part["functionCall"]
        if not isinstance(fc, Mapping) or not isinstance(fc.get("name"), str) or not fc["name"]:
            raise ContractValidationError(
                "functionCall must be an object with non-empty string 'name'",
                file_path="request",
                pointer=f"/contents/{turn_idx}/parts/{part_idx}/functionCall",
            )
    if "functionResponse" in part and part["functionResponse"] is not None:
        fr = part["functionResponse"]
        if (
            not isinstance(fr, Mapping)
            or not isinstance(fr.get("name"), str)
            or not fr["name"]
            or not isinstance(fr.get("response"), Mapping)
        ):
            raise ContractValidationError(
                "functionResponse must be an object with string 'name' and object 'response'",
                file_path="request",
                pointer=f"/contents/{turn_idx}/parts/{part_idx}/functionResponse",
            )


def _validate_contents(raw_contents: object) -> tuple[dict[str, object], ...]:
    if not isinstance(raw_contents, list) or len(raw_contents) == 0:
        raise ContractValidationError(
            "field 'contents' must be a non-empty array",
            file_path="request",
            pointer="/contents",
        )

    validated: list[dict[str, object]] = []
    for idx, turn in enumerate(raw_contents):
        if not isinstance(turn, Mapping):
            raise ContractValidationError(
                "each contents entry must be an object",
                file_path="request",
                pointer=f"/contents/{idx}",
            )
        role = turn.get("role")
        if role is not None and role not in VALID_CONTENT_ROLES:
            raise ContractValidationError(
                f"invalid content role {role!r}; expected one of {sorted(VALID_CONTENT_ROLES)}",
                file_path="request",
                pointer=f"/contents/{idx}/role",
            )
        parts = turn.get("parts")
        if parts is not None:
            if not isinstance(parts, list):
                raise ContractValidationError(
                    "content 'parts' must be an array",
                    file_path="request",
                    pointer=f"/contents/{idx}/parts",
                )
            for p_idx, part in enumerate(parts):
                _validate_part(part, turn_idx=idx, part_idx=p_idx)
        validated.append(copy.deepcopy({str(k): v for k, v in turn.items()}))
    return tuple(validated)


def translate_generate_request(
    *,
    model: str,
    body: object,
    tenant: str,
    explicit_session: str | None = None,
    is_streaming: bool = False,
    alt: str | None = None,
) -> RunRequest:
    """Validate an incoming Gemini generate request (K01) into a ``RunRequest``."""
    clean_model = normalize_model_id(model)
    if alt is not None and alt not in VALID_STREAM_ALTS:
        raise ContractValidationError(
            f"invalid stream format alt={alt!r}; expected 'sse' or 'json'",
            file_path="request",
            pointer="/alt",
        )
    if not isinstance(body, Mapping):
        raise ContractValidationError(
            "request body must be a JSON object",
            file_path="request",
            pointer="/",
        )

    raw_body = copy.deepcopy({str(k): v for k, v in body.items()})
    contents = _validate_contents(raw_body.get("contents"))

    raw_sys = raw_body.get("systemInstruction")
    system_instruction: dict[str, object] | None = None
    if raw_sys is not None:
        if not isinstance(raw_sys, Mapping):
            raise ContractValidationError(
                "systemInstruction must be a JSON object",
                file_path="request",
                pointer="/systemInstruction",
            )
        system_instruction = {str(k): v for k, v in raw_sys.items()}

    raw_tools = raw_body.get("tools")
    tools: list[dict[str, object]] = []
    if raw_tools is not None:
        if not isinstance(raw_tools, list):
            raise ContractValidationError(
                "tools must be an array",
                file_path="request",
                pointer="/tools",
            )
        for t_idx, tool in enumerate(raw_tools):
            if not isinstance(tool, Mapping):
                raise ContractValidationError(
                    "each tools item must be a JSON object",
                    file_path="request",
                    pointer=f"/tools/{t_idx}",
                )
            tools.append({str(k): v for k, v in tool.items()})

    last_parts = contents[-1].get("parts")
    has_function_responses = isinstance(last_parts, list) and any(
        isinstance(part, Mapping) and "functionResponse" in part for part in last_parts
    )

    session_id = resolve_session_id(
        tenant=tenant,
        model=clean_model,
        system_instruction=system_instruction,
        contents=contents,
        explicit_session=explicit_session,
    )
    profile = GOVERNED_MODELS.get(clean_model)
    return RunRequest(
        run_id=str(uuid.uuid4()),
        session_id=session_id,
        tenant=tenant,
        model=clean_model,
        is_governed=profile is not None,
        profile=profile,
        raw_body=raw_body,
        contents=contents,
        system_instruction=system_instruction,
        tools=tuple(tools),
        has_function_responses=has_function_responses,
        is_streaming=is_streaming,
        alt=alt,
    )


__all__ = [
    "GOVERNED_MODELS",
    "VALID_CONTENT_ROLES",
    "VALID_STREAM_ALTS",
    "RunRequest",
    "normalize_model_id",
    "translate_generate_request",
]
