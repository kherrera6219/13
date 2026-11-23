"""13-Axis coordinate parser, temporal filter, and jurisdiction precedence engine (``H4``).

Implements DLE-SPC-003 (A1/A3/A6), DLE-SPC-004 (§6), DLE-SPC-005 (T1-T8),
``DVSS-K02`` (coordinate parsing), ``DVSS-K06`` (temporal interval filtering),
and ``DVSS-P01`` (jurisdiction precedence).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import jsonschema

from dle.errors import ContractValidationError
from dle.host.services.registry import RegistrySnapshot
from dle.temporal import Interval, LegacyFormatError, contains, interval_of, overlaps, project

_DEFAULT_COORDINATE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "contracts" / "coordinate.schema.json"
)

_ATOM_RE = re.compile(r"^\[([A-Z][A-Z0-9-]*):(1[0-3]|[1-9])((?:\.(?:0|[1-9][0-9]*))+)\]$")
_TMP_RE = re.compile(
    r"^\[TMP:5\.TMP\.([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]$"
)
_WORD_RE = re.compile(r"[a-z0-9]+")

AXIS_FIELD_MAP: dict[int, str] = {
    1: "axis_1_pillars",
    2: "axis_2_sectors",
    3: "axis_3_honeycomb",
    4: "axis_4_branches",
    5: "axis_5_nodes",
    6: "axis_6_octopus",
    7: "axis_7_spiderweb",
    8: "axis_8_scholar",
    9: "axis_9_practitioner",
    10: "axis_10_regulator",
    11: "axis_11_compliance",
    12: "axis_12_jurisdiction",
}

SLOT_STATE_KEYS: tuple[str, ...] = (
    "axis_2_sectors",
    "axis_3_honeycomb",
    "axis_4_branches",
    "axis_5_nodes",
    "axis_6_octopus",
    "axis_7_spiderweb",
    "axis_8_scholar",
    "axis_9_practitioner",
    "axis_10_regulator",
    "axis_11_compliance",
)

NEXUS_PRECEDENCE: dict[str, int] = {
    "federal_agency": 1,
    "state_agency": 2,
    "local_government": 3,
    "tribal_government": 4,
    "contract": 5,
    "buyer": 6,
    "site_owner": 7,
    "foreign_authority": 8,
    "unscoped": 9,
}

_FALLBACK_PILLAR = "[PL:1.1.0.0]"


@dataclass(frozen=True)
class UncertainMatch:
    """Anchor string that failed parsing, registry resolution, or A1 pillar constraint."""

    raw_atom: str
    reason: str


@dataclass(frozen=True)
class DependencyItem:
    """Explicit open dependency emitted when a required binding slot or interval is unknown."""

    axis_id: int
    slot: str
    reason: str
    subject: str | None = None


@dataclass(frozen=True)
class CoordinateParseResult:
    """Output of ``DVSS-K02`` coordinate parsing & registry validation."""

    coordinate: dict[str, object]
    uncertain_matches: tuple[UncertainMatch, ...]
    alias_rewrites: tuple[tuple[str, str], ...]
    active_axes: tuple[int, ...]
    activated_roles: tuple[str, ...]
    open_dependencies: tuple[DependencyItem, ...]
    used_fallback_pillar: bool


@dataclass(frozen=True)
class TemporalConflict:
    """Conflicting overlapping intervals for the same ``(subject, kind)`` pair."""

    subject: str
    kind: str
    interval_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ExcludedTemporalRecord:
    """Temporal record excluded from active scope with an explicit reason."""

    interval_id: str | None
    subject: str
    scope: str
    reason: str


@dataclass(frozen=True)
class TemporalFilterResult:
    """Output of ``DVSS-K06`` half-open interval applicability evaluation."""

    applicable: tuple[dict[str, object], ...]
    excluded: tuple[ExcludedTemporalRecord, ...]
    conflicts: tuple[TemporalConflict, ...]
    has_unknown_dependency: bool


@dataclass(frozen=True)
class PrecedenceArm:
    """Applicable hub arm ordered by Axis 12 jurisdiction precedence (``DVSS-P01``)."""

    arm_id: str
    authority: str
    nexus_kind: str
    rank: int
    relation: str
    citation: str
    jurisdiction: str


@dataclass(frozen=True)
class JurisdictionReviewItem:
    """Review item raised on conflicting applicable authorities or unknown jurisdiction."""

    reason: str
    arm_ids: tuple[str, ...]


@dataclass(frozen=True)
class JurisdictionResolutionResult:
    """Output of ``DVSS-P01`` jurisdiction hierarchy ordering."""

    jurisdiction_state: Literal["specified", "unknown", "unscoped"]
    ordered_arms: tuple[PrecedenceArm, ...]
    excluded_arms: tuple[tuple[str, str], ...]
    review_items: tuple[JurisdictionReviewItem, ...]


def parse_atom(raw: str) -> dict[str, object]:
    """Parse canonical Nuremberg or Axis-5 session ``TMP`` coordinate atom."""
    cleaned = raw.strip()
    m_tmp = _TMP_RE.match(cleaned)
    if m_tmp is not None:
        node_uuid = m_tmp.group(1)
        return {
            "axis_id": 5,
            "meta_tag": "TMP",
            "session_uuid": node_uuid,
            "node_uuid": node_uuid,
            "status": "synthetic_derived",
            "canonical_str": cleaned,
        }

    m = _ATOM_RE.match(cleaned)
    if m is None:
        raise ValueError(f"invalid canonical atom syntax: {raw!r}")
    tag = m.group(1)
    if tag == "TMP":
        raise ValueError(f"TMP atom must match [TMP:5.TMP.<uuid>]: {raw!r}")
    axis_id = int(m.group(2))
    path = [int(part) for part in m.group(3).lstrip(".").split(".")]
    if axis_id == 1 and len(path) >= 2 and any(part != 0 for part in path[1:]):
        raise ValueError(f"Axis 1 pillar cannot have non-zero sub-member (DLE-SPC-003 A1): {raw!r}")

    return {
        "axis_id": axis_id,
        "meta_tag": tag,
        "nuremberg_path": path,
        "canonical_str": cleaned,
    }


def _tokens(val: str) -> set[str]:
    return {tok for tok in _WORD_RE.findall(val.lower()) if len(tok) >= 3}


def propose_anchors_from_query(query_str: str, snapshot: RegistrySnapshot) -> list[str]:
    """Propose deterministic initial anchor atoms from query keywords against ``snapshot``."""
    q_tokens = _tokens(query_str)
    proposals: list[str] = []

    if q_tokens:
        pillar_scores: list[tuple[int, str]] = []
        for canon, pil in snapshot.pillars.items():
            if pil.status != "active":
                continue
            p_tokens = _tokens(pil.name) | _tokens(" ".join(pil.seed_members))
            overlap = len(q_tokens & p_tokens)
            if overlap > 0:
                pillar_scores.append((-overlap, canon))
        pillar_scores.sort()
        proposals.extend(canon for _, canon in pillar_scores[:3])

        sector_scores: list[tuple[int, str]] = []
        for canon, sec in snapshot.sectors.items():
            if sec.status != "active":
                continue
            s_tokens = _tokens(sec.name) | _tokens(" ".join(sec.seed_subsectors))
            overlap = len(q_tokens & s_tokens)
            if overlap > 0:
                sector_scores.append((-overlap, canon))
        sector_scores.sort()
        proposals.extend(canon for _, canon in sector_scores[:2])

        for br_id, br in sorted(snapshot.branches.items()):
            if q_tokens & _tokens(str(br.get("label", ""))):
                proposals.append(br_id)
        for node_id, node in sorted(snapshot.nodes.items()):
            if q_tokens & _tokens(str(node.get("label", ""))):
                proposals.append(node_id)
        for link_id, link in sorted(snapshot.links.items()):
            if q_tokens & _tokens(str(link.get("scope", ""))):
                proposals.append(link_id)
        for hub_id, hub in sorted(snapshot.hubs.items()):
            h_tok = _tokens(str(hub.get("concept", ""))) | _tokens(str(hub.get("definition", "")))
            if q_tokens & h_tok:
                proposals.append(hub_id)
        for mesh_id, mesh in sorted(snapshot.meshes.items()):
            if q_tokens & _tokens(str(mesh.get("label", ""))):
                proposals.append(mesh_id)
        for jur_id, jur in sorted(snapshot.jurisdictions.items()):
            place = jur.get("place")
            j_tok: set[str] = set()
            if isinstance(place, Mapping):
                for val in place.values():
                    j_tok |= _tokens(str(val))
            if q_tokens & j_tok:
                proposals.append(jur_id)

    has_pillar = any(a.startswith("[PL:") for a in proposals)
    if not has_pillar and _FALLBACK_PILLAR in snapshot.pillars:
        proposals.insert(0, _FALLBACK_PILLAR)
    return proposals


def _compile_coord_validator(schema_path: Path | None) -> jsonschema.Draft202012Validator:
    target = schema_path if schema_path is not None else _DEFAULT_COORDINATE_SCHEMA_PATH
    loaded = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ContractValidationError(
            "coordinate schema root must be a JSON object",
            file_path=str(target),
            pointer="/",
        )
    return jsonschema.Draft202012Validator(loaded, format_checker=jsonschema.FormatChecker())


def parse_coordinate(
    *,
    proposed_anchors: Sequence[str],
    snapshot: RegistrySnapshot,
    as_of: date,
    temporal_records: Sequence[Mapping[str, object]] = (),
    binding_claim: bool = False,
    session_uuid: str | None = None,
    allow_widen_instants: bool = False,
    explicit_slot_states: Mapping[str, str] | None = None,
    explicit_jurisdiction_state: Literal["specified", "unknown", "unscoped"] | None = None,
    schema_path: Path | None = None,
) -> CoordinateParseResult:
    """Parse proposed anchors, rewrite aliases, resolve Axes 12-13, and validate coordinate."""
    buckets: dict[str, list[dict[str, object]]] = {field: [] for field in AXIS_FIELD_MAP.values()}
    seen_canon: set[str] = set()
    uncertain: list[UncertainMatch] = []
    alias_rewrites: list[tuple[str, str]] = []
    dependencies: list[DependencyItem] = []

    for raw in proposed_anchors:
        resolved, was_alias = snapshot.resolve_pillar_alias(raw.strip())
        if was_alias:
            alias_rewrites.append((raw.strip(), resolved))

        try:
            atom = parse_atom(resolved)
        except ValueError as exc:
            uncertain.append(UncertainMatch(raw_atom=raw, reason=str(exc)))
            continue

        axis_id = int(str(atom["axis_id"]))
        canon = str(atom["canonical_str"])
        if canon in seen_canon:
            continue

        if atom.get("meta_tag") == "TMP":
            if session_uuid is not None:
                atom["session_uuid"] = session_uuid
            buckets["axis_5_nodes"].append(atom)
            seen_canon.add(canon)
            continue

        if axis_id in {8, 9, 10, 11}:
            field = AXIS_FIELD_MAP[axis_id]
            buckets[field].append(atom)
            seen_canon.add(canon)
            continue

        if not snapshot.is_known_atom(canon, include_retired=False):
            reason = (
                "retired_atom_excluded" if canon in snapshot.retired_ids else "unregistered_atom"
            )
            uncertain.append(UncertainMatch(raw_atom=raw, reason=reason))
            continue

        field = AXIS_FIELD_MAP[axis_id]
        buckets[field].append(atom)
        seen_canon.add(canon)

    used_fallback_pillar = False
    if not buckets["axis_1_pillars"]:
        used_fallback_pillar = True
        uncertain.append(
            UncertainMatch(raw_atom="", reason="missing_axis_1_pillar_used_general_fallback")
        )
        fallback_atom = parse_atom(_FALLBACK_PILLAR)
        buckets["axis_1_pillars"].append(fallback_atom)

    # Axis 12 jurisdiction resolution
    jur_list = buckets["axis_12_jurisdiction"]
    if jur_list:
        jurisdiction_state: Literal["specified", "unknown", "unscoped"] = "specified"
    elif explicit_jurisdiction_state in ("unknown", "unscoped"):
        jurisdiction_state = explicit_jurisdiction_state
        if jurisdiction_state == "unknown" and binding_claim:
            dependencies.append(
                DependencyItem(
                    axis_id=12,
                    slot="axis_12_jurisdiction",
                    reason="unknown_jurisdiction_on_binding_claim",
                )
            )
    elif binding_claim:
        jurisdiction_state = "unknown"
        dependencies.append(
            DependencyItem(
                axis_id=12,
                slot="axis_12_jurisdiction",
                reason="missing_jurisdiction_on_binding_claim",
            )
        )
    else:
        jurisdiction_state = "unscoped"

    # Axis 13 temporal projection via dle.temporal.project
    projected_temporal: list[dict[str, object]] = []
    seen_temporal_keys: set[tuple[str, str, str | None, str]] = set()
    for rec in temporal_records:
        subj = str(rec.get("subject", ""))
        if rec.get("determination") == "unknown":
            dependencies.append(
                DependencyItem(
                    axis_id=13,
                    slot="axis_13_temporal",
                    reason="unknown_valid_time",
                    subject=subj or None,
                )
            )
            continue
        try:
            proj = project(rec, as_of, allow_widen=allow_widen_instants)
        except LegacyFormatError as exc:
            uncertain.append(UncertainMatch(raw_atom=subj or "axis13", reason=str(exc)))
            continue
        t_key = (
            str(proj["claim_scope"]),
            str(proj["effective_start"]),
            str(proj["effective_end"]) if proj["effective_end"] is not None else None,
            str(proj["as_of"]),
        )
        if t_key not in seen_temporal_keys:
            projected_temporal.append(proj)
            seen_temporal_keys.add(t_key)

    if not projected_temporal:
        projected_temporal.append(
            {
                "claim_scope": "query_as_of",
                "effective_start": as_of.isoformat(),
                "effective_end": None,
                "as_of": as_of.isoformat(),
            }
        )

    # Mandatory slot states for Axes 2..11
    slot_states: dict[str, str] = {}
    for key in SLOT_STATE_KEYS:
        if buckets[key]:
            slot_states[key] = "specified"
        elif explicit_slot_states and key in explicit_slot_states:
            chosen = explicit_slot_states[key]
            slot_states[key] = chosen
            if chosen == "unknown" and binding_claim:
                axis_num = int(key.split("_")[1])
                dependencies.append(
                    DependencyItem(
                        axis_id=axis_num,
                        slot=key,
                        reason=f"unknown_slot_{key}",
                    )
                )
        elif key == "axis_10_regulator" and binding_claim:
            slot_states[key] = "unknown"
            dependencies.append(
                DependencyItem(
                    axis_id=10,
                    slot=key,
                    reason="binding_claim_missing_regulator_atom",
                )
            )
        elif key == "axis_11_compliance" and buckets["axis_7_spiderweb"]:
            slot_states[key] = "unknown"
            dependencies.append(
                DependencyItem(
                    axis_id=11,
                    slot=key,
                    reason="active_axis7_missing_harmonizer_atom",
                )
            )
        else:
            slot_states[key] = "empty"

    # Rule-based activation (DLE-SPC-003 A6 & DLE-SPC-004 §2)
    roles: list[str] = ["scholar"]
    if buckets["axis_2_sectors"]:
        roles.append("practitioner")
    if binding_claim or buckets["axis_10_regulator"]:
        roles.append("regulator")
    if buckets["axis_7_spiderweb"] or buckets["axis_11_compliance"]:
        roles.append("harmonizer")

    active_axes: list[int] = [1]
    for ax_id in range(2, 13):
        if buckets[AXIS_FIELD_MAP[ax_id]]:
            active_axes.append(ax_id)
    active_axes.append(13)

    coordinate_doc: dict[str, object] = {
        **buckets,
        "axis_13_temporal": projected_temporal,
        "schema_version": "3.7.1",
        "registry_manifest_sha256": snapshot.manifest_sha256,
        "jurisdiction_state": jurisdiction_state,
        "slot_states": slot_states,
    }

    validator = _compile_coord_validator(schema_path)
    errors = sorted(validator.iter_errors(coordinate_doc), key=str)
    if errors:
        raise ContractValidationError(
            f"generated coordinate violated 3.7.1 schema: {errors[0].message}",
            file_path="coordinate",
            pointer="/" + "/".join(str(p) for p in errors[0].path),
        )

    return CoordinateParseResult(
        coordinate=coordinate_doc,
        uncertain_matches=tuple(uncertain),
        alias_rewrites=tuple(alias_rewrites),
        active_axes=tuple(active_axes),
        activated_roles=tuple(roles),
        open_dependencies=tuple(dependencies),
        used_fallback_pillar=used_fallback_pillar,
    )


def _date_interval_from_record(rec: Mapping[str, object], as_of: date) -> Interval | None:
    if rec.get("determination") == "unknown":
        return None
    proj = project(rec, as_of, allow_widen=True)
    start_d = date.fromisoformat(str(proj["effective_start"]))
    raw_end = proj.get("effective_end")
    end_d = date.fromisoformat(str(raw_end)) if raw_end is not None else None
    return Interval(start_d, end_d, "date")


def evaluate_temporal_applicability(
    intervals: Sequence[Mapping[str, object]],
    *,
    as_of: date,
    query_scopes: Sequence[tuple[str, date, date | None]] = (),
) -> TemporalFilterResult:
    """Evaluate Axis 13 half-open interval applicability & detect overlapping version errors."""
    excluded: list[ExcludedTemporalRecord] = []
    applicable: list[dict[str, object]] = []
    has_unknown_dep = False

    parsed_by_subject_kind: dict[
        tuple[str, str], list[tuple[str, Interval, Mapping[str, object]]]
    ] = {}

    for rec in intervals:
        rec_id = str(rec.get("interval_id", "")) or None
        subject = str(rec.get("subject", ""))
        scope_label = str(rec.get("claim_scope", ""))
        kind = str(rec.get("kind", "effective"))
        status = str(rec.get("status", "verified"))
        if status == "retired":
            excluded.append(
                ExcludedTemporalRecord(
                    interval_id=rec_id,
                    subject=subject,
                    scope=scope_label,
                    reason="retired_interval",
                )
            )
            continue

        iv = interval_of(rec)
        if iv is None:
            has_unknown_dep = True
            excluded.append(
                ExcludedTemporalRecord(
                    interval_id=rec_id,
                    subject=subject,
                    scope=scope_label,
                    reason="unknown_valid_time",
                )
            )
            continue

        date_iv = _date_interval_from_record(rec, as_of)
        if date_iv is None:
            continue
        parsed_by_subject_kind.setdefault((subject, kind), []).append(
            (rec_id or subject, date_iv, rec)
        )

    # Detect overlapping versions within the same (subject, kind) (DLE-SPC-005 §4.4)
    conflicts: list[TemporalConflict] = []
    conflicted_keys: set[tuple[str, str]] = set()
    for (subject, kind), entries in sorted(parsed_by_subject_kind.items()):
        if len(entries) < 2:
            continue
        overlapping_ids: set[str] = set()
        for i in range(len(entries)):
            id_a, iv_a, _ = entries[i]
            for j in range(i + 1, len(entries)):
                id_b, iv_b, _ = entries[j]
                if overlaps(iv_a, iv_b):
                    overlapping_ids.add(id_a)
                    overlapping_ids.add(id_b)
        if overlapping_ids:
            conflicted_keys.add((subject, kind))
            conflicts.append(
                TemporalConflict(
                    subject=subject,
                    kind=kind,
                    interval_ids=tuple(sorted(overlapping_ids)),
                    reason="overlapping_versions_for_subject",
                )
            )

    for (subject, kind), entries in sorted(parsed_by_subject_kind.items()):
        if (subject, kind) in conflicted_keys:
            for rec_id, _iv, rec in entries:
                excluded.append(
                    ExcludedTemporalRecord(
                        interval_id=rec_id,
                        subject=subject,
                        scope=str(rec.get("claim_scope", "")),
                        reason="overlapping_version_conflict",
                    )
                )
            continue

        for rec_id, date_iv, rec in entries:
            if query_scopes:
                matched_scopes = [
                    sname
                    for sname, s_start, s_end in query_scopes
                    if overlaps(date_iv, Interval(s_start, s_end, "date"))
                ]
                in_scope = bool(matched_scopes)
            else:
                in_scope = contains(date_iv, as_of)
                matched_scopes = [as_of.isoformat()] if in_scope else []

            if in_scope:
                applicable.append(
                    {
                        "interval_id": rec_id,
                        "subject": subject,
                        "kind": kind,
                        "claim_scope": str(rec.get("claim_scope", "")),
                        "start": date_iv.start.isoformat(),
                        "end": date_iv.end.isoformat() if date_iv.end is not None else None,
                        "matched_scopes": matched_scopes,
                    }
                )
            else:
                excluded.append(
                    ExcludedTemporalRecord(
                        interval_id=rec_id,
                        subject=subject,
                        scope=str(rec.get("claim_scope", "")),
                        reason="outside_as_of_window",
                    )
                )

    return TemporalFilterResult(
        applicable=tuple(applicable),
        excluded=tuple(excluded),
        conflicts=tuple(conflicts),
        has_unknown_dependency=has_unknown_dep,
    )


def _arm_matches_jurisdiction(
    arm_jur: str | None,
    jurisdiction_record: Mapping[str, object] | None,
) -> bool:
    if arm_jur is None or arm_jur == "unscoped":
        return True
    if jurisdiction_record is None:
        return False
    if str(jurisdiction_record.get("jurisdiction_id", "")) == arm_jur:
        return True
    place = jurisdiction_record.get("place")
    if not isinstance(place, Mapping):
        return False
    iso1 = str(place.get("iso_3166_1", ""))
    iso2 = str(place.get("iso_3166_2", ""))
    return arm_jur in {iso1, iso2}


def _infer_nexus_kind(
    arm: Mapping[str, object],
    jurisdiction_record: Mapping[str, object] | None,
) -> str:
    arm_jur = str(arm.get("jurisdiction", "unscoped"))
    if arm_jur == "unscoped":
        return "unscoped"
    authority = str(arm.get("authority", "")).strip().lower()
    if jurisdiction_record is not None:
        nexuses = jurisdiction_record.get("legal_nexus")
        if isinstance(nexuses, list):
            for nx in nexuses:
                if not isinstance(nx, Mapping):
                    continue
                if str(nx.get("name", "")).strip().lower() == authority:
                    return str(nx.get("kind", "buyer"))
            first = nexuses[0] if nexuses else None
            if isinstance(first, Mapping):
                return str(first.get("kind", "buyer"))
    return "buyer"


def resolve_jurisdiction_precedence(
    *,
    jurisdiction_record: Mapping[str, object] | None,
    hub_arms: Sequence[Mapping[str, object]],
    as_of: date,
    intervals_by_subject: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
    hub_id: str = "[HUB:6.0]",
    binding_claim: bool = False,
) -> JurisdictionResolutionResult:
    """Order applicable Axis 6 hub arms by Axis 12 precedence and Axis 13 temporal scope."""
    raw_state = (
        str(jurisdiction_record.get("state", "unscoped"))
        if jurisdiction_record is not None
        else "unscoped"
    )
    jur_state: Literal["specified", "unknown", "unscoped"]
    if raw_state == "specified":
        jur_state = "specified"
    elif raw_state == "unknown":
        jur_state = "unknown"
    else:
        jur_state = "unscoped"

    review_items: list[JurisdictionReviewItem] = []
    if jur_state == "unknown" and binding_claim:
        review_items.append(
            JurisdictionReviewItem(reason="unknown_jurisdiction_on_binding_claim", arm_ids=())
        )

    applicable: list[PrecedenceArm] = []
    excluded: list[tuple[str, str]] = []

    for arm in hub_arms:
        arm_id = str(arm.get("arm_id", ""))
        arm_jur = (
            str(arm.get("jurisdiction")) if arm.get("jurisdiction") is not None else "unscoped"
        )
        if not _arm_matches_jurisdiction(arm_jur, jurisdiction_record):
            excluded.append((arm_id, f"jurisdiction_mismatch:{arm_jur}"))
            continue

        arm_subj = f"{hub_id}#{arm_id}"
        if intervals_by_subject and arm_subj in intervals_by_subject:
            t_res = evaluate_temporal_applicability(intervals_by_subject[arm_subj], as_of=as_of)
            if not t_res.applicable:
                excluded.append((arm_id, "outside_axis13_interval"))
                continue
        elif arm.get("valid_from") is not None:
            v_start = date.fromisoformat(str(arm["valid_from"]))
            raw_v_end = arm.get("valid_to")
            v_end = date.fromisoformat(str(raw_v_end)) if raw_v_end is not None else None
            if not contains(Interval(v_start, v_end, "date"), as_of):
                excluded.append((arm_id, "outside_arm_valid_window"))
                continue

        explicit_kind = arm.get("nexus_kind")
        nexus_kind = (
            str(explicit_kind)
            if isinstance(explicit_kind, str) and explicit_kind in NEXUS_PRECEDENCE
            else _infer_nexus_kind(arm, jurisdiction_record)
        )
        rank = NEXUS_PRECEDENCE.get(nexus_kind, 9)
        applicable.append(
            PrecedenceArm(
                arm_id=arm_id,
                authority=str(arm.get("authority", "")),
                nexus_kind=nexus_kind,
                rank=rank,
                relation=str(arm.get("relation", "")),
                citation=str(arm.get("citation", "")),
                jurisdiction=arm_jur,
            )
        )

    ordered = tuple(sorted(applicable, key=lambda a: (a.rank, a.citation, a.arm_id)))

    if binding_claim and len(ordered) >= 2:
        by_rank: dict[int, list[PrecedenceArm]] = {}
        for item in ordered:
            by_rank.setdefault(item.rank, []).append(item)
        for _rank, group in sorted(by_rank.items()):
            relations = {item.relation for item in group}
            if "prohibits" in relations and (relations & {"permits", "exempts", "requires"}):
                review_items.append(
                    JurisdictionReviewItem(
                        reason="equal_precedence_authority_conflict",
                        arm_ids=tuple(item.arm_id for item in group),
                    )
                )

    return JurisdictionResolutionResult(
        jurisdiction_state=jur_state,
        ordered_arms=ordered,
        excluded_arms=tuple(excluded),
        review_items=tuple(review_items),
    )


__all__ = [
    "AXIS_FIELD_MAP",
    "NEXUS_PRECEDENCE",
    "SLOT_STATE_KEYS",
    "CoordinateParseResult",
    "DependencyItem",
    "ExcludedTemporalRecord",
    "JurisdictionResolutionResult",
    "JurisdictionReviewItem",
    "PrecedenceArm",
    "TemporalConflict",
    "TemporalFilterResult",
    "UncertainMatch",
    "evaluate_temporal_applicability",
    "parse_atom",
    "parse_coordinate",
    "propose_anchors_from_query",
    "resolve_jurisdiction_precedence",
]
