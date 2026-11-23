"""FastAPI Gemini-compatible gateway serving all routes in ``contracts/openapi.yaml``.

Implements FR-API-01..02, IR-01..07, NFR-SEC-01..02, NFR-OBS-01, ADR-001, and
ADR-011. Serves ``v1beta`` Gemini routes, ``/v1`` DLE endpoints, ``/admin``
loopback-only routes, ``/healthz``, and static browser UI assets.
"""

from __future__ import annotations

import copy
import hmac
import io
import json
import re
import time
import uuid
import zipfile
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dle import __version__
from dle.config import DleConfig, load_config
from dle.edge.sessions import InMemorySessionStore
from dle.edge.settings import GatewaySettings, validate_bind
from dle.edge.translator import normalize_model_id, translate_generate_request
from dle.errors import (
    AuthError,
    ContractValidationError,
    DleError,
    EgressDenied,
    ModelUnavailable,
    SessionError,
    UpstreamApiError,
)
from dle.models import EgressClient, FakeModel, GeminiAdapter, ModelPort, ModelRegistry
from dle.observability import METRICS, get_logger, sha256_text

DLE_API_VERSION = "1.0"
_RECEIPT_ID_RE = re.compile(r"^[0-9a-f-]{36}$")
_ADMIN_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})

VIRTUAL_MODELS: tuple[dict[str, object], ...] = (
    {
        "name": "models/dle-13axis-strict",
        "displayName": "DLE 13-Axis Strict",
        "description": "Governed DataLogicEngine 13-axis pipeline with strict verification gate.",
        "inputTokenLimit": 1_048_576,
        "outputTokenLimit": 65_536,
        "supportedGenerationMethods": ["generateContent", "streamGenerateContent", "countTokens"],
    },
    {
        "name": "models/dle-13axis-advisory",
        "displayName": "DLE 13-Axis Advisory",
        "description": (
            "Governed DataLogicEngine 13-axis pipeline releasing weak claims as advisory."
        ),
        "inputTokenLimit": 1_048_576,
        "outputTokenLimit": 65_536,
        "supportedGenerationMethods": ["generateContent", "streamGenerateContent", "countTokens"],
    },
)
_VIRTUAL_MODELS_BY_ID: dict[str, dict[str, object]] = {
    str(item["name"]).removeprefix("models/"): item for item in VIRTUAL_MODELS
}


@dataclass
class GatewayRuntime:
    """In-memory runtime container held on ``app.state.dle``."""

    settings: GatewaySettings
    config: DleConfig
    registry: ModelRegistry
    model_port: ModelPort
    sessions: InMemorySessionStore
    egress: EgressClient | None = None
    receipts: dict[str, dict[str, object]] = field(default_factory=dict)
    sources: dict[str, dict[str, object]] = field(default_factory=dict)


def gemini_error_response(http_status: int, message: str, status: str) -> JSONResponse:
    """Build a Gemini-shaped ``ErrorResponse`` with ``X-DLE-API-Version`` header."""
    return JSONResponse(
        status_code=http_status,
        content={
            "error": {
                "code": http_status,
                "message": message,
                "status": status,
            }
        },
        headers={"X-DLE-API-Version": DLE_API_VERSION},
    )


def _extract_client_key(request: Request) -> str | None:
    header_key = request.headers.get("x-goog-api-key")
    if header_key:
        return header_key.strip()
    query_key = request.query_params.get("key")
    if query_key:
        return query_key.strip()
    return None


def _matches_any_key(candidate: str, allowed: frozenset[str]) -> bool:
    matched = False
    for target in allowed:
        if hmac.compare_digest(candidate, target):
            matched = True
    return matched


def _require_client_auth(request: Request, settings: GatewaySettings) -> tuple[str, str]:
    provided = _extract_client_key(request)
    if not provided or not _matches_any_key(provided, settings.client_api_keys):
        raise AuthError("invalid or missing Gemini API key")
    return sha256_text(provided)[:16], provided


def _require_admin_auth(request: Request, settings: GatewaySettings) -> str:
    provided = request.headers.get("x-dle-admin-key")
    if not provided or not _matches_any_key(provided.strip(), settings.admin_api_keys):
        raise AuthError("invalid or missing X-DLE-Admin-Key")
    client_host = request.client.host if request.client is not None else ""
    if client_host.lower() not in _ADMIN_LOOPBACK_HOSTS:
        raise EgressDenied(
            client_host or "unknown",
            0,
            "admin endpoints accept loopback connections only",
        )
    return sha256_text(provided.strip())[:16]


def _upstream_key(settings: GatewaySettings, client_key: str) -> str:
    return settings.gemini_api_key or client_key


def _record_http_metric(route: str, status_code: int) -> None:
    METRICS.counter(
        "dle_http_requests_total",
        "Total inbound HTTP requests by route and status",
        ("route", "status"),
    ).inc(route=route, status=str(status_code))


async def _parse_json_object(request: Request) -> dict[str, object]:
    try:
        parsed = await request.json()
    except ValueError as exc:
        raise ContractValidationError(
            "request body must be valid JSON",
            file_path="request",
            pointer="/",
        ) from exc
    if not isinstance(parsed, Mapping):
        raise ContractValidationError(
            "request body must be a JSON object",
            file_path="request",
            pointer="/",
        )
    return {str(k): v for k, v in parsed.items()}


def create_app(
    *,
    settings: GatewaySettings | None = None,
    config: DleConfig | None = None,
    model_port: ModelPort | None = None,
    registry: ModelRegistry | None = None,
) -> FastAPI:
    """Create and configure the FastAPI middleware application."""
    eff_settings = settings if settings is not None else GatewaySettings.from_env()
    validate_bind(eff_settings.bind_address, allow_lan=eff_settings.allow_lan)
    eff_settings.register_secrets()

    eff_config = config if config is not None else load_config(eff_settings.config_dir)
    eff_registry = registry if registry is not None else ModelRegistry(eff_config.model_pins)
    sessions = InMemorySessionStore()

    egress: EgressClient | None = None
    eff_model_port: ModelPort
    if model_port is not None:
        eff_model_port = model_port
    elif eff_settings.model_backend == "gemini":
        egress = EgressClient(eff_config.egress)
        eff_model_port = GeminiAdapter(
            egress,
            eff_registry,
            api_key=eff_settings.gemini_api_key,
        )
    else:
        eff_model_port = FakeModel(registry=eff_registry)

    runtime = GatewayRuntime(
        settings=eff_settings,
        config=eff_config,
        registry=eff_registry,
        model_port=eff_model_port,
        sessions=sessions,
        egress=egress,
    )
    log = get_logger("dle.edge.gateway")

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if runtime.egress is not None:
                await runtime.egress.aclose()

    app = FastAPI(
        title="DataLogicEngine 13-Axis Middleware API",
        version=__version__,
        lifespan=_lifespan,
    )
    app.state.dle = runtime

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(eff_settings.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[
            "X-DLE-Release-Mode",
            "X-DLE-Receipt",
            "X-DLE-Tier",
            "X-DLE-API-Version",
        ],
    )

    @app.exception_handler(AuthError)
    async def _handle_auth_error(request: Request, exc: AuthError) -> JSONResponse:
        _record_http_metric(request.url.path, 401)
        return gemini_error_response(401, exc.message, "UNAUTHENTICATED")

    @app.exception_handler(ContractValidationError)
    async def _handle_validation_error(
        request: Request, exc: ContractValidationError
    ) -> JSONResponse:
        _record_http_metric(request.url.path, 400)
        suffix = f" ({exc.pointer})" if exc.pointer else ""
        return gemini_error_response(400, f"{exc.message}{suffix}", "INVALID_ARGUMENT")

    @app.exception_handler(SessionError)
    async def _handle_session_error(request: Request, exc: SessionError) -> JSONResponse:
        _record_http_metric(request.url.path, 400)
        return gemini_error_response(400, exc.message, "INVALID_ARGUMENT")

    @app.exception_handler(UpstreamApiError)
    async def _handle_upstream_error(request: Request, exc: UpstreamApiError) -> JSONResponse:
        _record_http_metric(request.url.path, exc.http_status)
        if isinstance(exc.payload.get("error"), Mapping):
            return JSONResponse(
                status_code=exc.http_status,
                content=exc.payload,
                headers={"X-DLE-API-Version": DLE_API_VERSION},
            )
        return gemini_error_response(exc.http_status, exc.message, exc.gemini_status)

    @app.exception_handler(ModelUnavailable)
    async def _handle_model_unavailable(request: Request, exc: ModelUnavailable) -> JSONResponse:
        _record_http_metric(request.url.path, 503)
        return gemini_error_response(503, exc.message, "UNAVAILABLE")

    @app.exception_handler(EgressDenied)
    async def _handle_egress_denied(request: Request, exc: EgressDenied) -> JSONResponse:
        _record_http_metric(request.url.path, 403)
        return gemini_error_response(403, exc.message, "PERMISSION_DENIED")

    @app.exception_handler(DleError)
    async def _handle_dle_error(request: Request, exc: DleError) -> JSONResponse:
        _record_http_metric(request.url.path, 500)
        return gemini_error_response(500, exc.message, "INTERNAL")

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        reachable = await runtime.model_port.is_reachable()
        kernel_count = sum(1 for fn in runtime.config.functions.functions if fn.level == "kernel")
        drift_state = "tripped" if runtime.registry.drift_latched else "clear"
        status = "ok" if reachable and not runtime.registry.drift_latched else "degraded"
        _record_http_metric("/healthz", 200)
        return {
            "status": status,
            "bind": f"{runtime.settings.bind_address}:{runtime.settings.port}",
            "modelReachable": reachable,
            "nliLoaded": False,
            "driftLatch": drift_state,
            "kernelFunctions": kernel_count,
            "version": __version__,
        }

    @app.get("/v1beta/models")
    async def list_models(
        request: Request,
        pageSize: int | None = Query(default=None, ge=1, le=1000),
        pageToken: str | None = Query(default=None),
    ) -> JSONResponse:
        _tenant, client_key = _require_client_auth(request, runtime.settings)
        res = await runtime.model_port.list_models(
            page_size=pageSize,
            page_token=pageToken,
            api_key=_upstream_key(runtime.settings, client_key),
        )
        body = copy.deepcopy(res.body)
        raw_upstream = body.get("models")
        upstream_list = list(raw_upstream) if isinstance(raw_upstream, list) else []
        if pageToken is None:
            existing_names = {str(m.get("name")) for m in upstream_list if isinstance(m, Mapping)}
            prefix = [
                copy.deepcopy(vm) for vm in VIRTUAL_MODELS if str(vm["name"]) not in existing_names
            ]
            body["models"] = [*prefix, *upstream_list]
        _record_http_metric("/v1beta/models", 200)
        return JSONResponse(
            status_code=200,
            content=body,
            headers={"X-DLE-API-Version": DLE_API_VERSION},
        )

    @app.get("/v1beta/models/{model}")
    async def get_model(request: Request, model: str) -> JSONResponse:
        _tenant, client_key = _require_client_auth(request, runtime.settings)
        clean = normalize_model_id(model)
        if clean in _VIRTUAL_MODELS_BY_ID:
            _record_http_metric("/v1beta/models/{model}", 200)
            return JSONResponse(
                status_code=200,
                content=copy.deepcopy(_VIRTUAL_MODELS_BY_ID[clean]),
                headers={"X-DLE-API-Version": DLE_API_VERSION},
            )
        res = await runtime.model_port.get_model(
            clean,
            api_key=_upstream_key(runtime.settings, client_key),
        )
        _record_http_metric("/v1beta/models/{model}", 200)
        return JSONResponse(
            status_code=200,
            content=res.body,
            headers={"X-DLE-API-Version": DLE_API_VERSION},
        )

    @app.post("/v1beta/models/{model}:generateContent")
    async def generate_content(request: Request, model: str) -> JSONResponse:
        start = time.perf_counter()
        tenant, client_key = _require_client_auth(request, runtime.settings)
        raw_body = await _parse_json_object(request)
        explicit_session = request.headers.get("x-dle-session")
        run_req = translate_generate_request(
            model=model,
            body=raw_body,
            tenant=tenant,
            explicit_session=explicit_session,
        )
        runtime.sessions.touch(run_req.session_id, tenant=tenant, model=run_req.model)

        upstream_key = _upstream_key(runtime.settings, client_key)
        if not run_req.is_governed:
            res = await runtime.model_port.generate(
                run_req.model,
                run_req.raw_body,
                api_key=upstream_key,
                job="passthrough",
            )
            headers = {
                "X-DLE-Release-Mode": "passthrough",
                "X-DLE-API-Version": DLE_API_VERSION,
            }
            _record_http_metric("/v1beta/models/{model}:generateContent", 200)
            log.info(
                "gateway.generate",
                route="/v1beta/models/{model}:generateContent",
                model=run_req.model,
                release_mode="passthrough",
                session_id=run_req.session_id,
                run_id=run_req.run_id,
                duration_ms=round((time.perf_counter() - start) * 1000.0, 3),
            )
            return JSONResponse(status_code=200, content=res.body, headers=headers)

        # Phase 1 Wave 1B minimal governed placeholder (upgraded to H16 stub in Wave 1C P1-15).
        writer_model = runtime.registry.pin_for_job("writer")
        res = await runtime.model_port.generate(
            writer_model,
            run_req.raw_body,
            api_key=upstream_key,
            job="writer",
        )
        out_body = copy.deepcopy(res.body)
        out_body["dleMetadata"] = {
            "releaseMode": "released_advisory",
            "receiptId": run_req.run_id,
            "tier": 1,
        }
        headers = {
            "X-DLE-Release-Mode": "released_advisory",
            "X-DLE-Receipt": run_req.run_id,
            "X-DLE-Tier": "1",
            "X-DLE-API-Version": DLE_API_VERSION,
        }
        _record_http_metric("/v1beta/models/{model}:generateContent", 200)
        log.info(
            "gateway.generate",
            route="/v1beta/models/{model}:generateContent",
            model=run_req.model,
            release_mode="released_advisory",
            session_id=run_req.session_id,
            run_id=run_req.run_id,
            duration_ms=round((time.perf_counter() - start) * 1000.0, 3),
        )
        return JSONResponse(status_code=200, content=out_body, headers=headers)

    @app.post("/v1beta/models/{model}:streamGenerateContent")
    async def stream_generate_content(
        request: Request,
        model: str,
        alt: str | None = Query(default=None),
    ) -> Response:
        tenant, client_key = _require_client_auth(request, runtime.settings)
        raw_body = await _parse_json_object(request)
        explicit_session = request.headers.get("x-dle-session")
        run_req = translate_generate_request(
            model=model,
            body=raw_body,
            tenant=tenant,
            explicit_session=explicit_session,
            is_streaming=True,
            alt=alt,
        )
        runtime.sessions.touch(run_req.session_id, tenant=tenant, model=run_req.model)
        upstream_key = _upstream_key(runtime.settings, client_key)

        target_model = (
            runtime.registry.pin_for_job("writer") if run_req.is_governed else run_req.model
        )
        job = "writer" if run_req.is_governed else "passthrough"
        release_mode = "released_advisory" if run_req.is_governed else "passthrough"
        headers: dict[str, str] = {
            "X-DLE-Release-Mode": release_mode,
            "X-DLE-API-Version": DLE_API_VERSION,
        }
        if run_req.is_governed:
            headers["X-DLE-Receipt"] = run_req.run_id
            headers["X-DLE-Tier"] = "1"

        stream_iter = runtime.model_port.stream_generate(
            target_model,
            run_req.raw_body,
            api_key=upstream_key,
            job=job,
        )

        if alt == "sse":
            # Pull first chunk before opening StreamingResponse so 4xx/503 map to HTTP errors.
            first_chunk = await anext(stream_iter, None)
            headers["Cache-Control"] = "no-cache"

            async def _sse_body() -> AsyncIterator[str]:
                if first_chunk is not None:
                    yield f"data: {json.dumps(first_chunk)}\n\n"
                async for chunk in stream_iter:
                    yield f"data: {json.dumps(chunk)}\n\n"

            _record_http_metric("/v1beta/models/{model}:streamGenerateContent", 200)
            return StreamingResponse(_sse_body(), media_type="text/event-stream", headers=headers)

        chunks = [chunk async for chunk in stream_iter]
        _record_http_metric("/v1beta/models/{model}:streamGenerateContent", 200)
        return JSONResponse(status_code=200, content=chunks, headers=headers)

    @app.post("/v1beta/models/{model}:countTokens")
    async def count_tokens(request: Request, model: str) -> JSONResponse:
        _tenant, client_key = _require_client_auth(request, runtime.settings)
        raw_body = await _parse_json_object(request)
        clean = normalize_model_id(model)
        target_model = (
            runtime.registry.pin_for_job("writer") if clean in _VIRTUAL_MODELS_BY_ID else clean
        )
        res = await runtime.model_port.count_tokens(
            target_model,
            raw_body,
            api_key=_upstream_key(runtime.settings, client_key),
        )
        _record_http_metric("/v1beta/models/{model}:countTokens", 200)
        return JSONResponse(
            status_code=200,
            content=res.body,
            headers={"X-DLE-API-Version": DLE_API_VERSION},
        )

    @app.get("/v1/receipts/{receiptId}")
    async def get_receipt(request: Request, receiptId: str) -> JSONResponse:
        _tenant, _key = _require_client_auth(request, runtime.settings)
        if not _RECEIPT_ID_RE.match(receiptId):
            raise ContractValidationError(
                f"invalid receiptId format: {receiptId!r}",
                file_path="request",
                pointer="/receiptId",
            )
        stored = runtime.receipts.get(receiptId)
        if stored is None:
            _record_http_metric("/v1/receipts/{receiptId}", 404)
            return gemini_error_response(404, f"receipt {receiptId} not found", "NOT_FOUND")
        _record_http_metric("/v1/receipts/{receiptId}", 200)
        return JSONResponse(
            status_code=200,
            content=stored,
            headers={"X-DLE-API-Version": DLE_API_VERSION},
        )

    @app.get("/v1/sources")
    async def list_sources(
        request: Request,
        pageToken: str | None = Query(default=None),
    ) -> JSONResponse:
        del pageToken
        _tenant, _key = _require_client_auth(request, runtime.settings)
        _record_http_metric("/v1/sources", 200)
        return JSONResponse(
            status_code=200,
            content={"sources": list(runtime.sources.values())},
            headers={"X-DLE-API-Version": DLE_API_VERSION},
        )

    @app.post("/admin/sources")
    async def register_source(request: Request) -> JSONResponse:
        _admin = _require_admin_auth(request, runtime.settings)
        raw_body = await _parse_json_object(request)
        for required_key in ("title", "authorityClass", "content"):
            if required_key not in raw_body:
                raise ContractValidationError(
                    f"missing required field {required_key!r}",
                    file_path="request",
                    pointer=f"/{required_key}",
                )
        source_id = str(uuid.uuid4())
        record: dict[str, object] = {
            "sourceId": source_id,
            "title": str(raw_body["title"]),
            "authorityClass": str(raw_body["authorityClass"]),
            "revision": "rev-1",
            "validFrom": str(raw_body.get("validFrom") or datetime.now(UTC).date().isoformat()),
            "validTo": raw_body.get("validTo"),
            "retainable": bool(raw_body.get("retainable", True)),
        }
        runtime.sources[source_id] = record
        _record_http_metric("/admin/sources", 201)
        return JSONResponse(
            status_code=201,
            content=record,
            headers={"X-DLE-API-Version": DLE_API_VERSION},
        )

    @app.post("/admin/drift/reset")
    async def reset_drift_latch(request: Request) -> Response:
        admin_id = _require_admin_auth(request, runtime.settings)
        raw_body = await _parse_json_object(request)
        artifact_id = raw_body.get("calibrationArtifactId")
        confirm = raw_body.get("confirm")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ContractValidationError(
                "calibrationArtifactId must be a non-empty string",
                file_path="request",
                pointer="/calibrationArtifactId",
            )
        if confirm != "RESET":
            raise ContractValidationError(
                "confirm must equal 'RESET'",
                file_path="request",
                pointer="/confirm",
            )
        runtime.registry.reset_drift_latch()
        log.info(
            "admin.drift_reset",
            admin_id=admin_id,
            calibration_artifact_id=artifact_id,
        )
        _record_http_metric("/admin/drift/reset", 204)
        return Response(status_code=204, headers={"X-DLE-API-Version": DLE_API_VERSION})

    @app.post("/admin/keys/rotate")
    async def rotate_signing_key(request: Request) -> JSONResponse:
        admin_id = _require_admin_auth(request, runtime.settings)
        new_key_id = f"ed25519-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        log.info("admin.key_rotate", admin_id=admin_id, key_id=new_key_id)
        _record_http_metric("/admin/keys/rotate", 200)
        return JSONResponse(
            status_code=200,
            content={
                "keyId": new_key_id,
                "validFrom": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            headers={"X-DLE-API-Version": DLE_API_VERSION},
        )

    @app.post("/admin/receipts/export")
    async def export_receipts(request: Request) -> Response:
        admin_id = _require_admin_auth(request, runtime.settings)
        raw_body = await _parse_json_object(request)
        if not isinstance(raw_body.get("from"), str) or not isinstance(raw_body.get("to"), str):
            raise ContractValidationError(
                "'from' and 'to' ISO timestamps are required",
                file_path="request",
                pointer="/",
            )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            manifest = {
                "from": raw_body["from"],
                "to": raw_body["to"],
                "receipts": [],
                "exportedBy": admin_id,
            }
            zf.writestr("manifest.json", json.dumps(manifest))
        _record_http_metric("/admin/receipts/export", 200)
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"X-DLE-API-Version": DLE_API_VERSION},
        )

    ui_dist = eff_settings.ui_dist_dir
    if ui_dist is not None and (ui_dist / "index.html").is_file():
        index_html = ui_dist / "index.html"
        assets_dir = ui_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="ui-assets")

        @app.get("/", include_in_schema=False)
        async def serve_ui_index() -> FileResponse:
            return FileResponse(index_html)

    return app


app = create_app()


def _resolve_default_root(path: Path | None) -> Path:
    return path if path is not None else Path.cwd()


__all__ = [
    "DLE_API_VERSION",
    "VIRTUAL_MODELS",
    "GatewayRuntime",
    "app",
    "create_app",
    "gemini_error_response",
]
