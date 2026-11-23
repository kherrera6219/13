"""FastAPI Gemini-compatible gateway serving all routes in ``contracts/openapi.yaml``.

Implements FR-API-01..08, IR-01..07, NFR-SEC-01..03, NFR-OBS-01, ADR-001, and
ADR-011. Serves ``v1beta`` Gemini routes, ``/v1`` DLE endpoints, ``/admin``
loopback-only routes, ``/healthz``, and static browser UI assets.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hmac
import json
import re
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dle import __version__
from dle.config import DleConfig, load_config
from dle.edge.composer import DLE_API_VERSION, ResponseComposer
from dle.edge.sessions import InMemorySessionStore, session_id_after_response
from dle.edge.settings import GatewaySettings, validate_bind
from dle.edge.streaming import split_response_chunks, stream_governed_sse
from dle.edge.tools import ToolBridge, extract_function_calls, extract_model_content
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
from dle.host.functions import FunctionRegistry, register_phase1_functions
from dle.host.services import (
    CalibrationArtifact,
    ClaimExtractor,
    ClaimVerifier,
    Ed25519KeyManager,
    EvidenceService,
    ReceiptSealer,
    RegistrySnapshot,
    load_registry,
)
from dle.host.workflow import (
    DEFAULT_PHASE2_CALIBRATION,
    run_governed_phase2,
    seal_cancelled_receipt,
)
from dle.models import (
    DeterministicLexicalNliScorer,
    EgressClient,
    EmbeddingService,
    FakeModel,
    GeminiAdapter,
    ModelPort,
    ModelRegistry,
    NliScorer,
    OnnxNliScorer,
)
from dle.observability import METRICS, get_logger, sha256_text
from dle.store import (
    EvidenceRepository,
    OpsRepository,
    ReceiptRepository,
    SessionRepository,
    StoreBundle,
    open_stores,
)

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
    """Runtime container held on ``app.state.dle``."""

    settings: GatewaySettings
    config: DleConfig
    registry: ModelRegistry
    model_port: ModelPort
    sessions: InMemorySessionStore
    function_registry: FunctionRegistry
    tool_bridge: ToolBridge
    composer: ResponseComposer
    stores: StoreBundle
    evidence_repo: EvidenceRepository
    session_repo: SessionRepository
    receipt_repo: ReceiptRepository
    ops_repo: OpsRepository
    embeddings: EmbeddingService
    nli_scorer: NliScorer
    evidence_service: EvidenceService
    claim_extractor: ClaimExtractor
    claim_verifier: ClaimVerifier
    key_manager: Ed25519KeyManager
    receipt_sealer: ReceiptSealer
    registry_snapshot: RegistrySnapshot
    calibration: CalibrationArtifact | None = DEFAULT_PHASE2_CALIBRATION
    egress: EgressClient | None = None


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


def _decode_source_content(raw_content: object) -> str:
    if isinstance(raw_content, str):
        if not raw_content.strip():
            raise ContractValidationError(
                "source content string must not be empty",
                file_path="request",
                pointer="/content",
            )
        return raw_content
    if isinstance(raw_content, Mapping):
        b64_data = raw_content.get("data")
        if not isinstance(b64_data, str) or not b64_data:
            raise ContractValidationError(
                "content.data must be a base64-encoded string",
                file_path="request",
                pointer="/content/data",
            )
        try:
            decoded = base64.b64decode(b64_data, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ContractValidationError(
                "content.data must be valid base64-encoded UTF-8 text",
                file_path="request",
                pointer="/content/data",
            ) from exc
        if not decoded.strip():
            raise ContractValidationError(
                "decoded source content must not be empty",
                file_path="request",
                pointer="/content/data",
            )
        return decoded
    raise ContractValidationError(
        "content must be a string or {mimeType, data} object",
        file_path="request",
        pointer="/content",
    )


def create_app(
    *,
    settings: GatewaySettings | None = None,
    config: DleConfig | None = None,
    model_port: ModelPort | None = None,
    registry: ModelRegistry | None = None,
    calibration: CalibrationArtifact | None = DEFAULT_PHASE2_CALIBRATION,
    nli_scorer: NliScorer | None = None,
) -> FastAPI:
    """Create and configure the FastAPI middleware application."""
    eff_settings = settings if settings is not None else GatewaySettings.from_env()
    validate_bind(eff_settings.bind_address, allow_lan=eff_settings.allow_lan)
    eff_settings.register_secrets()

    eff_config = config if config is not None else load_config(eff_settings.config_dir)
    eff_registry = registry if registry is not None else ModelRegistry(eff_config.model_pins)
    sessions = InMemorySessionStore()
    fn_registry = FunctionRegistry(eff_config.functions, eff_config.profiles)
    register_phase1_functions(fn_registry, eff_config.notices)
    fn_registry.self_check()
    tool_bridge = ToolBridge()
    composer = ResponseComposer(eff_config.notices)

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

    stores = open_stores(eff_settings.data_dir, enable_vec=True)
    evidence_repo = EvidenceRepository(stores.evidence, vec_enabled=stores.vec_enabled)
    session_repo = SessionRepository(stores.sessions)
    receipt_repo = ReceiptRepository(stores.receipts)
    ops_repo = OpsRepository(stores.ops)
    embeddings = EmbeddingService(eff_model_port, eff_registry)

    if nli_scorer is not None:
        eff_nli: NliScorer = nli_scorer
    elif eff_settings.nli_model_path is not None and eff_settings.nli_sha256:
        eff_nli = OnnxNliScorer(
            model_path=eff_settings.nli_model_path,
            expected_sha256=eff_settings.nli_sha256,
        )
    else:
        eff_nli = DeterministicLexicalNliScorer()

    evidence_service = EvidenceService(evidence_repo, embeddings)
    claim_extractor = ClaimExtractor(eff_model_port, eff_registry)
    claim_verifier = ClaimVerifier(eff_nli, evidence_service)
    key_manager = Ed25519KeyManager(receipt_repo, keys_dir=eff_settings.keys_dir)
    receipt_sealer = ReceiptSealer(receipt_repo, key_manager)
    default_pilot_dir = eff_settings.config_dir / "pilots" / "warehouse_substitution"
    eff_overlay_dir = (
        eff_settings.registry_overlay_dir
        if eff_settings.registry_overlay_dir is not None
        else (default_pilot_dir if default_pilot_dir.is_dir() else None)
    )
    registry_snapshot = load_registry(
        eff_settings.config_dir / "registry",
        overlay_dir=eff_overlay_dir,
        w3=eff_config.tiers.distance_weights.w3,
        w67=eff_config.tiers.distance_weights.w67,
    )

    runtime = GatewayRuntime(
        settings=eff_settings,
        config=eff_config,
        registry=eff_registry,
        model_port=eff_model_port,
        sessions=sessions,
        function_registry=fn_registry,
        tool_bridge=tool_bridge,
        composer=composer,
        stores=stores,
        evidence_repo=evidence_repo,
        session_repo=session_repo,
        receipt_repo=receipt_repo,
        ops_repo=ops_repo,
        embeddings=embeddings,
        nli_scorer=eff_nli,
        evidence_service=evidence_service,
        claim_extractor=claim_extractor,
        claim_verifier=claim_verifier,
        key_manager=key_manager,
        receipt_sealer=receipt_sealer,
        registry_snapshot=registry_snapshot,
        calibration=calibration,
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
            runtime.stores.close()

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
        ops_drift = runtime.ops_repo.get_drift_state()
        is_latched = runtime.registry.drift_latched or bool(
            ops_drift is not None and ops_drift.get("is_latched")
        )
        drift_state = "tripped" if is_latched else "clear"
        status = "ok" if reachable and not is_latched else "degraded"
        _record_http_metric("/healthz", 200)
        return {
            "status": status,
            "bind": f"{runtime.settings.bind_address}:{runtime.settings.port}",
            "modelReachable": reachable,
            "nliLoaded": runtime.nli_scorer.is_loaded,
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
        sess_rec = runtime.sessions.touch(run_req.session_id, tenant=tenant, model=run_req.model)
        runtime.session_repo.touch_session(
            session_id=run_req.session_id,
            tenant=tenant,
            model=run_req.model,
            now_utc=sess_rec.last_seen_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires_utc=sess_rec.expires_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        upstream_key = _upstream_key(runtime.settings, client_key)
        if not run_req.is_governed:
            if run_req.has_function_responses:
                runtime.tool_bridge.resume(run_req.session_id)
            res = await runtime.model_port.generate(
                run_req.model,
                run_req.raw_body,
                api_key=upstream_key,
                job="passthrough",
            )
            calls = extract_function_calls(res.body)
            if calls:
                model_content = extract_model_content(res.body)
                if model_content is not None:
                    next_sid = session_id_after_response(
                        tenant=tenant,
                        model=run_req.model,
                        system_instruction=run_req.system_instruction,
                        contents=run_req.contents,
                        response_content=model_content,
                        explicit_session=explicit_session,
                    )
                    runtime.tool_bridge.park(
                        run_id=run_req.run_id,
                        session_id=next_sid,
                        pending_calls=calls,
                        run_state={"model": run_req.model, "tenant": tenant},
                    )
            out_body, headers = runtime.composer.compose_passthrough(res.body)
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
            return JSONResponse(status_code=200, content=out_body, headers=headers)

        gov_res = await run_governed_phase2(
            run_req=run_req,
            config=runtime.config,
            function_registry=runtime.function_registry,
            model_registry=runtime.registry,
            model_port=runtime.model_port,
            evidence_service=runtime.evidence_service,
            claim_extractor=runtime.claim_extractor,
            claim_verifier=runtime.claim_verifier,
            receipt_sealer=runtime.receipt_sealer,
            ops_repo=runtime.ops_repo,
            session_repo=runtime.session_repo,
            calibration=runtime.calibration,
            api_key=upstream_key,
            registry_snapshot=runtime.registry_snapshot,
            enable_ppr=runtime.settings.enable_ppr,
        )
        out_body, headers = runtime.composer.compose_governed(
            release_mode=gov_res.release_mode,
            receipt_id=gov_res.receipt_id,
            tier=gov_res.tier,
            body=gov_res.body,
            notice_id=gov_res.notice_id,
            hold_reason=gov_res.hold_reason,
            rendered_body_complete=True,
        )
        _record_http_metric("/v1beta/models/{model}:generateContent", 200)
        log.info(
            "gateway.generate",
            route="/v1beta/models/{model}:generateContent",
            model=run_req.model,
            release_mode=gov_res.release_mode,
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
        sess_rec = runtime.sessions.touch(run_req.session_id, tenant=tenant, model=run_req.model)
        runtime.session_repo.touch_session(
            session_id=run_req.session_id,
            tenant=tenant,
            model=run_req.model,
            now_utc=sess_rec.last_seen_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires_utc=sess_rec.expires_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        upstream_key = _upstream_key(runtime.settings, client_key)

        if run_req.is_governed:

            async def _execute_governed_gate() -> tuple[dict[str, object], dict[str, str]]:
                gov_res = await run_governed_phase2(
                    run_req=run_req,
                    config=runtime.config,
                    function_registry=runtime.function_registry,
                    model_registry=runtime.registry,
                    model_port=runtime.model_port,
                    evidence_service=runtime.evidence_service,
                    claim_extractor=runtime.claim_extractor,
                    claim_verifier=runtime.claim_verifier,
                    receipt_sealer=runtime.receipt_sealer,
                    ops_repo=runtime.ops_repo,
                    session_repo=runtime.session_repo,
                    calibration=runtime.calibration,
                    api_key=upstream_key,
                    registry_snapshot=runtime.registry_snapshot,
                    enable_ppr=runtime.settings.enable_ppr,
                )
                return runtime.composer.compose_governed(
                    release_mode=gov_res.release_mode,
                    receipt_id=gov_res.receipt_id,
                    tier=gov_res.tier,
                    body=gov_res.body,
                    notice_id=gov_res.notice_id,
                    hold_reason=gov_res.hold_reason,
                    rendered_body_complete=True,
                )

            def _on_cancel() -> None:
                seal_cancelled_receipt(
                    run_req=run_req,
                    config=runtime.config,
                    function_registry=runtime.function_registry,
                    model_registry=runtime.registry,
                    receipt_sealer=runtime.receipt_sealer,
                    calibration=runtime.calibration,
                )

            if alt == "sse":
                _record_http_metric("/v1beta/models/{model}:streamGenerateContent", 200)
                return StreamingResponse(
                    stream_governed_sse(
                        _execute_governed_gate(),
                        keepalive_interval_s=runtime.settings.keepalive_interval_s,
                        on_cancel=_on_cancel,
                    ),
                    media_type="text/event-stream",
                    headers={
                        "X-DLE-Tier": "1",
                        "X-DLE-API-Version": DLE_API_VERSION,
                        "Cache-Control": "no-cache",
                    },
                )

            out_body, out_headers = await _execute_governed_gate()
            _record_http_metric("/v1beta/models/{model}:streamGenerateContent", 200)
            return JSONResponse(
                status_code=200,
                content=split_response_chunks(out_body),
                headers=out_headers,
            )

        if run_req.has_function_responses:
            runtime.tool_bridge.resume(run_req.session_id)
        headers: dict[str, str] = {
            "X-DLE-Release-Mode": "passthrough",
            "X-DLE-API-Version": DLE_API_VERSION,
        }
        stream_iter = runtime.model_port.stream_generate(
            run_req.model,
            run_req.raw_body,
            api_key=upstream_key,
            job="passthrough",
        )

        if alt == "sse":
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
        stored = runtime.receipt_sealer.get_receipt(receiptId)
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
        _tenant, _key = _require_client_auth(request, runtime.settings)
        offset = int(pageToken) if pageToken is not None and pageToken.isdigit() else 0
        sources, next_tok = runtime.evidence_repo.list_sources(limit=50, offset=offset)
        body: dict[str, object] = {"sources": sources}
        if next_tok is not None:
            body["nextPageToken"] = next_tok
        _record_http_metric("/v1/sources", 200)
        return JSONResponse(
            status_code=200,
            content=body,
            headers={"X-DLE-API-Version": DLE_API_VERSION},
        )

    @app.post("/admin/sources")
    async def register_source(request: Request) -> JSONResponse:
        admin_id = _require_admin_auth(request, runtime.settings)
        raw_body = await _parse_json_object(request)
        for required_key in ("title", "authorityClass", "content"):
            if required_key not in raw_body:
                raise ContractValidationError(
                    f"missing required field {required_key!r}",
                    file_path="request",
                    pointer=f"/{required_key}",
                )
        content_text = _decode_source_content(raw_body["content"])
        valid_from = str(raw_body["validFrom"]) if raw_body.get("validFrom") is not None else None
        valid_to = str(raw_body["validTo"]) if raw_body.get("validTo") is not None else None
        jurisdiction = (
            str(raw_body["jurisdiction"]) if raw_body.get("jurisdiction") is not None else None
        )
        retainable = bool(raw_body.get("retainable", True))
        upstream_api_key = runtime.settings.gemini_api_key or ""
        record = await runtime.evidence_service.register_document(
            title=str(raw_body["title"]),
            authority_class=str(raw_body["authorityClass"]),
            content_text=content_text,
            jurisdiction=jurisdiction,
            valid_from=valid_from,
            valid_to=valid_to,
            retainable=retainable,
            api_key=upstream_api_key,
        )
        log.info(
            "admin.source_registered",
            admin_id=admin_id,
            source_id=record["sourceId"],
            authority_class=record["authorityClass"],
        )
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
        cal = runtime.calibration or DEFAULT_PHASE2_CALIBRATION
        runtime.ops_repo.upsert_drift_state(
            c_t=0.0,
            mu0=cal.mu_0,
            delta=cal.drift_delta,
            lambda_val=cal.drift_lambda,
            is_latched=False,
            latch_reason=None,
            updated_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
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
        rotated = runtime.key_manager.rotate_key()
        log.info("admin.key_rotate", admin_id=admin_id, key_id=rotated["keyId"])
        _record_http_metric("/admin/keys/rotate", 200)
        return JSONResponse(
            status_code=200,
            content={"keyId": rotated["keyId"], "validFrom": rotated["validFrom"]},
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
        archive = runtime.receipt_sealer.export_bundle(
            str(raw_body["from"]),
            str(raw_body["to"]),
            exported_by=admin_id,
        )
        _record_http_metric("/admin/receipts/export", 200)
        return Response(
            content=archive,
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

__all__ = [
    "DLE_API_VERSION",
    "VIRTUAL_MODELS",
    "GatewayRuntime",
    "app",
    "create_app",
    "gemini_error_response",
]
