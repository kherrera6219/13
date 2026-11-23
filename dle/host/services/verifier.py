"""Independent claim verifier computing NLI support, contradictions, and grounding (``H12``).

Implements FR-VER-02..03, FR-API-04 (``groundingMetadata``), DVSS-K05/K08 wiring,
and DVSS-P04 contradiction detection.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from dle.host.services.claim_extractor import ExtractedClaim
from dle.host.services.evidence import (
    AUTHORITY_PRIOR,
    AuthorityCheckResult,
    EvidenceService,
    RetrievedPassage,
)
from dle.host.services.scorer import DEFAULT_DECAY_RATES, ScoredClaim, source_age_decay
from dle.models.nli import NliScorer

_SCOPE_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DEFAULT_LAMBDA_BY_CLASS: dict[str, float] = {
    "primary_text": DEFAULT_DECAY_RATES["amended"],
    "binding_instrument": DEFAULT_DECAY_RATES["amended"],
    "peer_reviewed": DEFAULT_DECAY_RATES["technical"],
    "industry_practice": DEFAULT_DECAY_RATES["amended"],
    "app_tool": DEFAULT_DECAY_RATES["technical"],
    "google_builtin_tool": DEFAULT_DECAY_RATES["technical"],
    "unhydrated_synthesis": DEFAULT_DECAY_RATES["amended"],
}


@dataclass(frozen=True)
class ContradictionFlag:
    """Detected polarity contradiction across two claims or between claim and passage."""

    claim_a_id: str
    claim_b_id: str
    passage_id: str | None
    reason: str
    score: float


@dataclass(frozen=True)
class VerificationResult:
    """Output of ``ClaimVerifier.verify()`` feeding H13/H14 and response composer."""

    scored_claims: tuple[ScoredClaim, ...]
    authority_checks: tuple[AuthorityCheckResult, ...]
    contradictions: tuple[ContradictionFlag, ...]
    grounding_metadata: dict[str, object]
    all_binding_verified: bool


def _shares_scope(a: ExtractedClaim, b: ExtractedClaim) -> bool:
    if a.scope.entity and b.scope.entity and a.scope.entity.lower() == b.scope.entity.lower():
        return True
    ta = {t for t in _SCOPE_TOKEN_RE.findall(a.assertion.lower()) if len(t) >= 4}
    tb = {t for t in _SCOPE_TOKEN_RE.findall(b.assertion.lower()) if len(t) >= 4}
    return len(ta & tb) >= 2


def detect_contradictions(
    claims: Sequence[ExtractedClaim],
    nli: NliScorer,
    *,
    threshold: float = 0.65,
) -> tuple[ContradictionFlag, ...]:
    """Detect conflicting claims sharing entity/scope (``DVSS-P04``)."""
    flags: list[ContradictionFlag] = []
    for i, c_a in enumerate(claims):
        for c_b in claims[i + 1 :]:
            if not _shares_scope(c_a, c_b):
                continue
            ab = nli.score(c_a.assertion, c_b.assertion)
            ba = nli.score(c_b.assertion, c_a.assertion)
            max_contra = max(ab.contradiction, ba.contradiction)
            if max_contra >= threshold:
                flags.append(
                    ContradictionFlag(
                        claim_a_id=c_a.claim_id,
                        claim_b_id=c_b.claim_id,
                        passage_id=None,
                        reason="conflicting polarity on normalized claim scope",
                        score=round(max_contra, 4),
                    )
                )
    return tuple(flags)


def _age_years(valid_from: str | None, as_of: date) -> float:
    if not valid_from:
        return 0.0
    try:
        start_d = date.fromisoformat(valid_from)
    except ValueError:
        return 0.0
    delta_days = (as_of - start_d).days
    return max(0.0, delta_days / 365.25)


def _build_grounding_metadata(
    passages_by_id: Mapping[str, RetrievedPassage],
    scored_claims: Sequence[ScoredClaim],
    draft_text: str,
) -> dict[str, object]:
    chunk_indices: dict[str, int] = {}
    grounding_chunks: list[dict[str, object]] = []

    def _chunk_index(pid: str) -> int:
        if pid in chunk_indices:
            return chunk_indices[pid]
        p = passages_by_id[pid]
        idx = len(grounding_chunks)
        chunk_indices[pid] = idx
        grounding_chunks.append(
            {
                "retrievedContext": {
                    "uri": f"dle://source/{p.source_id}@{p.revision}#{p.locator}",
                    "title": p.title,
                    "text": p.text,
                }
            }
        )
        return idx

    grounding_supports: list[dict[str, object]] = []
    for claim in scored_claims:
        if not claim.passage_ids:
            continue
        indices = [_chunk_index(pid) for pid in claim.passage_ids if pid in passages_by_id]
        if not indices:
            continue
        seg_text = (
            draft_text[claim.span_start : claim.span_end]
            if 0 <= claim.span_start < claim.span_end <= len(draft_text)
            else claim.assertion
        )
        grounding_supports.append(
            {
                "segment": {
                    "startIndex": claim.span_start,
                    "endIndex": claim.span_end,
                    "text": seg_text,
                },
                "groundingChunkIndices": indices,
                "confidenceScores": [round(claim.support_z, 4) for _ in indices],
            }
        )

    return {
        "groundingChunks": grounding_chunks,
        "groundingSupports": grounding_supports,
    }


class ClaimVerifier:
    """Independent NLI + provenance + authority verifier (``H12``)."""

    def __init__(self, nli: NliScorer, evidence: EvidenceService) -> None:
        """Initialize verifier with an ``NliScorer`` and ``EvidenceService``."""
        self._nli = nli
        self._evidence = evidence

    def verify(
        self,
        *,
        claims: Sequence[ExtractedClaim],
        passages: Sequence[RetrievedPassage],
        draft_text: str = "",
        as_of: date | None = None,
        decay_rate_by_class: Mapping[str, float] | None = None,
        source_unavailable: bool = False,
        contradiction_threshold: float = 0.65,
    ) -> VerificationResult:
        """Score every claim against active passages, verify authority, and build grounding."""
        eff_date = as_of if as_of is not None else datetime.now(UTC).date()
        rates = (
            {**_DEFAULT_LAMBDA_BY_CLASS, **decay_rate_by_class}
            if decay_rate_by_class is not None
            else _DEFAULT_LAMBDA_BY_CLASS
        )

        passages_by_id = {p.passage_id: p for p in passages}
        scored: list[ScoredClaim] = []
        auth_checks: list[AuthorityCheckResult] = []
        contradictions: list[ContradictionFlag] = list(
            detect_contradictions(claims, self._nli, threshold=contradiction_threshold)
        )

        for claim in claims:
            best_z = 0.0
            best_e = 0.0
            best_p = 0.0
            best_b = 0.0
            max_contra = 0.0
            best_pid: str | None = None

            for p_obj in passages:
                nli_res = self._nli.score(p_obj.text, claim.assertion)
                prior = AUTHORITY_PRIOR.get(p_obj.authority_class, 0.35)
                z_val = prior * nli_res.entailment
                if nli_res.contradiction > max_contra:
                    max_contra = nli_res.contradiction
                if nli_res.contradiction >= contradiction_threshold:
                    contradictions.append(
                        ContradictionFlag(
                            claim_a_id=claim.claim_id,
                            claim_b_id=p_obj.passage_id,
                            passage_id=p_obj.passage_id,
                            reason="passage contradicts claim assertion",
                            score=round(nli_res.contradiction, 4),
                        )
                    )
                if z_val > best_z:
                    best_z = z_val
                    best_e = nli_res.entailment
                    best_p = prior
                    lam = rates.get(p_obj.authority_class, 0.05)
                    best_b = source_age_decay(
                        provenance_prior=prior,
                        active_in_scope=p_obj.active_in_scope,
                        age_years=_age_years(p_obj.valid_from, eff_date),
                        decay_lambda=lam,
                    )
                    best_pid = p_obj.passage_id

            chosen_pids = (best_pid,) if (best_pid is not None and best_z >= 0.25) else ()
            auth_res = self._evidence.verify_binding_authority(
                claim_id=claim.claim_id,
                assertion=claim.assertion,
                binding=claim.binding,
                passages=passages,
                attached_passage_ids=chosen_pids,
                source_unavailable=source_unavailable,
            )
            auth_checks.append(auth_res)

            # Force support_z = 0 when claim span could not be validated (K01 safety check).
            eff_z = best_z if claim.span_valid else 0.0
            scored.append(
                ScoredClaim(
                    claim_id=claim.claim_id,
                    proposal_id=claim.proposal_id,
                    assertion=claim.assertion,
                    binding=claim.binding,
                    scope_label=claim.scope.summary_label(),
                    passage_ids=chosen_pids,
                    entailment=round(best_e, 6),
                    provenance=round(best_p, 6),
                    belief=round(best_b, 6),
                    support_z=round(eff_z, 6),
                    contradiction=round(max_contra, 6),
                    authority_status=auth_res.status,
                    span_start=claim.span_start,
                    span_end=claim.span_end,
                )
            )

        all_binding_verified = all(
            a.status == "verified" for a in auth_checks if a.status != "not_applicable"
        )
        grounding = _build_grounding_metadata(passages_by_id, scored, draft_text)
        return VerificationResult(
            scored_claims=tuple(scored),
            authority_checks=tuple(auth_checks),
            contradictions=tuple(contradictions),
            grounding_metadata=grounding,
            all_binding_verified=all_binding_verified,
        )


__all__ = [
    "ClaimVerifier",
    "ContradictionFlag",
    "VerificationResult",
    "detect_contradictions",
]
