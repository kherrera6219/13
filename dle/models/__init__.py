"""Model ports, adapters, registry, fake stub, and single allowlisted egress client."""

from dle.models.egress import (
    EgressClient,
    EgressEvent,
    EgressResponse,
    EgressSink,
    is_transport_error,
)
from dle.models.embeddings import EmbeddingService
from dle.models.fake import FakeGenerateHandler, FakeModel, RecordedModelCall
from dle.models.gemini import DEFAULT_GEMINI_BASE_URL, GeminiAdapter
from dle.models.nli import (
    DeterministicLexicalNliScorer,
    NliScore,
    NliScorer,
    OnnxNliScorer,
)
from dle.models.port import ModelCallResult, ModelPort
from dle.models.registry import ModelRegistry, ModelVersionDriftEvent, UsageCost

__all__ = [
    "DEFAULT_GEMINI_BASE_URL",
    "DeterministicLexicalNliScorer",
    "EgressClient",
    "EgressEvent",
    "EgressResponse",
    "EgressSink",
    "EmbeddingService",
    "FakeGenerateHandler",
    "FakeModel",
    "GeminiAdapter",
    "ModelCallResult",
    "ModelPort",
    "ModelRegistry",
    "ModelVersionDriftEvent",
    "NliScore",
    "NliScorer",
    "OnnxNliScorer",
    "RecordedModelCall",
    "UsageCost",
    "is_transport_error",
]
