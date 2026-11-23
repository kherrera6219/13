"""Edge layer: Gemini-compatible HTTP façade, auth, session resolution, and translator."""

from dle.edge.composer import DLE_API_VERSION, ResponseComposer
from dle.edge.gateway import (
    VIRTUAL_MODELS,
    GatewayRuntime,
    app,
    create_app,
    gemini_error_response,
)
from dle.edge.sessions import (
    MAX_EXPLICIT_SESSION_LEN,
    InMemorySessionStore,
    SessionRecord,
    resolve_session_id,
    session_id_after_response,
)
from dle.edge.settings import (
    LOOPBACK_HOSTS,
    GatewaySettings,
    validate_bind,
)
from dle.edge.streaming import (
    DEFAULT_KEEPALIVE_INTERVAL_S,
    split_response_chunks,
    stream_governed_sse,
)
from dle.edge.tools import (
    ParkedRun,
    ToolBridge,
    extract_function_calls,
    extract_model_content,
)
from dle.edge.translator import (
    GOVERNED_MODELS,
    RunRequest,
    normalize_model_id,
    translate_generate_request,
)

__all__ = [
    "DEFAULT_KEEPALIVE_INTERVAL_S",
    "DLE_API_VERSION",
    "GOVERNED_MODELS",
    "LOOPBACK_HOSTS",
    "MAX_EXPLICIT_SESSION_LEN",
    "VIRTUAL_MODELS",
    "GatewayRuntime",
    "GatewaySettings",
    "InMemorySessionStore",
    "ParkedRun",
    "ResponseComposer",
    "RunRequest",
    "SessionRecord",
    "ToolBridge",
    "app",
    "create_app",
    "extract_function_calls",
    "extract_model_content",
    "gemini_error_response",
    "normalize_model_id",
    "resolve_session_id",
    "session_id_after_response",
    "split_response_chunks",
    "stream_governed_sse",
    "translate_generate_request",
    "validate_bind",
]
