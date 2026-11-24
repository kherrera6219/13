"""Pareto option filtering after feasibility & unit compatibility checks (``DVSS-P02``).

Implements DLE-FNS-001 (``DVSS-P02``) and white paper §10: filters infeasible
options first, skips dominance pruning when fewer than two feasible options remain,
enforces compatible metric units before pairwise dominance comparisons, and keeps
every non-dominated feasible frontier option deterministically ordered.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ParetoObjective:
    """Single comparable optimization objective in a declared physical unit."""

    name: str
    direction: Literal["min", "max"]
    unit: str


@dataclass(frozen=True)
class CandidateOption:
    """Feasible or infeasible candidate option evaluated by ``DVSS-P02``."""

    option_id: str
    label: str
    feasible: bool
    metrics: Mapping[str, float]
    units: Mapping[str, str]
    infeasibility_reason: str | None = None


@dataclass(frozen=True)
class UnitConflict:
    """Recorded unit mismatch preventing unsafe cross-unit dominance pruning."""

    objective: str
    expected_unit: str
    option_id: str
    actual_unit: str


@dataclass(frozen=True)
class ParetoResult:
    """Outcome of ``DVSS-P02`` Pareto option filtering."""

    applied: bool
    retained: tuple[CandidateOption, ...]
    dominated: tuple[str, ...]
    infeasible: tuple[str, ...]
    unit_conflicts: tuple[UnitConflict, ...]


def _norm_unit(unit: str | None) -> str:
    return (unit or "").strip().lower()


def _strictly_dominates(
    a: CandidateOption,
    b: CandidateOption,
    objectives: Sequence[ParetoObjective],
) -> bool:
    if not objectives:
        return False
    strictly_better = False
    for obj in objectives:
        if obj.name not in a.metrics or obj.name not in b.metrics:
            return False
        va = float(a.metrics[obj.name])
        vb = float(b.metrics[obj.name])
        if obj.direction == "min":
            if va > vb:
                return False
            if va < vb:
                strictly_better = True
        else:
            if va < vb:
                return False
            if va > vb:
                strictly_better = True
    return strictly_better


def filter_pareto_options(
    *,
    options: Sequence[CandidateOption],
    objectives: Sequence[ParetoObjective],
) -> ParetoResult:
    """Filter infeasible options then retain Pareto-undominated compatible options."""
    infeasible_ids = tuple(sorted(opt.option_id for opt in options if not opt.feasible))
    feasible = sorted((opt for opt in options if opt.feasible), key=lambda o: o.option_id)

    if len(feasible) < 2:
        return ParetoResult(
            applied=False,
            retained=tuple(feasible),
            dominated=(),
            infeasible=infeasible_ids,
            unit_conflicts=(),
        )

    conflicts: list[UnitConflict] = []
    compatible_objectives: list[ParetoObjective] = []
    for obj in objectives:
        expected = _norm_unit(obj.unit)
        obj_ok = True
        for opt in feasible:
            if obj.name not in opt.metrics:
                conflicts.append(
                    UnitConflict(
                        objective=obj.name,
                        expected_unit=obj.unit,
                        option_id=opt.option_id,
                        actual_unit="missing_metric",
                    )
                )
                obj_ok = False
                continue
            actual_raw = opt.units.get(obj.name, "")
            if _norm_unit(actual_raw) != expected:
                conflicts.append(
                    UnitConflict(
                        objective=obj.name,
                        expected_unit=obj.unit,
                        option_id=opt.option_id,
                        actual_unit=actual_raw or "unspecified",
                    )
                )
                obj_ok = False
        if obj_ok:
            compatible_objectives.append(obj)

    if not compatible_objectives:
        return ParetoResult(
            applied=False,
            retained=tuple(feasible),
            dominated=(),
            infeasible=infeasible_ids,
            unit_conflicts=tuple(conflicts),
        )

    retained: list[CandidateOption] = []
    dominated: list[str] = []
    for cand in feasible:
        is_dom = any(
            other.option_id != cand.option_id
            and _strictly_dominates(other, cand, compatible_objectives)
            for other in feasible
        )
        if is_dom:
            dominated.append(cand.option_id)
        else:
            retained.append(cand)

    return ParetoResult(
        applied=True,
        retained=tuple(retained),
        dominated=tuple(dominated),
        infeasible=infeasible_ids,
        unit_conflicts=tuple(conflicts),
    )


__all__ = [
    "CandidateOption",
    "ParetoObjective",
    "ParetoResult",
    "UnitConflict",
    "filter_pareto_options",
]
