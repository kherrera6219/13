"""Deterministic bounded PPR graph retrieval & ontology crosswalk alignment (``H6``).

Implements ``DVSS-K07`` (bounded expansion: Personalized PageRank alpha=0.85,
<= 80 iterations, L1 <= 1.76e-6, <= 250 vertices, hop budget by tier/retry <= 4,
post-hydration edge/token re-budgeting, reserved synthetic slots) and ``DVSS-P06``
(cross-axis crosswalk term reconciliation).
"""

from __future__ import annotations

import heapq
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from dle.config.loader import canonicalize_jcs
from dle.host.services.overlay import SessionOverlay
from dle.host.services.pilot import ppr
from dle.host.services.registry import RegistrySnapshot, SpineEdge
from dle.observability import sha256_text

_AXIS_NUM_RE = re.compile(r"^\[[A-Z][A-Z0-9-]*:(1[0-3]|[1-9])(?:\.|#|$)")


@dataclass(frozen=True)
class RetainedVertex:
    """Graph vertex surviving hop/score pruning and post-hydration capacity budgets."""

    vertex_id: str
    axis_id: int
    score: float
    hop: int
    distance: float
    synthetic: bool
    token_cost: int


@dataclass(frozen=True)
class RetainedEdge:
    """Canonical edge preserved inside the bounded subgraph."""

    src: str
    dst: str
    edge_type: str
    weight: float
    predicate: str | None = None


@dataclass(frozen=True)
class GraphExpansionResult:
    """Deterministic output of ``DVSS-K07`` bounded Personalized PageRank expansion."""

    vertices: tuple[RetainedVertex, ...]
    edges: tuple[RetainedEdge, ...]
    ppr_iterations: int
    converged: bool
    effective_hops: int
    graph_sha256: str
    pruned_count: int
    reserved_synthetic_used: int


@dataclass(frozen=True)
class AlignedTermGroup:
    """Terms linked by ``equivalent``, ``overlaps``, or ``is_analogous_to`` crosswalks."""

    canonical_atom: str
    related_atoms: tuple[str, ...]
    relations: tuple[str, ...]


@dataclass(frozen=True)
class UnresolvedAlignment:
    """Crosswalk tension preserved for downstream review (``conflicts`` / ``depends_on``)."""

    from_atom: str
    to_atom: str
    relation: str
    reason: str


@dataclass(frozen=True)
class OntologyAlignmentResult:
    """Output of ``DVSS-P06`` ontology alignment over registry crosswalks."""

    groups: tuple[AlignedTermGroup, ...]
    unresolved: tuple[UnresolvedAlignment, ...]


def effective_hop_budget(*, tier: int, retry_count: int = 0, max_hops: int = 4) -> int:
    """Compute bounded hop budget per ``DVSS-K07`` (1 at Tier 1, 2 at Tiers 2-3, +1/retry <= 4)."""
    base = 1 if tier <= 1 else 2
    return min(max_hops, base + max(0, retry_count))


def _infer_axis_id(vertex_id: str) -> int:
    m = _AXIS_NUM_RE.match(vertex_id.split("#", 1)[0])
    if m is not None:
        return int(m.group(1))
    return 0


def _is_synthetic(vertex_id: str) -> bool:
    return vertex_id.startswith("[TMP:")


def expand_bounded_ppr(
    *,
    anchors: Sequence[str],
    snapshot: RegistrySnapshot,
    tier: int,
    retry_count: int = 0,
    overlay: SessionOverlay | None = None,
    damping: float = 0.85,
    max_iterations: int = 80,
    tolerance: float = 1.76e-6,
    max_vertices: int = 250,
    max_edges: int = 500,
    max_tokens: int = 4000,
    max_hops: int = 4,
    min_score: float = 0.0,
    reserved_synthetic_slots: int = 5,
    excluded_atoms: Collection[str] = (),
    token_costs: Mapping[str, int] | None = None,
) -> GraphExpansionResult:
    """Execute deterministic ``DVSS-K07`` bounded Personalized PageRank over spine + overlay."""
    capped_vertices = min(max_vertices, 250)
    eff_hops = effective_hop_budget(tier=tier, retry_count=retry_count, max_hops=max_hops)
    blocked = set(snapshot.retired_ids) | set(excluded_atoms)

    canonical_seeds: list[str] = []
    seen_seeds: set[str] = set()
    for raw in anchors:
        canon, _ = snapshot.resolve_pillar_alias(raw.strip())
        if canon and canon not in blocked and canon not in seen_seeds:
            canonical_seeds.append(canon)
            seen_seeds.add(canon)

    if not canonical_seeds:
        empty_sha = sha256_text(canonicalize_jcs({"vertices": [], "edges": []}).decode("utf-8"))
        return GraphExpansionResult(
            vertices=(),
            edges=(),
            ppr_iterations=0,
            converged=True,
            effective_hops=eff_hops,
            graph_sha256=empty_sha,
            pruned_count=0,
            reserved_synthetic_used=0,
        )

    combined_edges: list[SpineEdge] = list(snapshot.spine_edges)
    if overlay is not None:
        combined_edges.extend(overlay.overlay_edges())

    # Build sorted undirected traversal neighbors for hop/distance bounded discovery.
    undirected: dict[str, list[tuple[str, float]]] = {}
    for edge in combined_edges:
        if edge.src in blocked or edge.dst in blocked or edge.weight <= 0.0:
            continue
        undirected.setdefault(edge.src, []).append((edge.dst, float(edge.weight)))
        undirected.setdefault(edge.dst, []).append((edge.src, float(edge.weight)))
    for node_id in undirected:
        undirected[node_id].sort(key=lambda item: (item[0], item[1]))

    # Shortest weighted hop-bounded BFS via Dijkstra keyed by (hop, dist, vertex_id).
    best_dist: dict[str, tuple[int, float]] = {}
    heap: list[tuple[int, float, str]] = []
    for seed in canonical_seeds:
        best_dist[seed] = (0, 0.0)
        heapq.heappush(heap, (0, 0.0, seed))

    while heap:
        hop, dist, cur = heapq.heappop(heap)
        if hop >= eff_hops:
            continue
        cur_best = best_dist[cur]
        if (hop, dist) > cur_best:
            continue
        for nxt, edge_w in undirected.get(cur, ()):
            nhop = hop + 1
            ndist = round(dist + edge_w, 6)
            cand = (nhop, ndist)
            prev = best_dist.get(nxt)
            if prev is None or cand < prev:
                best_dist[nxt] = cand
                heapq.heappush(heap, (nhop, ndist, nxt))

    reachable = set(best_dist)
    sub_adj: dict[str, list[tuple[str, float]]] = {}
    sub_edge_map: dict[tuple[str, str, str], RetainedEdge] = {}
    for edge in combined_edges:
        if edge.src not in reachable or edge.dst not in reachable or edge.weight <= 0.0:
            continue
        conductance = 1.0 / max(edge.weight, 1e-6)
        sub_adj.setdefault(edge.src, []).append((edge.dst, conductance))
        sub_adj.setdefault(edge.dst, []).append((edge.src, conductance))
        ekey = (edge.src, edge.dst, edge.edge_type)
        sub_edge_map[ekey] = RetainedEdge(
            src=edge.src,
            dst=edge.dst,
            edge_type=edge.edge_type,
            weight=float(edge.weight),
            predicate=edge.predicate,
        )

    for src in sub_adj:
        sub_adj[src].sort(key=lambda item: item[0])

    seed_weights = {seed: 1.0 for seed in canonical_seeds}
    scores, iterations = ppr(
        sub_adj,
        seed_weights,
        damping=damping,
        max_iterations=max_iterations,
        tolerance=tolerance,
    )

    # Check convergence flag accurately vs iteration cap.
    converged = iterations < max_iterations or iterations == 1
    if iterations == max_iterations and max_iterations > 1:
        # Recompute final one-step residual check to verify exact convergence at max_iterations.
        _, check_iters = ppr(
            sub_adj,
            seed_weights,
            damping=damping,
            max_iterations=max_iterations + 1,
            tolerance=tolerance,
        )
        converged = check_iters <= max_iterations

    cost_lookup = token_costs if token_costs is not None else {}
    raw_candidates: list[RetainedVertex] = []
    pruned_count = 0
    for vid in sorted(reachable):
        hop, dist = best_dist[vid]
        sc = round(float(scores.get(vid, 0.0)), 12)
        if sc < min_score or hop > eff_hops:
            pruned_count += 1
            continue
        raw_candidates.append(
            RetainedVertex(
                vertex_id=vid,
                axis_id=_infer_axis_id(vid),
                score=sc,
                hop=hop,
                distance=dist,
                synthetic=_is_synthetic(vid),
                token_cost=max(1, int(cost_lookup.get(vid, 64))),
            )
        )

    synthetic_pool = sorted(
        (v for v in raw_candidates if v.synthetic),
        key=lambda v: (-v.score, v.vertex_id),
    )
    reserved = synthetic_pool[: max(0, reserved_synthetic_slots)]
    reserved_ids = {v.vertex_id for v in reserved}
    regular_pool = sorted(
        (v for v in raw_candidates if v.vertex_id not in reserved_ids),
        key=lambda v: (-v.score, v.vertex_id),
    )

    retained: list[RetainedVertex] = []
    used_tokens = 0
    for vertex_cand in [*reserved, *regular_pool]:
        if len(retained) >= capped_vertices:
            pruned_count += 1
            continue
        if used_tokens + vertex_cand.token_cost > max_tokens:
            pruned_count += 1
            continue
        retained.append(vertex_cand)
        used_tokens += vertex_cand.token_cost

    retained_sorted = tuple(sorted(retained, key=lambda v: (-v.score, v.vertex_id)))
    retained_set = {v.vertex_id for v in retained_sorted}
    reserved_used = sum(1 for v in retained_sorted if v.synthetic)

    # Re-apply edge budget after vertex retention, preferring highest endpoint scores.
    score_by_id = {v.vertex_id: v.score for v in retained_sorted}
    valid_edges = [
        e for e in sub_edge_map.values() if e.src in retained_set and e.dst in retained_set
    ]
    valid_edges.sort(
        key=lambda e: (
            -round(score_by_id.get(e.src, 0.0) + score_by_id.get(e.dst, 0.0), 12),
            e.src,
            e.dst,
            e.edge_type,
        )
    )
    retained_edges = tuple(
        sorted(valid_edges[:max_edges], key=lambda e: (e.src, e.dst, e.edge_type))
    )

    digest_payload = {
        "vertices": [v.vertex_id for v in sorted(retained_sorted, key=lambda v: v.vertex_id)],
        "edges": [[e.src, e.dst, e.edge_type] for e in retained_edges],
    }
    graph_sha256 = sha256_text(canonicalize_jcs(digest_payload).decode("utf-8"))

    return GraphExpansionResult(
        vertices=retained_sorted,
        edges=retained_edges,
        ppr_iterations=iterations,
        converged=converged,
        effective_hops=eff_hops,
        graph_sha256=graph_sha256,
        pruned_count=pruned_count,
        reserved_synthetic_used=reserved_used,
    )


def align_crosswalk_terms(
    *,
    atoms: Collection[str],
    snapshot: RegistrySnapshot,
) -> OntologyAlignmentResult:
    """Reconcile equivalent/overlapping crosswalks while preserving conflicts (``DVSS-P06``)."""
    atom_set = {snapshot.resolve_pillar_alias(a)[0] for a in atoms}
    aligned_rels: dict[str, set[str]] = {}
    rel_kinds: dict[str, set[str]] = {}
    unresolved: list[UnresolvedAlignment] = []

    for cw in snapshot.crosswalks:
        if (
            cw.from_atom not in atom_set
            and cw.to_atom not in atom_set
            and cw.from_atom.split("#", 1)[0] not in atom_set
            and cw.to_atom.split("#", 1)[0] not in atom_set
        ):
            continue
        if cw.relation in {"equivalent", "overlaps", "is_analogous_to"}:
            canon = min(cw.from_atom, cw.to_atom)
            other = max(cw.from_atom, cw.to_atom)
            aligned_rels.setdefault(canon, {canon}).add(other)
            rel_kinds.setdefault(canon, set()).add(cw.relation)
        elif cw.relation in {"conflicts", "depends_on", "stricter_than", "requires"}:
            unresolved.append(
                UnresolvedAlignment(
                    from_atom=cw.from_atom,
                    to_atom=cw.to_atom,
                    relation=cw.relation,
                    reason=f"crosswalk_{cw.relation}_preserved",
                )
            )

    groups = tuple(
        AlignedTermGroup(
            canonical_atom=canon,
            related_atoms=tuple(sorted(aligned_rels[canon])),
            relations=tuple(sorted(rel_kinds[canon])),
        )
        for canon in sorted(aligned_rels)
    )
    sorted_unresolved = tuple(
        sorted(unresolved, key=lambda u: (u.relation, u.from_atom, u.to_atom))
    )
    return OntologyAlignmentResult(groups=groups, unresolved=sorted_unresolved)


__all__ = [
    "AlignedTermGroup",
    "GraphExpansionResult",
    "OntologyAlignmentResult",
    "RetainedEdge",
    "RetainedVertex",
    "UnresolvedAlignment",
    "align_crosswalk_terms",
    "effective_hop_budget",
    "expand_bounded_ppr",
]
