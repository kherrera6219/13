"""13-Axis registry loader, alias canonicalizer, and spine builder (``H3``).

Implements DLE-REG-001..005, DLE-SPC-003..005, and Phase 3 manifest integrity:
loads Axis 1-2 CSVs and Axis 3-7, 12-13 JSONL registries, rejects ``status='fixture'``
records outside test invocations, rewrites Axis 1 aliases, excludes retired records
from active indices while preserving replay lookup, and computes canonical JCS SHA-256 digests.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from dle.config.loader import canonicalize_jcs
from dle.errors import ConfigError, ContractValidationError
from dle.observability import sha256_text

_DEFAULT_SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "contracts" / "registry"

_JSONL_FILES: tuple[tuple[str, str, str, int], ...] = (
    ("axis3_links.jsonl", "axis3_link.schema.json", "link_id", 3),
    ("axis4_branches.jsonl", "axis4_branch.schema.json", "branch_id", 4),
    ("axis5_nodes.jsonl", "axis5_node.schema.json", "node_id", 5),
    ("axis6_hubs.jsonl", "axis6_hub.schema.json", "hub_id", 6),
    ("axis7_meshes.jsonl", "axis7_mesh.schema.json", "mesh_id", 7),
    ("axis12_jurisdictions.jsonl", "axis12_jurisdiction.schema.json", "jurisdiction_id", 12),
    ("axis13_intervals.jsonl", "axis13_interval.schema.json", "interval_id", 13),
)


@dataclass(frozen=True)
class PillarRecord:
    """Axis 1 top-level disciplinary pillar row (DLE-REG-001)."""

    pillar_id: str
    name: str
    coordinate: str
    canonical_str: str
    status: str
    canonical_id: str
    seed_members: tuple[str, ...]
    cip_codes: tuple[str, ...]


@dataclass(frozen=True)
class SectorRecord:
    """Axis 2 NAICS sector row (DLE-REG-002)."""

    sector_id: str
    name: str
    coordinate: str
    canonical_str: str
    status: str
    naics_2022: str
    seed_subsectors: tuple[str, ...]


@dataclass(frozen=True)
class NaicsCrosswalkRow:
    """Axis 2 historical/external classification crosswalk row."""

    sector_id: str
    scheme: str
    code_as_given: str
    resolution: str
    normalized_code: str
    naics_2022_successor: str


@dataclass(frozen=True)
class SpineEdge:
    """Directed edge in the bounded multi-axis retrieval spine."""

    src: str
    dst: str
    edge_type: str
    weight: float
    predicate: str | None = None
    cost: float = 1.0
    axis_id: int = 0


@dataclass(frozen=True)
class CrosswalkEntry:
    """Typed registry crosswalk row for ``registry.db`` persistence."""

    axis_id: int
    from_atom: str
    to_atom: str
    relation: str


@dataclass(frozen=True)
class RegistrySnapshot:
    """Immutable validated snapshot of active 13-axis registries and spine."""

    manifest_sha256: str
    pillars: Mapping[str, PillarRecord]
    pillars_by_id: Mapping[str, PillarRecord]
    pillar_aliases: Mapping[str, str]
    sectors: Mapping[str, SectorRecord]
    sectors_by_id: Mapping[str, SectorRecord]
    naics_crosswalk: tuple[NaicsCrosswalkRow, ...]
    links: Mapping[str, dict[str, object]]
    branches: Mapping[str, dict[str, object]]
    nodes: Mapping[str, dict[str, object]]
    hubs: Mapping[str, dict[str, object]]
    meshes: Mapping[str, dict[str, object]]
    jurisdictions: Mapping[str, dict[str, object]]
    intervals: Mapping[str, dict[str, object]]
    all_records_by_id: Mapping[str, dict[str, object]]
    retired_ids: frozenset[str]
    spine_edges: tuple[SpineEdge, ...]
    crosswalks: tuple[CrosswalkEntry, ...]

    def resolve_pillar_alias(self, token: str) -> tuple[str, bool]:
        """Rewrite Axis 1 alias IDs or coordinates to their canonical equivalent."""
        if token in self.pillar_aliases:
            return self.pillar_aliases[token], True
        return token, False

    def active_atoms(self) -> set[str]:
        """Return canonical strings of all non-retired records across axes 1-7, 12, 13."""
        active_pillars = {c for c, rec in self.pillars.items() if rec.status == "active"}
        active_sectors = {c for c, rec in self.sectors.items() if rec.status == "active"}
        return (
            active_pillars
            | active_sectors
            | set(self.links)
            | set(self.branches)
            | set(self.nodes)
            | set(self.hubs)
            | set(self.meshes)
            | set(self.jurisdictions)
            | set(self.intervals)
        )

    def is_known_atom(self, canonical_str: str, *, include_retired: bool = False) -> bool:
        """Check whether ``canonical_str`` resolves to a valid active (or replay) atom."""
        resolved, _ = self.resolve_pillar_alias(canonical_str)
        if resolved in self.active_atoms():
            return True
        return include_retired and resolved in self.retired_ids

    def to_db_rows(
        self,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        """Convert snapshot into SQLite rows for ``RegistryRepository.publish_release``."""
        atoms: list[dict[str, object]] = []
        for p in sorted(self.pillars.values(), key=lambda x: x.canonical_str):
            alias_target: str | None = None
            db_status = "active"
            if p.status == "alias":
                db_status = "alias"
                canon = self.pillars_by_id.get(p.canonical_id)
                alias_target = canon.canonical_str if canon is not None else p.canonical_id
            elif p.status == "retired":
                db_status = "retired"
            atoms.append(
                {
                    "axis_id": 1,
                    "canonical_str": p.canonical_str,
                    "meta_tag": "PL",
                    "label": p.name,
                    "status": db_status,
                    "alias_of": alias_target,
                }
            )
        for s in sorted(self.sectors.values(), key=lambda x: x.canonical_str):
            atoms.append(
                {
                    "axis_id": 2,
                    "canonical_str": s.canonical_str,
                    "meta_tag": "SECTOR",
                    "label": s.name,
                    "status": "active" if s.status == "active" else "retired",
                    "alias_of": None,
                }
            )

        axis_tables: tuple[tuple[int, str, str, Mapping[str, dict[str, object]]], ...] = (
            (3, "LINK", "scope", self.links),
            (4, "BR", "label", self.branches),
            (5, "NODE", "label", self.nodes),
            (6, "HUB", "concept", self.hubs),
            (7, "MESH", "label", self.meshes),
            (12, "JUR", "state", self.jurisdictions),
            (13, "TIME", "claim_scope", self.intervals),
        )
        for axis_id, tag, label_key, mapping in axis_tables:
            for rec_id in sorted(mapping):
                rec = mapping[rec_id]
                atoms.append(
                    {
                        "axis_id": axis_id,
                        "canonical_str": rec_id,
                        "meta_tag": tag,
                        "label": str(rec.get(label_key, rec_id)),
                        "status": "active",
                        "alias_of": None,
                    }
                )
        for rec_id in sorted(self.retired_ids):
            rec = self.all_records_by_id[rec_id]
            prefix = rec_id.split(":", 1)[0].lstrip("[")
            axis_num_str = rec_id.split(":", 1)[1].split(".", 1)[0]
            atoms.append(
                {
                    "axis_id": int(axis_num_str),
                    "canonical_str": rec_id,
                    "meta_tag": prefix,
                    "label": str(rec.get("label", rec.get("scope", rec_id))),
                    "status": "retired",
                    "alias_of": None,
                }
            )

        edges = [
            {
                "src": e.src,
                "dst": e.dst,
                "edge_type": e.edge_type,
                "weight": e.weight,
            }
            for e in self.spine_edges
        ]
        cws = [
            {
                "axis_id": c.axis_id,
                "from_atom": c.from_atom,
                "to_atom": c.to_atom,
                "relation": c.relation,
            }
            for c in self.crosswalks
        ]
        return atoms, edges, cws


def _compile_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    if not schema_path.is_file():
        raise ConfigError(f"missing registry schema: {schema_path}")
    loaded = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ContractValidationError(
            "registry schema root must be a JSON object",
            file_path=str(schema_path),
            pointer="/",
        )
    jsonschema.Draft202012Validator.check_schema(loaded)
    return jsonschema.Draft202012Validator(loaded, format_checker=jsonschema.FormatChecker())


def _split_semicolon(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(";") if part.strip())


def _read_pillars(path: Path) -> tuple[dict[str, PillarRecord], dict[str, PillarRecord]]:
    if not path.is_file():
        raise ConfigError(f"missing Axis 1 pillars CSV: {path}")
    by_canon: dict[str, PillarRecord] = {}
    by_id: dict[str, PillarRecord] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            coord = row["coordinate"].strip()
            canon = f"[PL:{coord}]"
            rec = PillarRecord(
                pillar_id=row["pillar_id"].strip(),
                name=row["name"].strip(),
                coordinate=coord,
                canonical_str=canon,
                status=row["status"].strip(),
                canonical_id=row["canonical_id"].strip(),
                seed_members=_split_semicolon(row.get("seed_members")),
                cip_codes=_split_semicolon(row.get("cip")),
            )
            by_canon[canon] = rec
            by_id[rec.pillar_id] = rec
    return by_canon, by_id


def _read_sectors(path: Path) -> tuple[dict[str, SectorRecord], dict[str, SectorRecord]]:
    if not path.is_file():
        raise ConfigError(f"missing Axis 2 sectors CSV: {path}")
    by_canon: dict[str, SectorRecord] = {}
    by_id: dict[str, SectorRecord] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            coord = row["coordinate"].strip()
            canon = f"[SECTOR:{coord}]"
            rec = SectorRecord(
                sector_id=row["sector_id"].strip(),
                name=row["name"].strip(),
                coordinate=coord,
                canonical_str=canon,
                status=row["status"].strip(),
                naics_2022=row["naics_2022"].strip(),
                seed_subsectors=_split_semicolon(row.get("seed_subsectors_naics_2022")),
            )
            by_canon[canon] = rec
            by_id[rec.sector_id] = rec
    return by_canon, by_id


def _read_naics_crosswalk(path: Path) -> tuple[NaicsCrosswalkRow, ...]:
    if not path.is_file():
        raise ConfigError(f"missing Axis 2 crosswalk CSV: {path}")
    rows: list[NaicsCrosswalkRow] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                NaicsCrosswalkRow(
                    sector_id=row["sector_id"].strip(),
                    scheme=row["scheme"].strip(),
                    code_as_given=row["code_as_given"].strip(),
                    resolution=row["resolution"].strip(),
                    normalized_code=row["normalized_code"].strip(),
                    naics_2022_successor=row["naics_2022_successor"].strip(),
                )
            )
    return tuple(rows)


def _read_jsonl_records(
    *,
    paths: list[Path],
    validator: jsonschema.Draft202012Validator,
    id_field: str,
    allow_fixtures: bool,
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]], set[str]]:
    active: dict[str, dict[str, object]] = {}
    all_recs: dict[str, dict[str, object]] = {}
    retired: set[str] = set()

    for path in paths:
        if not path.is_file():
            continue
        for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw_obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ContractValidationError(
                    f"invalid JSON on line {idx}: {exc.msg}",
                    file_path=str(path),
                    pointer="/",
                ) from exc
            if not isinstance(raw_obj, dict):
                raise ContractValidationError(
                    f"line {idx} must be a JSON object",
                    file_path=str(path),
                    pointer="/",
                )
            errors = sorted(validator.iter_errors(raw_obj), key=str)
            if errors:
                raise ContractValidationError(
                    f"{path.name}:{idx} schema error: {errors[0].message}",
                    file_path=str(path),
                    pointer="/" + "/".join(str(p) for p in errors[0].path),
                )
            rec = {str(k): v for k, v in raw_obj.items()}
            status = str(rec.get("status", ""))
            if status == "fixture" and not allow_fixtures:
                raise ContractValidationError(
                    "fixture registry records are rejected outside test runs",
                    file_path=str(path),
                    pointer="/status",
                )
            rec_id = rec.get(id_field)
            if not isinstance(rec_id, str) or not rec_id:
                raise ContractValidationError(
                    f"missing required identifier field {id_field!r}",
                    file_path=str(path),
                    pointer=f"/{id_field}",
                )
            if rec_id in all_recs:
                raise ContractValidationError(
                    f"duplicate registry record identifier {rec_id!r}",
                    file_path=str(path),
                    pointer=f"/{id_field}",
                )
            all_recs[rec_id] = rec
            if status == "retired":
                retired.add(rec_id)
            else:
                active[rec_id] = rec

    return active, all_recs, retired


def load_registry(
    registry_dir: Path,
    *,
    overlay_dir: Path | None = None,
    schemas_dir: Path | None = None,
    allow_fixtures: bool = False,
    w3: float = 1.0,
    w67: float = 1.0,
) -> RegistrySnapshot:
    """Load and schema-validate the 13-axis registries and compute spine/manifest digest."""
    if w3 <= 0.0 or w67 <= 0.0:
        raise ValueError("distance_weights w3 and w67 must be strictly positive (DLE-SPC-003 §5)")

    eff_schemas = schemas_dir if schemas_dir is not None else _DEFAULT_SCHEMAS_DIR
    pillars, pillars_by_id = _read_pillars(registry_dir / "axis1_pillars.csv")
    sectors, sectors_by_id = _read_sectors(registry_dir / "axis2_sectors.csv")
    naics_crosswalk = _read_naics_crosswalk(registry_dir / "axis2_crosswalk.csv")

    pillar_aliases: dict[str, str] = {}
    for p in pillars.values():
        if p.status == "alias":
            target = pillars_by_id.get(p.canonical_id)
            if target is None:
                raise ConfigError(
                    f"Axis 1 alias {p.pillar_id} points to unknown target {p.canonical_id}"
                )
            pillar_aliases[p.pillar_id] = target.pillar_id
            pillar_aliases[p.canonical_str] = target.canonical_str

    buckets: dict[int, dict[str, dict[str, object]]] = {}
    all_records_by_id: dict[str, dict[str, object]] = {}
    retired_ids: set[str] = set()

    for filename, schema_name, id_field, axis_id in _JSONL_FILES:
        validator = _compile_validator(eff_schemas / schema_name)
        candidate_paths = [registry_dir / filename]
        if overlay_dir is not None:
            candidate_paths.append(overlay_dir / filename)
        active_recs, all_recs, retired = _read_jsonl_records(
            paths=candidate_paths,
            validator=validator,
            id_field=id_field,
            allow_fixtures=allow_fixtures,
        )
        buckets[axis_id] = active_recs
        all_records_by_id.update(all_recs)
        retired_ids.update(retired)

    edges_set: dict[tuple[str, str, str], SpineEdge] = {}
    crosswalks_list: list[CrosswalkEntry] = []

    def _add_edge(edge: SpineEdge) -> None:
        key = (edge.src, edge.dst, edge.edge_type)
        edges_set[key] = edge

    # Axis 4 branch hierarchy -> pillar/sector root and parent branch.
    for branch_id, br in buckets[4].items():
        root_code = str(br["root"])
        if root_code in pillars_by_id:
            canon_root = pillars_by_id[root_code].canonical_str
            resolved_root = pillar_aliases.get(canon_root, canon_root)
            _add_edge(SpineEdge(resolved_root, branch_id, "tree_branch", 1.0, axis_id=4))
        elif root_code in sectors_by_id:
            _add_edge(
                SpineEdge(
                    sectors_by_id[root_code].canonical_str,
                    branch_id,
                    "tree_branch",
                    1.0,
                    axis_id=4,
                )
            )
        parent = br.get("parent")
        if isinstance(parent, str) and parent:
            _add_edge(SpineEdge(parent, branch_id, "tree_branch", 1.0, axis_id=4))

    # Axis 5 nodes -> anchors and intersection via_links.
    for node_id, node in buckets[5].items():
        anchors = node.get("anchors")
        if isinstance(anchors, list):
            for raw_anchor in anchors:
                anc = pillar_aliases.get(str(raw_anchor), str(raw_anchor))
                _add_edge(SpineEdge(anc, node_id, "node_anchor", 1.0, axis_id=5))
        via_links = node.get("via_links")
        if isinstance(via_links, list):
            for raw_link in via_links:
                _add_edge(SpineEdge(str(raw_link), node_id, "node_via_link", w3, axis_id=5))

    # Axis 3 links -> lateral bidirectional edges + crosswalk.
    for link_id, link in buckets[3].items():
        subj = pillar_aliases.get(str(link["subject"]), str(link["subject"]))
        obj = pillar_aliases.get(str(link["object"]), str(link["object"]))
        pred = str(link["predicate"])
        cost = float(str(link["cost"]))
        weight = round(w3 * cost, 6)
        _add_edge(
            SpineEdge(subj, obj, "honeycomb_link", weight, predicate=pred, cost=cost, axis_id=3)
        )
        _add_edge(
            SpineEdge(obj, subj, "honeycomb_link", weight, predicate=pred, cost=cost, axis_id=3)
        )
        _add_edge(
            SpineEdge(link_id, subj, "link_endpoint", weight, predicate=pred, cost=cost, axis_id=3)
        )
        _add_edge(
            SpineEdge(link_id, obj, "link_endpoint", weight, predicate=pred, cost=cost, axis_id=3)
        )
        crosswalks_list.append(
            CrosswalkEntry(axis_id=3, from_atom=subj, to_atom=obj, relation=pred)
        )

    # Axis 6 hubs -> anchors & arm edges.
    for hub_id, hub in buckets[6].items():
        anchors = hub.get("anchors")
        if isinstance(anchors, list):
            for raw_anchor in anchors:
                anc = pillar_aliases.get(str(raw_anchor), str(raw_anchor))
                _add_edge(SpineEdge(anc, hub_id, "hub_anchor", w67, cost=w67, axis_id=6))
        arms = hub.get("arms")
        if isinstance(arms, list):
            for arm in arms:
                if not isinstance(arm, Mapping):
                    continue
                arm_id = f"{hub_id}#{arm['arm_id']}"
                rel = str(arm["relation"])
                _add_edge(
                    SpineEdge(hub_id, arm_id, "hub_arm", w67, predicate=rel, cost=w67, axis_id=6)
                )
                crosswalks_list.append(
                    CrosswalkEntry(axis_id=6, from_atom=hub_id, to_atom=arm_id, relation=rel)
                )

    # Axis 7 meshes -> hub requirements & mesh relations.
    for mesh_id, mesh in buckets[7].items():
        reqs = mesh.get("requirements")
        if isinstance(reqs, list):
            for req in reqs:
                req_str = str(req)
                _add_edge(SpineEdge(mesh_id, req_str, "mesh_requirement", w67, cost=w67, axis_id=7))
                if "#" in req_str and req_str.startswith("[HUB:"):
                    parent_hub = req_str.split("#", 1)[0]
                    _add_edge(
                        SpineEdge(parent_hub, mesh_id, "hub_to_mesh", w67, cost=w67, axis_id=7)
                    )
        rels = mesh.get("relations")
        if isinstance(rels, list):
            for rel in rels:
                if not isinstance(rel, Mapping):
                    continue
                crosswalks_list.append(
                    CrosswalkEntry(
                        axis_id=7,
                        from_atom=str(rel["a"]),
                        to_atom=str(rel["b"]),
                        relation=str(rel["type"]),
                    )
                )

    sorted_edges = tuple(
        sorted(edges_set.values(), key=lambda e: (e.src, e.dst, e.edge_type, e.axis_id))
    )
    sorted_crosswalks = tuple(
        sorted(
            set(crosswalks_list),
            key=lambda c: (c.axis_id, c.from_atom, c.to_atom, c.relation),
        )
    )

    manifest_payload = {
        "pillars": sorted(pillars),
        "sectors": sorted(sectors),
        "links": {k: buckets[3][k] for k in sorted(buckets[3])},
        "branches": {k: buckets[4][k] for k in sorted(buckets[4])},
        "nodes": {k: buckets[5][k] for k in sorted(buckets[5])},
        "hubs": {k: buckets[6][k] for k in sorted(buckets[6])},
        "meshes": {k: buckets[7][k] for k in sorted(buckets[7])},
        "jurisdictions": {k: buckets[12][k] for k in sorted(buckets[12])},
        "intervals": {k: buckets[13][k] for k in sorted(buckets[13])},
    }
    manifest_sha256 = sha256_text(canonicalize_jcs(manifest_payload).decode("utf-8"))

    return RegistrySnapshot(
        manifest_sha256=manifest_sha256,
        pillars=pillars,
        pillars_by_id=pillars_by_id,
        pillar_aliases=pillar_aliases,
        sectors=sectors,
        sectors_by_id=sectors_by_id,
        naics_crosswalk=naics_crosswalk,
        links=buckets[3],
        branches=buckets[4],
        nodes=buckets[5],
        hubs=buckets[6],
        meshes=buckets[7],
        jurisdictions=buckets[12],
        intervals=buckets[13],
        all_records_by_id=all_records_by_id,
        retired_ids=frozenset(retired_ids),
        spine_edges=sorted_edges,
        crosswalks=sorted_crosswalks,
    )


__all__ = [
    "CrosswalkEntry",
    "NaicsCrosswalkRow",
    "PillarRecord",
    "RegistrySnapshot",
    "SectorRecord",
    "SpineEdge",
    "load_registry",
]
