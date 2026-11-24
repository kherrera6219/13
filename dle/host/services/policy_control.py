"""Cutoff-blind retries (``DVSS-K09``), binding escalation (``DVSS-P07``) & tool flags.

Implements FR-WF-03..05, FR-TOOL-05, DLE-FNS-001 (``DVSS-K09`` and ``DVSS-P07``),
and white paper §16b invariants: ``DVSS-K09`` is strictly blind to CRC cutoffs,
drift state, and gold labels, caps retries at ``<= 2``, and ``DVSS-P07``
performs at most one Regulator escalation with ``S_eff = max(S, 3, 6Z)``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from dle.config.models import FunctionFlagsConfig


@dataclass(frozen=True)
class RetryPolicyInput:
    """Cutoff-blind input structure evaluated by ``DVSS-K09``."""

    retries_used: int
    has_recoverable_gap: bool
    has_permanent_veto: bool
    new_evidence_found: bool
    resolved: bool
    candidate_id: str
    max_retries: int = 2
    gap_reason: str | None = None
    authorized_next_source: str | None = None


@dataclass(frozen=True)
class RetryDecision:
    """Deterministic outcome of ``DVSS-K09`` two-retry policy."""

    action: Literal["retry", "terminal"]
    reason: str
    candidate_id: str
    next_source: str | None
    hop_increment: int


@dataclass(frozen=True)
class EscalationDecision:
    """Outcome of ``DVSS-P07`` one-time binding escalation."""

    should_escalate: bool
    new_tier: int
    new_s_eff: int
    new_roles: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ConsequentialToolHit:
    """Client tool flagged consequential by ``config/function_flags.yaml``."""

    name: str
    reason: str


def decide_retry_policy(policy_in: RetryPolicyInput) -> RetryDecision:
    """Evaluate strictly cutoff-blind ``DVSS-K09`` retry vs terminal policy.

    Notice by design there is no parameter for ``cutoff``, ``threshold``,
    ``drift_latched``, or labels — candidate generation cannot leak cutoff choices.
    """
    eff_max = min(max(0, policy_in.max_retries), 2)
    if policy_in.resolved:
        return RetryDecision(
            action="terminal",
            reason="resolved",
            candidate_id=policy_in.candidate_id,
            next_source=None,
            hop_increment=0,
        )
    if policy_in.has_permanent_veto:
        return RetryDecision(
            action="terminal",
            reason="permanent_veto",
            candidate_id=policy_in.candidate_id,
            next_source=None,
            hop_increment=0,
        )
    if policy_in.retries_used >= eff_max:
        return RetryDecision(
            action="terminal",
            reason="retry_budget_exhausted",
            candidate_id=policy_in.candidate_id,
            next_source=None,
            hop_increment=0,
        )
    if policy_in.retries_used > 0 and not policy_in.new_evidence_found:
        return RetryDecision(
            action="terminal",
            reason="no_useful_new_evidence",
            candidate_id=policy_in.candidate_id,
            next_source=None,
            hop_increment=0,
        )
    if not policy_in.has_recoverable_gap or not (
        policy_in.authorized_next_source and policy_in.authorized_next_source.strip()
    ):
        return RetryDecision(
            action="terminal",
            reason="no_authorized_recoverable_gap",
            candidate_id=policy_in.candidate_id,
            next_source=None,
            hop_increment=0,
        )
    return RetryDecision(
        action="retry",
        reason=(policy_in.gap_reason or "recoverable_evidence_gap").strip(),
        candidate_id=policy_in.candidate_id,
        next_source=policy_in.authorized_next_source.strip(),
        hop_increment=1,
    )


def evaluate_binding_escalation(
    *,
    tier: int,
    s_score: int,
    z_flag: int,
    active_roles: Sequence[str],
    has_binding_claim: bool,
    escalated_once: bool,
    consequential_tool_used: bool = False,
) -> EscalationDecision:
    """Evaluate one-time ``DVSS-P07`` Regulator escalation (uncounted against retries)."""
    norm_roles = [r.lower().strip() for r in active_roles if r.strip()]
    has_regulator = "regulator" in norm_roles
    needs_regulator = has_binding_claim or consequential_tool_used

    if not needs_regulator or has_regulator or escalated_once:
        eff_roles = tuple(dict.fromkeys(norm_roles or ["scholar"]))
        return EscalationDecision(
            should_escalate=False,
            new_tier=tier,
            new_s_eff=max(s_score, 3 * (1 if needs_regulator else 0), 6 * z_flag),
            new_roles=eff_roles,
            reason=(
                "already_escalated"
                if escalated_once
                else ("regulator_already_active" if has_regulator else "non_binding")
            ),
        )

    # Recompute S_eff with B = 1 per DLE-FNS-001 DVSS-P07 and tiers.yaml.
    new_s_eff = max(s_score, 3, 6 * z_flag)
    new_tier = 3 if new_s_eff >= 6 else max(tier, 2)
    expanded_roles = list(dict.fromkeys(norm_roles or ["scholar"]))
    if new_tier >= 2 and "practitioner" not in expanded_roles:
        expanded_roles.append("practitioner")
    if "regulator" not in expanded_roles:
        expanded_roles.append("regulator")
    if new_tier >= 3 and "harmonizer" not in expanded_roles:
        expanded_roles.append("harmonizer")

    reason = (
        "consequential_tool_requires_regulator"
        if consequential_tool_used and not has_binding_claim
        else "binding_claim_without_regulator"
    )
    return EscalationDecision(
        should_escalate=True,
        new_tier=new_tier,
        new_s_eff=new_s_eff,
        new_roles=tuple(expanded_roles),
        reason=reason,
    )


def check_consequential_functions(
    contents: Sequence[Mapping[str, object]],
    function_flags: FunctionFlagsConfig,
) -> tuple[ConsequentialToolHit, ...]:
    """Identify consequential ``functionResponse`` calls per ``config/function_flags.yaml``."""
    flagged_by_name = {entry.name: entry.reason for entry in function_flags.consequential_functions}
    if not flagged_by_name:
        return ()

    hits: list[ConsequentialToolHit] = []
    seen: set[str] = set()
    for turn in contents:
        parts = turn.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, Mapping):
                continue
            fr = part.get("functionResponse")
            if not isinstance(fr, Mapping):
                continue
            fn_name = str(fr.get("name", "")).strip()
            if fn_name in flagged_by_name and fn_name not in seen:
                seen.add(fn_name)
                hits.append(ConsequentialToolHit(name=fn_name, reason=flagged_by_name[fn_name]))
    return tuple(hits)


__all__ = [
    "ConsequentialToolHit",
    "EscalationDecision",
    "RetryDecision",
    "RetryPolicyInput",
    "check_consequential_functions",
    "decide_retry_policy",
    "evaluate_binding_escalation",
]
