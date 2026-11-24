"""Deterministic recorded-replay upstream implementing ``ModelPort`` for GC-01..GC-26.

Supports every Phase 1 Gemini compatibility scenario (``docs/test/gemini_compat_test_plan.md``)
without performing any outbound network calls.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from dle.errors import UpstreamApiError
from dle.models.fake import _build_fake_role_artifact, extract_writer_question
from dle.models.port import ModelCallResult
from dle.models.registry import ModelRegistry

_COMPAT_CATALOG: tuple[dict[str, object], ...] = (
    {
        "name": "models/gemini-4-neon",
        "displayName": "Gemini 4 Neon",
        "description": "Fast structured Gemini 4 tier (compat replay).",
        "inputTokenLimit": 1_048_576,
        "outputTokenLimit": 65_536,
        "supportedGenerationMethods": ["generateContent", "countTokens"],
    },
    {
        "name": "models/gemini-4-carbon",
        "displayName": "Gemini 4 Carbon",
        "description": "Balanced Gemini 4 reasoning tier (compat replay).",
        "inputTokenLimit": 1_048_576,
        "outputTokenLimit": 65_536,
        "supportedGenerationMethods": ["generateContent", "countTokens"],
    },
    {
        "name": "models/gemini-embedding-001",
        "displayName": "Gemini Embedding 001",
        "description": "Dense text embedding model (compat replay).",
        "inputTokenLimit": 2_048,
        "outputTokenLimit": 0,
        "supportedGenerationMethods": ["embedContent"],
    },
)


@dataclass(frozen=True)
class CapturedRequest:
    """Recorded upstream invocation captured for compatibility assertions."""

    method: str
    model: str
    payload: dict[str, object]
    job: str


def _clean_model(model: str) -> str:
    return model.removeprefix("models/")


def _all_text_parts(payload: Mapping[str, object]) -> list[str]:
    texts: list[str] = []
    contents = payload.get("contents")
    if isinstance(contents, list):
        for turn in contents:
            if not isinstance(turn, Mapping):
                continue
            parts = turn.get("parts")
            if isinstance(parts, list):
                for part in parts:
                    if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                        texts.append(part["text"])
    return texts


def _has_part_key(payload: Mapping[str, object], key: str) -> bool:
    contents = payload.get("contents")
    if not isinstance(contents, list):
        return False
    for turn in contents:
        if not isinstance(turn, Mapping):
            continue
        parts = turn.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, Mapping) and key in part and part[key] is not None:
                    return True
    return False


def _last_turn_function_responses(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    contents = payload.get("contents")
    if not isinstance(contents, list) or not contents:
        return []
    last = contents[-1]
    if not isinstance(last, Mapping):
        return []
    parts = last.get("parts")
    if not isinstance(parts, list):
        return []
    out: list[Mapping[str, object]] = []
    for part in parts:
        if isinstance(part, Mapping):
            fr = part.get("functionResponse")
            if isinstance(fr, Mapping):
                out.append(fr)
    return out


def _inline_mime_types(payload: Mapping[str, object]) -> list[str]:
    mimes: list[str] = []
    contents = payload.get("contents")
    if not isinstance(contents, list):
        return mimes
    for turn in contents:
        if not isinstance(turn, Mapping):
            continue
        parts = turn.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, Mapping) and isinstance(part.get("inlineData"), Mapping):
                    mime = part["inlineData"].get("mimeType")
                    if isinstance(mime, str):
                        mimes.append(mime)
    return mimes


def _declared_function_names(payload: Mapping[str, object]) -> list[str]:
    names: list[str] = []
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return names
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        decls = tool.get("functionDeclarations")
        if isinstance(decls, list):
            for decl in decls:
                if isinstance(decl, Mapping) and isinstance(decl.get("name"), str):
                    names.append(decl["name"])
    return names


def _has_tool_flag(payload: Mapping[str, object], tool_key: str) -> bool:
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return False
    return any(isinstance(t, Mapping) and tool_key in t for t in tools)


def _tool_mode(payload: Mapping[str, object]) -> str | None:
    tool_cfg = payload.get("toolConfig")
    if not isinstance(tool_cfg, Mapping):
        return None
    fc_cfg = tool_cfg.get("functionCallingConfig")
    if not isinstance(fc_cfg, Mapping):
        return None
    mode = fc_cfg.get("mode")
    return str(mode) if isinstance(mode, str) else None


def _count_tokens_estimate(payload: Mapping[str, object]) -> int:
    texts = _all_text_parts(payload)
    total_chars = sum(len(t) for t in texts)
    if total_chars >= 1_500_000:
        # Large context simulation (>= 500k tokens for GC-24).
        return max(500_000, total_chars // 3)
    words = sum(len(t.split()) for t in texts)
    sys_inst = payload.get("systemInstruction")
    if isinstance(sys_inst, Mapping) and isinstance(sys_inst.get("parts"), list):
        for p in sys_inst["parts"]:
            if isinstance(p, Mapping) and isinstance(p.get("text"), str):
                words += len(p["text"].split())
    return max(1, words * 2) if words else max(1, len(json.dumps(dict(payload))) // 8)


class FakeUpstream:
    """Recorded-replay upstream adapter supporting GC-01..GC-26 P-cases."""

    def __init__(
        self,
        *,
        registry: ModelRegistry | None = None,
        delay_s: float = 0.0,
        stream_delay_s: float = 0.0,
    ) -> None:
        self._registry = registry
        self.delay_s = delay_s
        self.stream_delay_s = stream_delay_s
        self.recorded_requests: list[CapturedRequest] = []

    async def list_models(
        self,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
        api_key: str | None = None,
    ) -> ModelCallResult:
        del api_key
        self.recorded_requests.append(
            CapturedRequest(
                method="list_models",
                model="models",
                payload={"pageSize": page_size, "pageToken": page_token},
                job="discovery",
            )
        )
        offset = int(page_token) if page_token and page_token.isdigit() else 0
        limit = page_size if page_size is not None and page_size > 0 else len(_COMPAT_CATALOG)
        items = [copy.deepcopy(item) for item in _COMPAT_CATALOG[offset : offset + limit]]
        body: dict[str, object] = {"models": items}
        if offset + limit < len(_COMPAT_CATALOG):
            body["nextPageToken"] = str(offset + limit)
        return ModelCallResult(body=body, status_code=200, attempts=1)

    async def get_model(
        self,
        model: str,
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        del api_key
        clean = _clean_model(model)
        self.recorded_requests.append(
            CapturedRequest(method="get_model", model=clean, payload={}, job="discovery")
        )
        for item in _COMPAT_CATALOG:
            if item["name"] == f"models/{clean}":
                return ModelCallResult(body=copy.deepcopy(item), status_code=200, attempts=1)
        raise UpstreamApiError(
            404,
            f"Model models/{clean} is not found.",
            gemini_status="NOT_FOUND",
            payload={
                "error": {
                    "code": 404,
                    "message": f"Model models/{clean} is not found.",
                    "status": "NOT_FOUND",
                }
            },
        )

    def _replay_generate(
        self,
        clean_model: str,
        body: Mapping[str, object],
        job: str,
    ) -> dict[str, object]:
        texts = _all_text_parts(body)
        joined = "\n".join(texts)

        if "TRIGGER_429" in joined:
            raise UpstreamApiError(
                429,
                "Resource has been exhausted (compat replay).",
                gemini_status="RESOURCE_EXHAUSTED",
                payload={
                    "error": {
                        "code": 429,
                        "message": "Resource has been exhausted (compat replay).",
                        "status": "RESOURCE_EXHAUSTED",
                    }
                },
            )

        if "TRIGGER_400" in joined:
            raise UpstreamApiError(
                400,
                "Request contains an invalid argument (compat replay).",
                gemini_status="INVALID_ARGUMENT",
                payload={
                    "error": {
                        "code": 400,
                        "message": "Request contains an invalid argument (compat replay).",
                        "status": "INVALID_ARGUMENT",
                    }
                },
            )

        prompt_tokens = _count_tokens_estimate(body)
        candidate: dict[str, object] = {
            "index": 0,
            "finishReason": "STOP",
        }
        parts: list[dict[str, object]] = []

        fn_responses = _last_turn_function_responses(body)
        fn_names = _declared_function_names(body)
        fc_mode = _tool_mode(body)

        if fn_responses:
            summaries = []
            for fr in fn_responses:
                call_id = fr.get("id")
                id_tag = f" [id={call_id}]" if isinstance(call_id, str) and call_id else ""
                summaries.append(
                    f"{fr.get('name', 'tool')}{id_tag}->{json.dumps(fr.get('response', {}))}"
                )
            parts.append({"text": "Tool outputs received: " + "; ".join(summaries)})
        elif fn_names and fc_mode != "NONE":
            if "parallel" in joined.lower() and len(fn_names) >= 2:
                parts.append(
                    {
                        "functionCall": {
                            "id": "call-parallel-1",
                            "name": fn_names[0],
                            "args": {"city": "Seattle"},
                        }
                    }
                )
                parts.append(
                    {
                        "functionCall": {
                            "id": "call-parallel-2",
                            "name": fn_names[1],
                            "args": {"timezone": "America/Los_Angeles"},
                        }
                    }
                )
            else:
                parts.append(
                    {
                        "functionCall": {
                            "id": "call-single-1",
                            "name": fn_names[0],
                            "args": {"city": "Austin"},
                        }
                    }
                )
        elif _has_tool_flag(body, "googleSearch"):
            parts.append({"text": "Grounded answer referencing official documentation."})
            candidate["groundingMetadata"] = {
                "webSearchQueries": [joined.strip() or "dle query"],
                "groundingChunks": [
                    {
                        "web": {
                            "uri": "https://example.org/spec",
                            "title": "Official Spec",
                        }
                    }
                ],
                "groundingSupports": [
                    {
                        "segment": {
                            "startIndex": 0,
                            "endIndex": 50,
                            "text": "Grounded answer referencing official documentation.",
                        },
                        "groundingChunkIndices": [0],
                    }
                ],
            }
        elif _has_tool_flag(body, "urlContext"):
            parts.append({"text": "URL context inspected cleanly."})
            candidate["urlContextMetadata"] = {
                "urlMetadata": [
                    {
                        "retrievedUrl": "https://example.org/doc",
                        "urlRetrievalStatus": "URL_RETRIEVAL_STATUS_SUCCESS",
                    }
                ]
            }
        elif _has_tool_flag(body, "codeExecution"):
            parts.append({"executableCode": {"language": "PYTHON", "code": "print(6 * 7)"}})
            parts.append({"codeExecutionResult": {"outcome": "OUTCOME_OK", "output": "42\n"}})
            parts.append({"text": "The executed result is 42."})
        else:
            gen_cfg = body.get("generationConfig")
            thinking_cfg = gen_cfg.get("thinkingConfig") if isinstance(gen_cfg, Mapping) else None
            if isinstance(thinking_cfg, Mapping):
                parts.append({"thought": True, "text": "Reasoning step 1: check constraints."})

            if job == "personas":
                parts.append({"text": _build_fake_role_artifact(body)})
            elif (
                isinstance(gen_cfg, Mapping)
                and gen_cfg.get("responseMimeType") == "application/json"
            ):
                if job == "claim_extraction":
                    payload_json = {"job": "claim_extraction", "echo": clean_model}
                else:
                    payload_json = {"answer": "verified", "confidence": 0.96, "model": clean_model}
                parts.append({"text": json.dumps(payload_json)})
            elif inline_mimes := _inline_mime_types(body):
                parts.append({"text": f"Processed inline image input ({', '.join(inline_mimes)})."})
            elif job == "writer":
                parts.append({"text": extract_writer_question(texts[-1] if texts else "ok")})
            else:
                turn_count = (
                    len(body.get("contents", [])) if isinstance(body.get("contents"), list) else 1
                )
                sys_tag = " [with-system]" if "systemInstruction" in body else ""
                parts.append(
                    {
                        "text": (
                            f"[{clean_model}/{job}] turn={turn_count}{sys_tag}: "
                            f"{texts[-1] if texts else 'ok'}"
                        )
                    }
                )

        candidate["content"] = {"role": "model", "parts": parts}
        output_tokens = max(4, sum(len(str(p.get("text", "")).split()) for p in parts) or 8)
        response: dict[str, object] = {
            "candidates": [candidate],
            "usageMetadata": {
                "promptTokenCount": prompt_tokens,
                "candidatesTokenCount": output_tokens,
                "totalTokenCount": prompt_tokens + output_tokens,
            },
            "modelVersion": f"{clean_model}-001",
            "responseId": "replay-" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12],
        }
        if "futureExperimentalFlag" in body:
            response["futureResponseExtension"] = {
                "echoedFlag": copy.deepcopy(body["futureExperimentalFlag"]),
            }
        return response

    async def generate(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
        job: str = "passthrough",
    ) -> ModelCallResult:
        del api_key
        if self.delay_s > 0.0:
            await asyncio.sleep(self.delay_s)
        clean = _clean_model(model)
        copied = copy.deepcopy({str(k): v for k, v in payload.items()})
        self.recorded_requests.append(
            CapturedRequest(method="generate", model=clean, payload=copied, job=job)
        )
        body = self._replay_generate(clean, copied, job)
        mv = str(body.get("modelVersion", f"{clean}-001"))
        if self._registry is not None:
            self._registry.record_model_version(job=job, model_id=clean, model_version=mv)
        return ModelCallResult(body=body, status_code=200, attempts=1, model_version=mv)

    async def stream_generate(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
        job: str = "passthrough",
    ) -> AsyncIterator[dict[str, object]]:
        if self.stream_delay_s > 0.0:
            await asyncio.sleep(self.stream_delay_s)
        result = await self.generate(model, payload, api_key=api_key, job=job)
        full = result.body
        cands = full.get("candidates")
        text = ""
        if isinstance(cands, list) and cands and isinstance(cands[0], Mapping):
            content = cands[0].get("content")
            if isinstance(content, Mapping) and isinstance(content.get("parts"), list):
                for part in content["parts"]:
                    if (
                        isinstance(part, Mapping)
                        and isinstance(part.get("text"), str)
                        and not part.get("thought")
                    ):
                        text = part["text"]
                        break

        if len(text) >= 6:
            cut = len(text) // 2
            first_chunk: dict[str, object] = {
                "candidates": [
                    {
                        "index": 0,
                        "content": {"role": "model", "parts": [{"text": text[:cut]}]},
                    }
                ],
                "modelVersion": full.get("modelVersion"),
            }
            second_chunk = copy.deepcopy(full)
            sec_cands = second_chunk["candidates"]
            if isinstance(sec_cands, list) and isinstance(sec_cands[0], dict):
                sec_cands[0]["content"] = {
                    "role": "model",
                    "parts": [{"text": text[cut:]}],
                }
            yield first_chunk
            yield second_chunk
            return
        yield full

    async def count_tokens(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        del api_key
        clean = _clean_model(model)
        copied = copy.deepcopy({str(k): v for k, v in payload.items()})
        self.recorded_requests.append(
            CapturedRequest(method="count_tokens", model=clean, payload=copied, job="count_tokens")
        )
        return ModelCallResult(
            body={"totalTokens": _count_tokens_estimate(copied)},
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
        del api_key
        clean = _clean_model(model)
        copied = copy.deepcopy({str(k): v for k, v in payload.items()})
        self.recorded_requests.append(
            CapturedRequest(method="embed", model=clean, payload=copied, job="embeddings")
        )
        return ModelCallResult(
            body={"embedding": {"values": [0.5, 0.5, 0.5, 0.5]}},
            status_code=200,
            attempts=1,
        )

    async def is_reachable(self) -> bool:
        return True
