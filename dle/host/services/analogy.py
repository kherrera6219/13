"""Cross-domain analogy hypothesis generator (``H8``, L4, ``DVSS-P09``).

Implements DLE-FNS-001 ``DVSS-P09``: proposes structural analogies across
Axis 3/6/7 crosswalks and spine edges as non-citable ``[TMP:ANALOGY:...]``
hypotheses for roles to test. Under the ``strict`` profile ``DVSS-P09`` is
disabled; under ``advisory`` it emits hypotheses that never count as evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import jsonschema

from dle.config.loader import canonicalize_jcs
from dle.host.services.overlay import can_cite_as_evidence
from dle.host.services.registry import RegistrySnapshot

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_P09_OUT_SCHEMA = _REPO_ROOT / "contracts" / "functions" / "p09.out.json"


@dataclass(frozen=True)
class AnalogyHypothesis:
    """Single non-evidence cross-domain analogy hypothesis for Quad role testing."""

    hypothesis_id: str
    source_atom: str
    target_atom: str
    relation: str
    label: str
    is_hypothesis: Literal[True] = True
    citable_as_evidence: Literal[False] = False

    def to_dict(self) -> dict[str, object]:
        """Serialize into a dictionary matching ``contracts/functions/p09.out.json``."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "source_atom": self.source_atom,
            "target_atom": self.target_atom,
            "relation": self.relation,
            "label": self.label,
            "is_hypothesis": True,
            "citable_as_evidence": False,
        }


def _hypothesis_id(src: str, dst: str, relation: str) -> str:
    digest = hashlib.sha256(
        canonicalize_jcs({"source": src, "target": dst, "relation": relation})
    ).hexdigest()
    return f"[TMP:ANALOGY:{digest[:12]}]"


def generate_cross_domain_analogies(
    *,
    query_anchors: Sequence[str],
    snapshot: RegistrySnapshot | None,
    max_analogies: int = 5,
    domain_hint: str | None = None,
    p09_out_schema_path: Path | None = None,
) -> tuple[AnalogyHypothesis, ...]:
    """Generate deterministic non-evidence cross-domain analogy hypotheses."""
    limit = max(0, min(10, int(max_analogies)))
    if snapshot is None or limit == 0 or not query_anchors:
        return ()

    anchor_set = {a.strip() for a in query_anchors if a.strip() and can_cite_as_evidence(a)}
    if not anchor_set:
        return ()

    raw_candidates: list[tuple[str, str, str, str]] = []
    for cw in snapshot.crosswalks:
        if cw.from_atom in anchor_set and can_cite_as_evidence(cw.to_atom):
            raw_candidates.append(
                (cw.from_atom, cw.to_atom, f"crosswalk:{cw.relation}", f"Axis-{cw.axis_id} link")
            )
        elif cw.to_atom in anchor_set and can_cite_as_evidence(cw.from_atom):
            raw_candidates.append(
                (cw.to_atom, cw.from_atom, f"crosswalk:{cw.relation}", f"Axis-{cw.axis_id} link")
            )

    for edge in snapshot.spine_edges:
        if edge.src in anchor_set and can_cite_as_evidence(edge.dst):
            raw_candidates.append(
                (edge.src, edge.dst, f"spine:{edge.edge_type}", f"Spine axis-{edge.axis_id}")
            )
        elif edge.dst in anchor_set and can_cite_as_evidence(edge.src):
            raw_candidates.append(
                (edge.dst, edge.src, f"spine:{edge.edge_type}", f"Spine axis-{edge.axis_id}")
            )

    raw_candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    hint_suffix = f" ({domain_hint.strip()})" if domain_hint and domain_hint.strip() else ""

    hypotheses: list[AnalogyHypothesis] = []
    seen_pairs: set[tuple[str, str]] = set()
    for src, dst, rel, desc in raw_candidates:
        if (src, dst) in seen_pairs or src == dst:
            continue
        seen_pairs.add((src, dst))
        hid = _hypothesis_id(src, dst, rel)
        hypotheses.append(
            AnalogyHypothesis(
                hypothesis_id=hid,
                source_atom=src,
                target_atom=dst,
                relation=rel,
                label=f"Analogy candidate {src} -> {dst} via {desc}{hint_suffix} [hypothesis only]",
            )
        )
        if len(hypotheses) >= limit:
            break

    schema_path = p09_out_schema_path or _DEFAULT_P09_OUT_SCHEMA
    if schema_path.is_file():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate({"hypotheses": [h.to_dict() for h in hypotheses]}, schema)

    return tuple(hypotheses)


__all__ = [
    "AnalogyHypothesis",
    "generate_cross_domain_analogies",
]
