"""Model ports, adapters, registry, fake stub, and single allowlisted egress client."""

from dle.models.egress import (
    EgressClient,
    EgressEvent,
    EgressResponse,
    EgressSink,
    is_transport_error,
)
from dle.models.fake import FakeGenerateHandler, FakeModel, RecordedModelCall
from dle.models.gemini import DEFAULT_GEMINI_BASE_URL, GeminiAdapter
from dle.models.port import ModelCallResult, ModelPort
from dle.models.registry import ModelRegistry, ModelVersionDriftEvent, UsageCost

__all__ = [
    "DEFAULT_GEMINI_BASE_URL",
    "EgressClient",
    "EgressEvent",
    "EgressResponse",
    "EgressSink",
    "FakeGenerateHandler",
    "FakeModel",
    "GeminiAdapter",
    "ModelCallResult",
    "ModelPort",
    "ModelRegistry",
    "ModelVersionDriftEvent",
    "RecordedModelCall",
    "UsageCost",
    "is_transport_error",
]
