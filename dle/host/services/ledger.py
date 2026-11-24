"""Verifier-only append-only objection ledger service (``H11``, ``DVSS-K12``).

Implements FR-VER-02 and DVSS-K12 over ``sessions.db`` (``ledger_entries``):
persists open objections across retries and escalations, normalizes any role's
``proposed_closed`` or unauthorized ``closed`` objection to ``open``, and allows
closing an objection strictly by ``verifier`` with non-empty verified evidence.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from dle.errors import ContractValidationError
from dle.host.services.release import LedgerObjection, evaluate_compliance_veto
from dle.observability import get_logger
from dle.store.repositories import SessionRepository


@dataclass(frozen=True)
class ProposedClosure:
    """In-memory record of a role's request to close an objection (awaiting verifier)."""

    objection_id: str
    role_axis: int
    proposed_evidence: tuple[str, ...]


class LedgerService:
    """Append-only ``sessions.db`` ledger controller enforcing ``DVSS-K12``."""

    def __init__(self, session_repo: SessionRepository) -> None:
        """Bind service to persistent ``SessionRepository``."""
        self._repo = session_repo
        self._log = get_logger("dle.host.services.ledger")

    def record_role_objections(
        self,
        *,
        run_id: str,
        attempt_id: str,
        raw_objections: Sequence[Mapping[str, object]],
        utc_iso: str,
    ) -> tuple[tuple[LedgerObjection, ...], tuple[ProposedClosure, ...]]:
        """Persist role objections as ``open`` regardless of role closure proposals."""
        recorded: list[LedgerObjection] = []
        proposed: list[ProposedClosure] = []

        for raw in raw_objections:
            oid = str(raw.get("objection_id", "")).strip()
            if not oid:
                raise ContractValidationError(
                    "role objection missing non-empty objection_id",
                    file_path="ledger",
                    pointer="/objection_id",
                )
            raw_axis = raw.get("role_axis", 10)
            role_axis = int(raw_axis) if isinstance(raw_axis, int) else int(str(raw_axis))
            proposal_id = str(raw.get("proposal_id", "p0"))
            blocking = bool(raw.get("blocking", True))
            predicate = str(raw.get("predicate", "")).strip() or "unspecified_predicate"
            raw_state = str(raw.get("state", "open"))
            raw_ev = raw.get("closure_evidence", ())
            ev_ids = (
                tuple(str(x).strip() for x in raw_ev if str(x).strip())
                if isinstance(raw_ev, Sequence) and not isinstance(raw_ev, str | bytes)
                else ()
            )
            if raw_state in ("proposed_closed", "closed") and ev_ids:
                proposed.append(
                    ProposedClosure(
                        objection_id=oid,
                        role_axis=role_axis,
                        proposed_evidence=ev_ids,
                    )
                )

            # Roles can never close ledger objections directly (FR-VER-02, DVSS-K12).
            self._repo.append_ledger_entry(
                run_id=run_id,
                attempt_id=attempt_id,
                objection_id=oid,
                role_axis=role_axis,
                blocking=blocking,
                predicate=predicate,
                state="open",
                closed_by=None,
                evidence_ids=(),
                created_utc=utc_iso,
            )
            recorded.append(
                LedgerObjection(
                    objection_id=oid,
                    role_axis=role_axis,
                    proposal_id=proposal_id,
                    blocking=blocking,
                    predicate=predicate,
                    state="open",
                    closed_by=None,
                    closure_evidence=(),
                )
            )
        return tuple(recorded), tuple(proposed)

    def record_objections(
        self,
        *,
        run_id: str,
        attempt_id: str,
        objections: Sequence[LedgerObjection],
        utc_iso: str,
    ) -> tuple[LedgerObjection, ...]:
        """Persist host-originated safety/span/contradiction objections via ``DVSS-K12``."""
        seen_open = {o.objection_id for o in self.current_state(run_id) if o.state == "open"}
        normalized, _ = evaluate_compliance_veto(objections, seen_open_ids=seen_open)
        for obj in normalized:
            self._repo.append_ledger_entry(
                run_id=run_id,
                attempt_id=attempt_id,
                objection_id=obj.objection_id,
                role_axis=obj.role_axis,
                blocking=obj.blocking,
                predicate=obj.predicate,
                state=obj.state,
                closed_by=obj.closed_by,
                evidence_ids=obj.closure_evidence,
                created_utc=utc_iso,
            )
        return normalized

    def close_by_verifier(
        self,
        *,
        run_id: str,
        attempt_id: str,
        objection_id: str,
        evidence_ids: Sequence[str],
        allowed_passage_ids: Collection[str],
        predicate_satisfied: bool,
        utc_iso: str,
    ) -> LedgerObjection:
        """Append a verifier-only closure entry once predicate & passage evidence check out."""
        current = {o.objection_id: o for o in self.current_state(run_id)}
        target = current.get(objection_id)
        if target is None:
            raise ContractValidationError(
                f"cannot close unknown objection {objection_id!r} for run {run_id}",
                file_path="ledger",
                pointer="/objection_id",
            )
        if not predicate_satisfied:
            raise ContractValidationError(
                f"cannot close objection {objection_id!r}: predicate not satisfied",
                file_path="ledger",
                pointer="/predicate_satisfied",
            )
        clean_ev = tuple(
            dict.fromkeys(str(eid).strip() for eid in evidence_ids if str(eid).strip())
        )
        if not clean_ev:
            raise ContractValidationError(
                f"cannot close objection {objection_id!r} without non-empty closure evidence",
                file_path="ledger",
                pointer="/closure_evidence",
            )
        unknown_ev = [eid for eid in clean_ev if eid not in allowed_passage_ids]
        if unknown_ev:
            raise ContractValidationError(
                f"closure evidence for {objection_id!r} references unknown passages {unknown_ev}",
                file_path="ledger",
                pointer="/closure_evidence",
            )

        self._repo.append_ledger_entry(
            run_id=run_id,
            attempt_id=attempt_id,
            objection_id=target.objection_id,
            role_axis=target.role_axis,
            blocking=target.blocking,
            predicate=target.predicate,
            state="closed",
            closed_by="verifier",
            evidence_ids=clean_ev,
            created_utc=utc_iso,
        )
        self._log.info(
            "ledger.objection_closed",
            run_id=run_id,
            attempt_id=attempt_id,
            objection_id=target.objection_id,
            evidence_count=len(clean_ev),
        )
        return LedgerObjection(
            objection_id=target.objection_id,
            role_axis=target.role_axis,
            proposal_id=target.proposal_id,
            blocking=target.blocking,
            predicate=target.predicate,
            state="closed",
            closed_by="verifier",
            closure_evidence=clean_ev,
        )

    def current_state(self, run_id: str) -> tuple[LedgerObjection, ...]:
        """Reconstruct latest normalized ledger state for ``run_id`` in seq order."""
        rows = self._repo.get_ledger_entries(run_id)
        by_id: dict[str, LedgerObjection] = {}
        seen_open_ids: set[str] = set()

        for row in rows:
            oid = str(row["objection_id"])
            raw_state = "closed" if str(row["state"]) == "closed" else "open"
            raw_ev = row.get("evidence", [])
            ev_tuple = (
                tuple(str(x) for x in raw_ev)
                if isinstance(raw_ev, Sequence) and not isinstance(raw_ev, str | bytes)
                else ()
            )
            closed_by = str(row["closed_by"]) if row.get("closed_by") is not None else None
            # Reject unauthorized closures or first-seen closed items via DVSS-K12 invariant.
            is_valid_close = (
                raw_state == "closed"
                and closed_by == "verifier"
                and len(ev_tuple) > 0
                and oid in seen_open_ids
            )
            eff_state: Literal["open", "closed"] = "closed" if is_valid_close else "open"
            if eff_state == "open":
                seen_open_ids.add(oid)
            raw_axis = row.get("role_axis", 10)
            role_axis = int(raw_axis) if isinstance(raw_axis, int) else int(str(raw_axis))
            by_id[oid] = LedgerObjection(
                objection_id=oid,
                role_axis=role_axis,
                proposal_id="p0",
                blocking=bool(row["blocking"]),
                predicate=str(row["predicate"]),
                state=eff_state,
                closed_by="verifier" if eff_state == "closed" else None,
                closure_evidence=ev_tuple if eff_state == "closed" else (),
            )
        return tuple(by_id.values())

    def open_blocking_objections(self, run_id: str) -> tuple[LedgerObjection, ...]:
        """Return currently open blocking objections for ``run_id``."""
        return tuple(o for o in self.current_state(run_id) if o.blocking and o.state == "open")

    def carry_forward_snapshot(self, run_id: str) -> list[dict[str, object]]:
        """Serialize open objections for carry-forward across retries/escalations."""
        return [
            {
                "objection_id": o.objection_id,
                "role_axis": o.role_axis,
                "blocking": o.blocking,
                "predicate": o.predicate,
                "state": o.state,
            }
            for o in self.current_state(run_id)
            if o.state == "open"
        ]


__all__ = ["LedgerService", "ProposedClosure"]
