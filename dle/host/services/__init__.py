"""Host domain services package (pilot §18 reference pipeline and Phase 2+ services)."""

from dle.host.services.evidence import (
    AUTHORITY_PRIOR,
    QUALIFYING_BINDING_CLASSES,
    AuthorityCheckResult,
    EvidenceService,
    RetrievalResult,
    RetrievedPassage,
    chunk_document_text,
)
from dle.host.services.pilot import (
    CoordinateResolver,
    DriftMonitor,
    PilotClaim,
    PilotExecutionResult,
    PilotObjection,
    PilotPassage,
    PilotPipeline,
    PilotReceiptSealer,
    calibrate_crc,
    compute_nonconformity,
    pack_hydrated,
    ppr,
)

__all__ = [
    "AUTHORITY_PRIOR",
    "QUALIFYING_BINDING_CLASSES",
    "AuthorityCheckResult",
    "CoordinateResolver",
    "DriftMonitor",
    "EvidenceService",
    "PilotClaim",
    "PilotExecutionResult",
    "PilotObjection",
    "PilotPassage",
    "PilotPipeline",
    "PilotReceiptSealer",
    "RetrievalResult",
    "RetrievedPassage",
    "calibrate_crc",
    "chunk_document_text",
    "compute_nonconformity",
    "pack_hydrated",
    "ppr",
]
