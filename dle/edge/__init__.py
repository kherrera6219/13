"""Edge layer: Gemini-compatible HTTP façade, auth, session resolution, and translator."""

from dle.edge.gateway import (
    DLE_API_VERSION,
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
from dle.edge.translator import (
    GOVERNED_MODELS,
    RunRequest,
    normalize_model_id,
    translate_generate_request,
)

__all__ = [
    "DLE_API_VERSION",
    "GOVERNED_MODELS",
    "LOOPBACK_HOSTS",
    "MAX_EXPLICIT_SESSION_LEN",
    "VIRTUAL_MODELS",
    "GatewayRuntime",
    "GatewaySettings",
    "InMemorySessionStore",
    "RunRequest",
    "SessionRecord",
    "app",
    "create_app",
    "gemini_error_response",
    "normalize_model_id",
    "resolve_session_id",
    "session_id_after_response",
    "translate_generate_request",
    "validate_bind",
]
