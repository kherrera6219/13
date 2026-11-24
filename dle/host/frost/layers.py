"""FROST 10-layer stack constants and deterministic step trace collector (``FR-FL-01..07``).

Maps the 12 canonical orchestration steps (``s01_ingest``..``s12_seal``) to the
10 FROST stack layers (``l01_grounding``..``l10_receipt``) and emits compact
ID/timing telemetry without logging user or passage content.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

STEP_IDS: tuple[str, ...] = (
    "s01_ingest",
    "s02_anchor",
    "s03_screen",
    "s04_retrieve",
    "s05_deliberate",
    "s06_reconcile",
    "s07_crosswalk",
    "s08_scope",
    "s09_verify_authority",
    "s10_score",
    "s11_refine_decide",
    "s12_seal",
)

FROST_LAYERS: tuple[str, ...] = (
    "l01_grounding",
    "l02_retrieval",
    "l03_persona_selection",
    "l04_deliberation",
    "l05_arbitration",
    "l06_alignment",
    "l07_scope",
    "l08_verification",
    "l09_decision",
    "l10_receipt",
)

STEP_TO_LAYER: dict[str, str] = {
    "s01_ingest": "l01_grounding",
    "s02_anchor": "l01_grounding",
    "s03_screen": "l02_retrieval",
    "s04_retrieve": "l02_retrieval",
    "s05_deliberate": "l04_deliberation",
    "s06_reconcile": "l05_arbitration",
    "s07_crosswalk": "l06_alignment",
    "s08_scope": "l07_scope",
    "s09_verify_authority": "l08_verification",
    "s10_score": "l08_verification",
    "s11_refine_decide": "l09_decision",
    "s12_seal": "l10_receipt",
}


@dataclass(frozen=True)
class StepTraceEntry:
    """Single step-level execution marker recorded across FROST layers."""

    step_id: str
    layer_id: str
    attempt_id: str
    event: str
    status: str
    dvss_ids: tuple[str, ...]
    duration_ms: float

    def to_metadata_dict(self) -> dict[str, object]:
        """Serialize compactly for ``dleMetadata.steps`` UI inspection."""
        return {
            "stepId": self.step_id,
            "layerId": self.layer_id,
            "attemptId": self.attempt_id,
            "event": self.event,
            "status": self.status,
            "dvssIds": list(self.dvss_ids),
            "durationMs": round(self.duration_ms, 3),
        }


class FrostTrace:
    """In-run collector enforcing canonical step/layer mapping across attempts."""

    def __init__(self) -> None:
        """Initialize an empty ordered trace."""
        self._entries: list[StepTraceEntry] = []

    def record(
        self,
        *,
        step_id: str,
        attempt_id: str,
        event: str,
        status: str,
        dvss_ids: Sequence[str] = (),
        duration_ms: float = 0.0,
        layer_override: str | None = None,
    ) -> StepTraceEntry:
        """Validate ``step_id`` and record an execution step entry."""
        if step_id not in STEP_TO_LAYER:
            raise ValueError(f"unknown DLE step_id {step_id!r}")
        layer_id = layer_override if layer_override is not None else STEP_TO_LAYER[step_id]
        if layer_id not in FROST_LAYERS:
            raise ValueError(f"unknown FROST layer_id {layer_id!r}")
        entry = StepTraceEntry(
            step_id=step_id,
            layer_id=layer_id,
            attempt_id=attempt_id,
            event=event,
            status=status,
            dvss_ids=tuple(dvss_ids),
            duration_ms=max(0.0, float(duration_ms)),
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[StepTraceEntry, ...]:
        """Return immutable recorded step trace entries in execution order."""
        return tuple(self._entries)

    def completed_steps(self) -> tuple[str, ...]:
        """Return distinct completed step IDs in first-seen order."""
        seen: set[str] = set()
        out: list[str] = []
        for entry in self._entries:
            if entry.step_id not in seen:
                seen.add(entry.step_id)
                out.append(entry.step_id)
        return tuple(out)

    def completed_layers(self) -> tuple[str, ...]:
        """Return distinct visited FROST layer IDs in first-seen order."""
        seen: set[str] = set()
        out: list[str] = []
        for entry in self._entries:
            if entry.layer_id not in seen:
                seen.add(entry.layer_id)
                out.append(entry.layer_id)
        return tuple(out)

    def to_metadata_list(self) -> list[dict[str, object]]:
        """Serialize ordered step trace for ``dleMetadata.steps``."""
        return [entry.to_metadata_dict() for entry in self._entries]


__all__ = [
    "FROST_LAYERS",
    "STEP_IDS",
    "STEP_TO_LAYER",
    "FrostTrace",
    "StepTraceEntry",
]
