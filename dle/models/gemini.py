"""Google Gemini API adapter routed exclusively through ``EgressClient``.

Implements FR-API-03, NFR-REL-02, NFR-SEC-03, and ADR-011. Retries transient
5xx and transport failures up to 3 attempts with exponential backoff while
preserving 4xx Gemini error shapes directly for SDK parity (GC-10, GC-11).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping

from dle.errors import (
    AuthError,
    DleError,
    EgressDenied,
    ModelUnavailable,
    UpstreamApiError,
)
from dle.models.egress import EgressClient, EgressResponse, is_transport_error
from dle.models.port import ModelCallResult
from dle.models.registry import ModelRegistry
from dle.observability import get_logger

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({500, 502, 503, 504})

_DEFAULT_GEMINI_STATUS_MAP: dict[int, str] = {
    400: "INVALID_ARGUMENT",
    401: "UNAUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    429: "RESOURCE_EXHAUSTED",
}


def _clean_model_name(model: str) -> str:
    return model.removeprefix("models/")


def _extract_gemini_error(
    status_code: int,
    raw_body: object,
) -> tuple[str, str, dict[str, object] | None]:
    default_status = _DEFAULT_GEMINI_STATUS_MAP.get(status_code, "INTERNAL")
    if isinstance(raw_body, Mapping):
        err_obj = raw_body.get("error")
        if isinstance(err_obj, Mapping):
            msg = str(err_obj.get("message") or f"upstream HTTP {status_code}")
            g_status = str(err_obj.get("status") or default_status)
            normalized_payload = {str(k): v for k, v in raw_body.items()}
            return msg, g_status, normalized_payload
    return f"upstream HTTP {status_code}", default_status, None


class GeminiAdapter:
    """Async Gemini REST adapter communicating solely through ``EgressClient``."""

    def __init__(
        self,
        egress: EgressClient,
        registry: ModelRegistry,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_GEMINI_BASE_URL,
        max_attempts: int = 3,
        base_backoff_s: float = 0.25,
    ) -> None:
        """Initialize the adapter with allowlisted egress, registry, and retry policy."""
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._egress = egress
        self._registry = registry
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_attempts = max_attempts
        self._base_backoff_s = base_backoff_s
        self._log = get_logger("dle.models.gemini")

    def _headers(self, api_key: str | None) -> dict[str, str]:
        effective = api_key if api_key else self._api_key
        if not effective:
            raise AuthError("missing Gemini API key for upstream request")
        return {
            "x-goog-api-key": effective,
            "content-type": "application/json",
        }

    async def _sleep_backoff(self, attempt: int) -> None:
        if self._base_backoff_s > 0.0:
            await asyncio.sleep(self._base_backoff_s * (2 ** (attempt - 1)))

    def _raise_for_non_retryable(self, status_code: int, raw_body: object) -> UpstreamApiError:
        msg, gemini_status, payload = _extract_gemini_error(status_code, raw_body)
        return UpstreamApiError(
            status_code,
            msg,
            gemini_status=gemini_status,
            payload=payload,
        )

    def _record_version_if_present(
        self,
        body: Mapping[str, object],
        *,
        job: str,
        model_id: str | None,
    ) -> str | None:
        raw_version = body.get("modelVersion")
        if isinstance(raw_version, str) and raw_version:
            if model_id is not None:
                self._registry.record_model_version(
                    job=job,
                    model_id=model_id,
                    model_version=raw_version,
                )
            return raw_version
        return None

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, object] | None = None,
        params: Mapping[str, str] | None = None,
        api_key: str | None = None,
        job: str = "passthrough",
        model_id: str | None = None,
    ) -> ModelCallResult:
        url = f"{self._base_url}{path}"
        headers = self._headers(api_key)
        last_reason = "no response from upstream model"

        for attempt in range(1, self._max_attempts + 1):
            try:
                resp: EgressResponse = await self._egress.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=dict(payload) if payload is not None else None,
                )
            except EgressDenied:
                raise
            except Exception as exc:
                if not is_transport_error(exc):
                    raise
                last_reason = type(exc).__name__
                self._log.warning(
                    "model.retry_transport",
                    job=job,
                    model_id=model_id or "none",
                    attempt=attempt,
                    max_attempts=self._max_attempts,
                    error_type=last_reason,
                )
                if attempt < self._max_attempts:
                    await self._sleep_backoff(attempt)
                continue

            if resp.status_code == 200:
                try:
                    raw_parsed = resp.json()
                except ValueError as exc:
                    raise ModelUnavailable(
                        f"upstream returned invalid JSON for model {model_id or path}"
                    ) from exc
                if not isinstance(raw_parsed, Mapping):
                    raise ModelUnavailable("upstream returned non-object JSON payload")
                body = {str(k): v for k, v in raw_parsed.items()}
                model_version = self._record_version_if_present(body, job=job, model_id=model_id)
                self._log.info(
                    "model.call_completed",
                    job=job,
                    model_id=model_id or "none",
                    attempts=attempt,
                    status="ok",
                )
                return ModelCallResult(
                    body=body,
                    status_code=resp.status_code,
                    attempts=attempt,
                    model_version=model_version,
                )

            parsed_err: object = None
            try:
                parsed_err = resp.json()
            except ValueError:
                parsed_err = None

            if resp.status_code in _RETRYABLE_STATUS_CODES:
                last_reason = f"HTTP {resp.status_code}"
                self._log.warning(
                    "model.retry_status",
                    job=job,
                    model_id=model_id or "none",
                    attempt=attempt,
                    max_attempts=self._max_attempts,
                    status_code=resp.status_code,
                )
                if attempt < self._max_attempts:
                    await self._sleep_backoff(attempt)
                continue

            raise self._raise_for_non_retryable(resp.status_code, parsed_err)

        raise ModelUnavailable(
            f"upstream model unavailable after {self._max_attempts} attempts ({last_reason})"
        )

    async def list_models(
        self,
        *,
        page_size: int | None = None,
        page_token: str | None = None,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """List Gemini models via ``GET /v1beta/models``."""
        params: dict[str, str] = {}
        if page_size is not None:
            params["pageSize"] = str(page_size)
        if page_token is not None:
            params["pageToken"] = page_token
        return await self._request_json(
            "GET",
            "/models",
            params=params or None,
            api_key=api_key,
            job="discovery",
        )

    async def get_model(
        self,
        model: str,
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """Fetch one Gemini model description via ``GET /v1beta/models/{model}``."""
        clean = _clean_model_name(model)
        return await self._request_json(
            "GET",
            f"/models/{clean}",
            api_key=api_key,
            job="discovery",
            model_id=clean,
        )

    async def generate(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
        job: str = "passthrough",
    ) -> ModelCallResult:
        """Invoke ``POST /v1beta/models/{model}:generateContent``."""
        clean = _clean_model_name(model)
        return await self._request_json(
            "POST",
            f"/models/{clean}:generateContent",
            payload=payload,
            api_key=api_key,
            job=job,
            model_id=clean,
        )

    async def stream_generate(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
        job: str = "passthrough",
    ) -> AsyncIterator[dict[str, object]]:
        """Stream SSE JSON chunks from ``POST /v1beta/models/{model}:streamGenerateContent``."""
        clean = _clean_model_name(model)
        url = f"{self._base_url}/models/{clean}:streamGenerateContent"
        headers = self._headers(api_key)

        try:
            async with self._egress.stream(
                "POST",
                url,
                headers=headers,
                params={"alt": "sse"},
                json=dict(payload),
            ) as resp:
                if resp.status_code != 200:
                    raw_lines = [line async for line in resp.aiter_lines()]
                    raw_text = "\n".join(raw_lines)
                    parsed_err: object = None
                    if raw_text.strip():
                        try:
                            parsed_err = json.loads(raw_text)
                        except ValueError:
                            parsed_err = None
                    if resp.status_code in _RETRYABLE_STATUS_CODES:
                        raise ModelUnavailable(
                            f"upstream stream unavailable (HTTP {resp.status_code})"
                        )
                    raise self._raise_for_non_retryable(resp.status_code, parsed_err)

                async for line in resp.aiter_lines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith(":") or not stripped.startswith("data:"):
                        continue
                    data_part = stripped[5:].strip()
                    if not data_part or data_part == "[DONE]":
                        continue
                    parsed = json.loads(data_part)
                    if isinstance(parsed, Mapping):
                        chunk = {str(k): v for k, v in parsed.items()}
                        self._record_version_if_present(chunk, job=job, model_id=clean)
                        yield chunk
        except EgressDenied:
            raise
        except Exception as exc:
            if is_transport_error(exc):
                raise ModelUnavailable(
                    f"upstream stream transport failure: {type(exc).__name__}"
                ) from exc
            raise

    async def count_tokens(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """Forward ``POST /v1beta/models/{model}:countTokens``."""
        clean = _clean_model_name(model)
        return await self._request_json(
            "POST",
            f"/models/{clean}:countTokens",
            payload=payload,
            api_key=api_key,
            job="count_tokens",
            model_id=clean,
        )

    async def embed(
        self,
        model: str,
        payload: Mapping[str, object],
        *,
        api_key: str | None = None,
    ) -> ModelCallResult:
        """Forward ``POST /v1beta/models/{model}:embedContent``."""
        clean = _clean_model_name(model)
        return await self._request_json(
            "POST",
            f"/models/{clean}:embedContent",
            payload=payload,
            api_key=api_key,
            job="embeddings",
            model_id=clean,
        )

    async def is_reachable(self) -> bool:
        """Probe model reachability cleanly without throwing."""
        try:
            await self.list_models(page_size=1)
        except DleError:
            return False
        except Exception as exc:
            if is_transport_error(exc):
                return False
            raise
        return True


__all__ = ["DEFAULT_GEMINI_BASE_URL", "GeminiAdapter"]
