"""Per-session ephemeral USKD overlay and TMP hypothesis nodes (``H7``).

Implements DLE-SPC-003 (A2, A3, §4.5) and ``DVSS-P03`` (session node synthesis):
tracks per-session depth <= 7 dynamic drill-down branches and synthetic hypotheses
with ``[TMP:5.TMP.<uuid>]`` identifiers, forbids citing TMP nodes as durable
evidence, and clears ephemeral session nodes when the run is sealed.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from dle.host.services.registry import SpineEdge

MAX_BRANCH_DEPTH = 7


def can_cite_as_evidence(atom_id: str) -> bool:
    """Return False for session-derived ``[TMP:...]`` nodes (``DVSS-P03``)."""
    return not atom_id.strip().startswith("[TMP:")


@dataclass(frozen=True)
class SessionTmpNode:
    """Ephemeral session hypothesis/branch node created in the USKD overlay."""

    canonical_str: str
    session_uuid: str
    node_uuid: str
    label: str
    parent_atom: str
    depth: int
    via_links: tuple[str, ...]
    anchor_atoms: tuple[str, ...]
    is_hypothesis: bool = True
    status: str = "synthetic_derived"


class SessionOverlay:
    """Mutable per-run USKD overlay wiped cleanly when the sealed receipt commits."""

    def __init__(self, session_uuid: str) -> None:
        """Initialize overlay bound to ``session_uuid``."""
        self.session_uuid = session_uuid
        self._nodes: dict[str, SessionTmpNode] = {}
        self._edges: list[SpineEdge] = []

    def add_branch_candidate(
        self,
        *,
        label: str,
        parent_atom: str,
        depth: int,
        via_links: Sequence[str] = (),
        node_uuid: str | None = None,
    ) -> SessionTmpNode:
        """Add an Axis 4 dynamic drill-down node at bounded depth ``1..7``."""
        if depth < 1 or depth > MAX_BRANCH_DEPTH:
            raise ValueError(f"USKD overlay depth must be in [1, {MAX_BRANCH_DEPTH}], got {depth}")
        clean_label = label.strip()
        if not clean_label:
            raise ValueError("session TMP node label must not be empty")

        eff_uuid = node_uuid if node_uuid is not None else str(uuid.uuid4())
        canonical = f"[TMP:5.TMP.{eff_uuid}]"
        node = SessionTmpNode(
            canonical_str=canonical,
            session_uuid=self.session_uuid,
            node_uuid=eff_uuid,
            label=clean_label,
            parent_atom=parent_atom,
            depth=depth,
            via_links=tuple(via_links),
            anchor_atoms=(parent_atom,),
            is_hypothesis=True,
        )
        self._nodes[canonical] = node
        self._edges.append(
            SpineEdge(
                src=parent_atom,
                dst=canonical,
                edge_type="session_tmp_branch",
                weight=1.0,
                axis_id=5,
            )
        )
        for link_id in via_links:
            self._edges.append(
                SpineEdge(
                    src=link_id,
                    dst=canonical,
                    edge_type="session_tmp_via_link",
                    weight=1.0,
                    axis_id=5,
                )
            )
        return node

    def synthesize_hypothesis(
        self,
        *,
        label: str,
        anchor_atoms: Sequence[str],
        via_links: Sequence[str] = (),
        node_uuid: str | None = None,
    ) -> SessionTmpNode:
        """Synthesize a ``DVSS-P03`` hypothesis node anchored to retrieved coordinate atoms."""
        anchors = tuple(a.strip() for a in anchor_atoms if a.strip())
        if not anchors:
            raise ValueError("synthesize_hypothesis requires at least one anchor atom")
        clean_label = label.strip()
        if not clean_label:
            raise ValueError("hypothesis node label must not be empty")

        eff_uuid = node_uuid if node_uuid is not None else str(uuid.uuid4())
        canonical = f"[TMP:5.TMP.{eff_uuid}]"
        node = SessionTmpNode(
            canonical_str=canonical,
            session_uuid=self.session_uuid,
            node_uuid=eff_uuid,
            label=clean_label,
            parent_atom=anchors[0],
            depth=1,
            via_links=tuple(via_links),
            anchor_atoms=anchors,
            is_hypothesis=True,
        )
        self._nodes[canonical] = node
        for anchor in anchors:
            self._edges.append(
                SpineEdge(
                    src=anchor,
                    dst=canonical,
                    edge_type="session_hypothesis",
                    weight=1.0,
                    axis_id=5,
                )
            )
        for link_id in via_links:
            self._edges.append(
                SpineEdge(
                    src=link_id,
                    dst=canonical,
                    edge_type="session_tmp_via_link",
                    weight=1.0,
                    axis_id=5,
                )
            )
        return node

    def list_nodes(self) -> tuple[SessionTmpNode, ...]:
        """Return currently active ephemeral nodes in deterministic order."""
        return tuple(self._nodes[k] for k in sorted(self._nodes))

    def overlay_edges(self) -> tuple[SpineEdge, ...]:
        """Return overlay spine edges connecting permanent atoms to active TMP nodes."""
        return tuple(self._edges)

    def clear_on_seal(self) -> int:
        """Wipe ephemeral TMP nodes & edges on run sealing (``DLE-SPC-003 §4.5``)."""
        removed = len(self._nodes)
        self._nodes.clear()
        self._edges.clear()
        return removed


__all__ = [
    "MAX_BRANCH_DEPTH",
    "SessionOverlay",
    "SessionTmpNode",
    "can_cite_as_evidence",
]
