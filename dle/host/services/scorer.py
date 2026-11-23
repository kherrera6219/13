"""Claim age-decay and terminal uncertainty scoring (``H13``, ``DVSS-K08``).

Implements FR-REL-01, DVSS-K08 (``F-DECAY-01`` source-age decay), and
``F-SCORE-01`` terminal uncertainty score ``u``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_DECAY_RATES: dict[str, float] = {
    "stable": 0.0,
    "technical": 0.01,
    "amended": 0.05,
}


@dataclass(frozen=True)
class ScoredClaim:
    """Verified claim annotated with support ``z = p * e``, belief ``b``, and citations."""

    claim_id: str
    proposal_id: str
    assertion: str
    binding: bool
    scope_label: str
    passage_ids: tuple[str, ...]
    entailment: float
    provenance: float
    belief: float
    support_z: float
    contradiction: float
    authority_status: str
    span_start: int
    span_end: int


@dataclass(frozen=True)
class TerminalScore:
    """Terminal candidate verification uncertainty ``u`` and component diagnostics."""

    u: float
    min_z_j: float
    mean_z: float
    min_b_j: float
    d: float
    weakest_claim_id: str | None


def _clamp01(val: float) -> float:
    return max(0.0, min(1.0, float(val)))


def source_age_decay(
    *,
    provenance_prior: float,
    active_in_scope: bool,
    age_years: float,
    decay_lambda: float,
) -> float:
    """Compute source-age decayed belief ``b_i = p_i * I[active] * exp(-lambda_i * age_i)``."""
    if not active_in_scope:
        return 0.0
    p = _clamp01(provenance_prior)
    age = max(0.0, float(age_years))
    lam = max(0.0, float(decay_lambda))
    return _clamp01(p * math.exp(-lam * age))


def compute_terminal_u(
    claims: Sequence[ScoredClaim],
    *,
    open_objections: int,
    total_objections: int,
) -> TerminalScore:
    """Compute ``F-SCORE-01`` terminal uncertainty ``u`` over scored claims and objections."""
    if open_objections < 0 or total_objections < 0 or open_objections > total_objections:
        raise ValueError(
            f"invalid objection counts: open={open_objections}, total={total_objections}"
        )
    d = (open_objections / total_objections) if total_objections > 0 else 0.0

    if not claims:
        return TerminalScore(
            u=1.0,
            min_z_j=0.0,
            mean_z=0.0,
            min_b_j=0.0,
            d=d,
            weakest_claim_id=None,
        )

    j_claims = [c for c in claims if c.binding] or list(claims)
    min_z_j = min(_clamp01(c.support_z) for c in j_claims)
    mean_z = sum(_clamp01(c.support_z) for c in claims) / len(claims)
    min_b_j = min(_clamp01(c.belief) for c in j_claims)

    u = 0.40 * (1.0 - min_z_j) + 0.20 * (1.0 - mean_z) + 0.25 * (1.0 - min_b_j) + 0.15 * d
    weakest = min(claims, key=lambda c: (c.support_z, c.claim_id))
    return TerminalScore(
        u=_clamp01(u),
        min_z_j=min_z_j,
        mean_z=mean_z,
        min_b_j=min_b_j,
        d=d,
        weakest_claim_id=weakest.claim_id,
    )


__all__ = [
    "DEFAULT_DECAY_RATES",
    "ScoredClaim",
    "TerminalScore",
    "compute_terminal_u",
    "source_age_decay",
]
