"""Offline quarantined promotion staging for session TMP nodes (``O2``, ``DVSS-P05``).

Implements DLE-FNS-001 ``DVSS-P05``: stages eligible session-derived hypothesis
nodes into a separate review staging directory with JCS integrity digests without
ever writing to the live 13-axis registry or SQLite stores.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import jsonschema

from dle.config.loader import canonicalize_jcs
from dle.errors import ContractValidationError
from dle.host.services.overlay import MAX_BRANCH_DEPTH, SessionTmpNode, can_cite_as_evidence

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_LIVE_REGISTRY_DIR = _REPO_ROOT / "config" / "registry"
_DEFAULT_P05_OUT_SCHEMA = _REPO_ROOT / "contracts" / "functions" / "p05.out.json"


@dataclass(frozen=True)
class StagedPromotionCandidate:
    """Validated session-derived candidate staged for human registry review."""

    canonical_str: str
    label: str
    parent_atom: str
    depth: int
    anchor_atoms: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class PromotionStagingResult:
    """Structured result emitted by ``DVSS-P05`` offline quarantined promotion."""

    staging_id: str
    staging_sha256: str
    staging_path: Path | None
    staged_count: int
    rejected_count: int
    rejected_reasons: tuple[str, ...]
    live_registry_modified: Literal[False]
    status: Literal["staged_for_review", "empty"]

    def to_contract_output(self) -> dict[str, object]:
        """Serialize into a dictionary conforming to ``contracts/functions/p05.out.json``."""
        return {
            "staging_id": self.staging_id,
            "staging_sha256": self.staging_sha256,
            "staged_count": self.staged_count,
            "rejected_count": self.rejected_count,
            "rejected_reasons": list(self.rejected_reasons),
            "live_registry_modified": False,
            "status": self.status,
        }


def _assert_not_live_registry(staging_dir: Path, live_registry_dir: Path) -> None:
    resolved_stage = staging_dir.resolve()
    resolved_live = live_registry_dir.resolve()
    if resolved_stage == resolved_live or resolved_live in resolved_stage.parents:
        raise ContractValidationError(
            "DVSS-P05 staging_dir must be separate from live config/registry directory",
            file_path=str(staging_dir),
            pointer="/target_staging_dir",
        )


def stage_quarantined_nodes(
    *,
    session_uuid: str,
    nodes: Sequence[SessionTmpNode],
    staging_dir: Path,
    staged_by: str = "registry-reviewer",
    live_registry_dir: Path | None = None,
    evidence_refs_by_node: Mapping[str, Sequence[str]] | None = None,
    created_utc: str | None = None,
    p05_out_schema_path: Path | None = None,
) -> PromotionStagingResult:
    """Quarantine and stage eligible ``[TMP:...]`` nodes for offline registry review."""
    clean_session = session_uuid.strip()
    if not clean_session:
        raise ContractValidationError(
            "session_uuid must be non-empty",
            file_path="promotion",
            pointer="/session_uuid",
        )
    clean_actor = staged_by.strip() or "registry-reviewer"
    _assert_not_live_registry(staging_dir, live_registry_dir or _DEFAULT_LIVE_REGISTRY_DIR)

    accepted: list[StagedPromotionCandidate] = []
    rejected_reasons: list[str] = []
    seen_keys: set[tuple[str, str]] = set()
    refs_map = evidence_refs_by_node or {}

    for node in nodes:
        cid = node.canonical_str.strip()
        label = node.label.strip()
        if not cid.startswith("[TMP:"):
            rejected_reasons.append(f"{cid or '<empty>'}: non-TMP node excluded")
            continue
        if node.depth < 1 or node.depth > MAX_BRANCH_DEPTH:
            rejected_reasons.append(f"{cid}: depth {node.depth} outside [1, {MAX_BRANCH_DEPTH}]")
            continue
        if not label:
            rejected_reasons.append(f"{cid}: empty label")
            continue
        perm_anchors = tuple(
            a.strip() for a in node.anchor_atoms if a.strip() and can_cite_as_evidence(a)
        )
        if not perm_anchors:
            rejected_reasons.append(f"{cid}: no permanent non-TMP anchor atoms")
            continue
        dedup_key = (cid, label.lower())
        if dedup_key in seen_keys:
            rejected_reasons.append(f"{cid}: duplicate candidate")
            continue
        seen_keys.add(dedup_key)

        node_refs = tuple(str(r).strip() for r in refs_map.get(cid, ()) if str(r).strip())
        accepted.append(
            StagedPromotionCandidate(
                canonical_str=cid,
                label=label,
                parent_atom=node.parent_atom.strip(),
                depth=node.depth,
                anchor_atoms=perm_anchors,
                evidence_refs=node_refs,
            )
        )

    now_utc = created_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle: dict[str, object] = {
        "schema_version": "1.0.0",
        "dvss_id": "DVSS-P05",
        "session_uuid": clean_session,
        "staged_by": clean_actor,
        "created_utc": now_utc,
        "reviewed": False,
        "live_registry_modified": False,
        "candidates": [
            {
                "canonical_str": c.canonical_str,
                "label": c.label,
                "parent_atom": c.parent_atom,
                "depth": c.depth,
                "anchor_atoms": list(c.anchor_atoms),
                "evidence_refs": list(c.evidence_refs),
            }
            for c in accepted
        ],
    }
    staging_sha256 = hashlib.sha256(canonicalize_jcs(bundle)).hexdigest()
    staging_id = f"p05-{clean_session[:8]}-{staging_sha256[:10]}"

    out_path: Path | None = None
    status: Literal["staged_for_review", "empty"] = "staged_for_review" if accepted else "empty"
    if accepted:
        staging_dir.mkdir(parents=True, exist_ok=True)
        out_path = staging_dir / f"{staging_id}.json"
        bundle["staging_id"] = staging_id
        bundle["staging_sha256"] = staging_sha256
        out_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = PromotionStagingResult(
        staging_id=staging_id,
        staging_sha256=staging_sha256,
        staging_path=out_path,
        staged_count=len(accepted),
        rejected_count=len(rejected_reasons),
        rejected_reasons=tuple(rejected_reasons),
        live_registry_modified=False,
        status=status,
    )

    schema_path = p05_out_schema_path or _DEFAULT_P05_OUT_SCHEMA
    if schema_path.is_file():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(result.to_contract_output(), schema)
    return result


__all__ = [
    "PromotionStagingResult",
    "StagedPromotionCandidate",
    "stage_quarantined_nodes",
]
