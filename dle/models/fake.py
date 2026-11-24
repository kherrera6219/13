"""Deterministic offline ``FakeModel`` implementing ``ModelPort``.

Implements FR-API-03, NFR-REL-02, and ADR-011 zero-spend local development
mode (``DLE_MODEL_BACKEND=fake``). Never performs network I/O.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import re
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass

from dle.models.port import ModelCallResult
from dle.models.registry import ModelRegistry

FakeGenerateHandler = Callable[[str, Mapping[str, object], str], dict[str, object]]


@dataclass(frozen=True)
class RecordedModelCall:
    """Recorded invocation against ``FakeModel`` for test assertions."""

    method: str
    model: str
    payload: dict[str, object]
    job: str


def _clean_model(model: str) -> str:
    return model.removeprefix("models/")


def _default_catalog() -> list[dict[str, object]]:
    return [
        {
            "name": "models/gemini-4-neon",
            "displayName": "Gemini 4 Neon",
            "description": "Fast structured Gemini 4 tier (fake local backend).",
            "inputTokenLimit": 1_048_576,
            "outputTokenLimit": 65_536,
            "supportedGenerationMethods": ["generateContent", "countTokens"],
        },
        {
            "name": "models/gemini-4-carbon",
            "displayName": "Gemini 4 Carbon",
            "description": "Balanced Gemini 4 reasoning tier (fake local backend).",
            "inputTokenLimit": 1_048_576,
            "outputTokenLimit": 65_536,
            "supportedGenerationMethods": ["generateContent", "countTokens"],
        },
        {
            "name": "models/gemini-embedding-001",
            "displayName": "Gemini Embedding 001",
            "description": "Dense text embedding model (fake local backend).",
            "inputTokenLimit": 2_048,
            "outputTokenLimit": 0,
            "supportedGenerationMethods": ["embedContent"],
        },
    ]


def _extract_prompt_summary(payload: Mapping[str, object]) -> str:
    contents = payload.get("contents")
    if isinstance(contents, list):
        for turn in reversed(contents):
            if not isinstance(turn, Mapping):
                continue
            parts = turn.get("parts")
            if isinstance(parts, list):
                texts = [
                    str(p.get("text"))
                    for p in parts
                    if isinstance(p, Mapping) and isinstance(p.get("text"), str)
                ]
                if texts:
                    return " ".join(texts)
    return "ok"


def _build_fake_role_artifact(payload: Mapping[str, object]) -> str:
    user_text = _extract_prompt_summary(payload)
    sys_text = ""
    sys_inst = payload.get("systemInstruction")
    if isinstance(sys_inst, Mapping) and isinstance(sys_inst.get("parts"), list):
        sys_text = " ".join(
            str(p.get("text"))
            for p in sys_inst["parts"]
            if isinstance(p, Mapping) and isinstance(p.get("text"), str)
        )

    prof_match = re.search(r'"profile_id"\s*:\s*"(\[ROLE:(8|9|10|11)\.[0-9]+\])"', user_text)
    profile_id = prof_match.group(1) if prof_match else "[ROLE:8.1]"
    role_axis = int(prof_match.group(2)) if prof_match else 8
    prop_match = re.search(r"Proposal:\s*(\S+)", user_text)
    proposal_id = prop_match.group(1) if prop_match else "p0"
    pids = list(dict.fromkeys(re.findall(r'<passage\s+id="([^"]+)">', user_text)))
    falsify = (
        "falsifier" in sys_text.lower() or "what evidence would make it wrong" in sys_text.lower()
    )

    claims: list[dict[str, object]] = []
    if pids:
        claim: dict[str, object] = {
            "claim_id": f"c-role-{role_axis}-1",
            "assertion": f"Evidence in packet supports scoped role-{role_axis} assessment.",
            "binding": role_axis in (10, 11),
            "scope": "general",
            "passage_ids": pids[:2],
        }
        if falsify:
            claim["falsifier"] = "Disconfirming measurement or superseded clause revision."
        claims.append(claim)

    artifact = {
        "profile_id": profile_id,
        "role_axis": role_axis,
        "proposal_id": proposal_id,
        "claims": claims,
        "assumptions": ["Scope matches packet metadata."],
        "disconfirming_observations": (
            ["Check whether newer signed revision supersedes packet clause."] if falsify else []
        ),
        "objections": [],
    }
    return json.dumps(artifact)


def _count_text_tokens(payload: Mapping[str, object]) -> int:
    total_words = 0
    for key in ("contents", "generateContentRequest"):
        val = payload.get(key)
        if isinstance(val, list):
            for turn in val:
                if isinstance(turn, Mapping) and isinstance(turn.get("parts"), list):
                    for part in turn["parts"]:
                        if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                            total_words += len(part["text"].split())
        elif isinstance(val, Mapping):
            total_words += _count_text_tokens(val)
    if total_words == 0:
        return len(json.dumps(dict(payload), default=str).split()) or 1
    return max(1, total_words * 2)


class FakeModel:
    """Deterministic in-process model stub implementing ``ModelPort``."""

    def __init__(
        self,
        *,
        registry: ModelRegistry | None = None,
        generate_handler: FakeGenerateHandler | None = None,
        delay_s: float = 0.0,
        reachable: bool = True,
        default_version_suffix: str = "001",
    ) -> None:
        """Initialize offline fake model with optional handlers, delay, and queue."""
        self._registry = registry
        self._generate_handler = generate_handler
        self._delay_s = delay_s
        self._reachable = reachable
        self._version_suffix = default_version_suffix
        self._catalog = _default_catalog()
        self._queue: deque[dict[str, object] | Exception] = deque()
        self.calls: list[RecordedModelCall] = []

    def enqueue_response(self, response: Mapping[str, object]) -> None:
        """Queue a canned response dict to be returned by the next generate/stream call."""
        self._queue.append({str(k): v for k, v in response.items()})

    def enqueue_error(self, exc: Exception) -> None:
        """Queue an exception to be raised on the next model invocation."""
        self._queue.append(exc)

    def _record_version(self, body: Mapping[str, object], *, job: str, model_id: str) -> str | None:
        mv = body.get("modelVersion")
        if isinstance(mv, str) and mv:
            if self._registry is not None:
                self._registry.record_model_version(job=job, model_id=model_id, model_version=mv)
            return mv
        return None

    def _build_default_generate(
        self,
        model: str,
        payload: Mapping[str, object],
        job: str,
    ) -> dict[str, object]:
        clean = _clean_model(model)
        prompt_summary = _extract_prompt_summary(payload)
        gen_cfg = payload.get("generationConfig")
        response_text: str
        if job == "personas":
            response_text = _build_fake_role_artifact(payload)
        elif isinstance(gen_cfg, Mapping) and gen_cfg.get("responseMimeType") == "application/json":
            response_text = json.dumps({"echo": prompt_summary, "job": job})
        elif job == "writer":
            response_text = prompt_summary
        else:
            response_text = f"[{clean}] {prompt_summary}"

        prompt_tokens = _count_text_tokens(payload)
        output_tokens = max(1, len(response_text.split()))
        return {
            "candidates": [
                {
                    "index": 0,
                    "content": {
                        "role": "model",
                        "parts": [{"text": response_text}],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": prompt_tokens,
                "candidatesTokenCount": output_tokens,
                "totalTokenCount": prompt_tokens + output_tokens,
            },
            "modelVersion": f"{clean}-{self._version_suffix}",
            "responseId": f"fake-{hashlib.sha256(response_text.encode('utf-8')).hexdigest()[:12]}",
        }

    async def list_models(
        self,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """Return deterministic catalog with offset-based pagination."""
        del api_key
        self.calls.append(
            RecordedModelCall("list_models", "models", {"pageSize": page_size}, "discovery")
        )
        offset = int(page_token) if page_token and page_token.isdigit() else 0
        limit = page_size if page_size is not None and page_size > 0 else len(self._catalog)
        page = [copy.deepcopy(item) for item in self._catalog[offset : offset + limit]]
        body: dict[str, object] = {"models": page}
        if offset + limit < len(self._catalog):
            body["nextPageToken"] = str(offset + limit)
        return ModelCallResult(body=body, status_code=200, attempts=1)

    async def get_model(
        self,
        model: str,
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """Return catalog entry or synthesized descriptor for ``model``."""
        del api_key
        clean = _clean_model(model)
        self.calls.append(RecordedModelCall("get_model", clean, {}, "discovery"))
        for item in self._catalog:
            if item["name"] == f"models/{clean}":
                return ModelCallResult(body=copy.deepcopy(item), status_code=200, attempts=1)
        return ModelCallResult(
            body={
                "name": f"models/{clean}",
                "displayName": clean,
                "supportedGenerationMethods": ["generateContent", "countTokens"],
            },
            status_code=200,
            attempts=1,
        )

    async def generate(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
        job: str = "passthrough",
    ) -> ModelCallResult:
        """Return deterministic generated response (or next queued response/error)."""
        del api_key
        if self._delay_s > 0.0:
            await asyncio.sleep(self._delay_s)

        clean = _clean_model(model)
        recorded_payload = copy.deepcopy({str(k): v for k, v in payload.items()})
        self.calls.append(RecordedModelCall("generate", clean, recorded_payload, job))

        if self._queue:
            queued = self._queue.popleft()
            if isinstance(queued, Exception):
                raise queued
            body = copy.deepcopy(queued)
        elif self._generate_handler is not None:
            body = copy.deepcopy(self._generate_handler(clean, recorded_payload, job))
        else:
            body = self._build_default_generate(clean, recorded_payload, job)

        mv = self._record_version(body, job=job, model_id=clean)
        return ModelCallResult(body=body, status_code=200, attempts=1, model_version=mv)

    async def stream_generate(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
        job: str = "passthrough",
    ) -> AsyncIterator[dict[str, object]]:
        """Yield two deterministic chunks derived from ``generate()`` output."""
        result = await self.generate(model, payload, api_key=api_key, job=job)
        body = result.body
        text = ""
        candidates = body.get("candidates")
        if isinstance(candidates, list) and candidates and isinstance(candidates[0], Mapping):
            content = candidates[0].get("content")
            if isinstance(content, Mapping) and isinstance(content.get("parts"), list):
                parts = content["parts"]
                if (
                    parts
                    and isinstance(parts[0], Mapping)
                    and isinstance(parts[0].get("text"), str)
                ):
                    text = parts[0]["text"]

        if text and len(text) > 1:
            midpoint = max(1, len(text) // 2)
            first_chunk = {
                "candidates": [
                    {
                        "index": 0,
                        "content": {"role": "model", "parts": [{"text": text[:midpoint]}]},
                    }
                ],
                "modelVersion": body.get(
                    "modelVersion", f"{_clean_model(model)}-{self._version_suffix}"
                ),
            }
            second_chunk = copy.deepcopy(body)
            second_cand = second_chunk["candidates"]
            if isinstance(second_cand, list) and isinstance(second_cand[0], dict):
                second_cand[0]["content"] = {
                    "role": "model",
                    "parts": [{"text": text[midpoint:]}],
                }
            yield first_chunk
            yield second_chunk
            return

        yield body

    async def count_tokens(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """Compute deterministic synthetic token count."""
        del api_key
        clean = _clean_model(model)
        recorded_payload = copy.deepcopy({str(k): v for k, v in payload.items()})
        self.calls.append(
            RecordedModelCall("count_tokens", clean, recorded_payload, "count_tokens")
        )
        return ModelCallResult(
            body={"totalTokens": _count_text_tokens(recorded_payload)},
            status_code=200,
            attempts=1,
        )

    async def embed(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """Produce deterministic normalized 8-d embedding from content hash."""
        del api_key
        clean = _clean_model(model)
        recorded_payload = copy.deepcopy({str(k): v for k, v in payload.items()})
        self.calls.append(RecordedModelCall("embed", clean, recorded_payload, "embeddings"))
        digest = hashlib.sha256(
            json.dumps(recorded_payload, sort_keys=True, default=str).encode("utf-8")
        ).digest()
        raw = [((digest[i] - 128) / 128.0) or 0.01 for i in range(8)]
        norm = math.sqrt(sum(v * v for v in raw)) or 1.0
        vec = [round(v / norm, 6) for v in raw]
        return ModelCallResult(body={"embedding": {"values": vec}}, status_code=200, attempts=1)

    async def is_reachable(self) -> bool:
        """Return configured fake reachability boolean."""
        return self._reachable


__all__ = ["FakeGenerateHandler", "FakeModel", "RecordedModelCall"]
