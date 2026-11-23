"""Release controller, compliance veto, CUSUM drift, safety, and disclosure (``H14``).

Implements FR-REL-01..04, FR-API-05..06, DVSS-K04 (hard + CRC gate),
DVSS-K11 (canonical disclosure/hold mapping), DVSS-K12 (verifier-only veto),
DVSS-P12 (fixed-baseline CUSUM drift), and DVSS-P13 (safety policy).
Only K04, K11, and K12 may produce holds; P13 emits blocking objections only.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from dle.config.models import NoticesConfig, NoticeTemplate
from dle.host.services.scorer import ScoredClaim, TerminalScore
from dle.observability import sha256_text
from dle.store.repositories import OpsRepository

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+|any\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"reveal\s+(?:the\s+|your\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+)?safety\s+rules", re.IGNORECASE),
)

_OUTPUT_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE\s+KEY-----"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
)


@dataclass(frozen=True)
class CalibrationArtifact:
    """Approved CRC cutoff and baseline CUSUM drift parameters."""

    artifact_id: str
    artifact_sha256: str
    n_cal: int
    alpha: float
    threshold: float
    mu_0: float
    drift_lambda: float
    drift_delta: float = 0.02


@dataclass(frozen=True)
class LedgerObjection:
    """Structured compliance or safety objection entry tracked through ``DVSS-K12``."""

    objection_id: str
    role_axis: int
    proposal_id: str
    blocking: bool
    predicate: str
    state: Literal["open", "closed"]
    closed_by: str | None = None
    closure_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateDecision:
    """Outcome of ``DVSS-K04`` ordered release decision table."""

    hard_gate: bool
    u: float
    cutoff: float
    drift_latched: bool
    cusum: float
    decision: Literal["block", "withhold_drift", "abstain_or_explain", "release"]
    block_reason: str | None = None
    open_blocking_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DisclosureOutcome:
    """Outcome of ``DVSS-K11`` mapping internal decision + profile to user-visible output."""

    receipt_release_mode: str
    api_release_mode: Literal["released", "released_advisory", "held"]
    notice_id: str
    final_text: str
    response_sha256: str


def evaluate_compliance_veto(
    objections: Sequence[LedgerObjection],
    *,
    seen_open_ids: set[str] | None = None,
) -> tuple[tuple[LedgerObjection, ...], tuple[LedgerObjection, ...]]:
    """Enforce ``DVSS-K12`` verifier-only closure with evidence."""
    normalized: list[LedgerObjection] = []
    open_blocking: list[LedgerObjection] = []

    for obj in objections:
        first_seen_closed = (
            seen_open_ids is not None
            and obj.state == "closed"
            and obj.objection_id not in seen_open_ids
        )
        valid_closure = (
            obj.state == "closed"
            and obj.closed_by == "verifier"
            and len(obj.closure_evidence) > 0
            and not first_seen_closed
        )
        eff = (
            obj
            if (obj.state == "open" or valid_closure)
            else replace(obj, state="open", closed_by=None, closure_evidence=())
        )
        normalized.append(eff)
        if eff.blocking and eff.state == "open":
            open_blocking.append(eff)

    return tuple(normalized), tuple(open_blocking)


def safety_policy_check(
    *,
    input_content: str = "",
    output_content: str = "",
    proposal_id: str = "p0",
) -> tuple[LedgerObjection, ...]:
    """Run ``DVSS-P13`` safety checks emitting blocking objections (never holds directly)."""
    objections: list[LedgerObjection] = []
    if input_content:
        for idx, pat in enumerate(_INJECTION_PATTERNS, start=1):
            if pat.search(input_content):
                objections.append(
                    LedgerObjection(
                        objection_id=f"safety-input-{idx}",
                        role_axis=10,
                        proposal_id=proposal_id,
                        blocking=True,
                        predicate="prompt_injection_marker",
                        state="open",
                    )
                )
                break
    if output_content:
        for idx, pat in enumerate(_OUTPUT_SECRET_PATTERNS, start=1):
            if pat.search(output_content):
                objections.append(
                    LedgerObjection(
                        objection_id=f"safety-output-{idx}",
                        role_axis=10,
                        proposal_id=proposal_id,
                        blocking=True,
                        predicate="sensitive_output_disclosure",
                        state="open",
                    )
                )
                break
    return tuple(objections)


def update_cusum_drift(
    *,
    previous_c_t: float,
    u_t: float,
    calibration: CalibrationArtifact,
    previous_latched: bool = False,
    version_changed_reason: str | None = None,
    ops_repo: OpsRepository | None = None,
) -> tuple[float, bool, str | None]:
    """Advance fixed-baseline CUSUM monitor (``DVSS-P12`` / H14 fallback)."""
    c_t = max(
        0.0,
        float(previous_c_t) + float(u_t) - calibration.mu_0 - calibration.drift_delta,
    )
    latched = bool(previous_latched)
    reason: str | None = None
    if version_changed_reason:
        latched = True
        reason = version_changed_reason
    elif c_t > calibration.drift_lambda:
        latched = True
        reason = f"cusum {c_t:.4f} exceeded threshold {calibration.drift_lambda:.4f}"

    if ops_repo is not None:
        ops_repo.upsert_drift_state(
            c_t=round(c_t, 6),
            mu0=calibration.mu_0,
            delta=calibration.drift_delta,
            lambda_val=calibration.drift_lambda,
            is_latched=latched,
            latch_reason=reason,
            updated_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    return round(c_t, 6), latched, reason


def evaluate_release_gate(
    *,
    schema_scope_valid: bool,
    claims: Sequence[ScoredClaim],
    all_binding_verified: bool,
    open_blocking_objections: Sequence[LedgerObjection],
    score: TerminalScore,
    calibration: CalibrationArtifact | None,
    drift_latched: bool,
    cusum: float,
) -> GateDecision:
    """Apply ``DVSS-K04`` hard gate and ordered CRC decision table (§16c)."""
    if calibration is None:
        return GateDecision(
            hard_gate=False,
            u=score.u,
            cutoff=0.0,
            drift_latched=drift_latched,
            cusum=cusum,
            decision="block",
            block_reason="missing_calibration_artifact",
            open_blocking_ids=tuple(o.objection_id for o in open_blocking_objections),
        )

    block_reason: str | None = None
    if open_blocking_objections:
        block_reason = "open_blocking_objection"
    elif len(claims) == 0:
        block_reason = "empty_claim_set"
    elif not all_binding_verified:
        block_reason = "binding_claim_unverified"
    elif not schema_scope_valid:
        block_reason = "schema_or_scope_invalid"

    hard_gate = block_reason is None
    open_ids = tuple(o.objection_id for o in open_blocking_objections)

    if not hard_gate:
        return GateDecision(
            hard_gate=False,
            u=score.u,
            cutoff=calibration.threshold,
            drift_latched=drift_latched,
            cusum=cusum,
            decision="block",
            block_reason=block_reason,
            open_blocking_ids=open_ids,
        )
    if drift_latched:
        return GateDecision(
            hard_gate=True,
            u=score.u,
            cutoff=calibration.threshold,
            drift_latched=True,
            cusum=cusum,
            decision="withhold_drift",
        )
    if score.u >= calibration.threshold:
        return GateDecision(
            hard_gate=True,
            u=score.u,
            cutoff=calibration.threshold,
            drift_latched=False,
            cusum=cusum,
            decision="abstain_or_explain",
        )
    return GateDecision(
        hard_gate=True,
        u=score.u,
        cutoff=calibration.threshold,
        drift_latched=False,
        cusum=cusum,
        decision="release",
    )


class _SafeFormat(dict[str, object]):
    def __missing__(self, key: str) -> str:
        return f"<{key}>"


def _render_notice(notices: NoticesConfig, notice_id: str, context: dict[str, object]) -> str:
    by_id: dict[str, NoticeTemplate] = {n.id: n for n in notices.notices}
    tmpl = by_id.get(notice_id)
    if tmpl is None:
        return f"Verification notice ({notice_id})."
    return tmpl.text.format_map(_SafeFormat(context))


def apply_disclosure(
    *,
    gate: GateDecision,
    profile: str,
    draft_text: str,
    notices: NoticesConfig,
    receipt_id: str,
    source_count: int = 0,
    flagged_count: int = 0,
    weakest_claim_summary: str = "supporting evidence below threshold",
    objection_predicate: str = "compliance obligation",
    required_evidence: str = "authoritative record",
    authority: str = "compliance reviewer",
    claim_summary: str = "binding statement",
    retrieval_status: str = "not_found",
) -> DisclosureOutcome:
    """Apply canonical ``DVSS-K11`` decision-to-output mapping and embed advisory notices."""
    is_advisory = profile == "advisory"
    ctx: dict[str, object] = {
        "receipt_id": receipt_id,
        "source_count": source_count,
        "flagged_count": flagged_count,
        "weakest_claim_summary": weakest_claim_summary,
        "objection_predicate": objection_predicate,
        "required_evidence": required_evidence,
        "authority": authority,
        "claim_summary": claim_summary,
        "retrieval_status": retrieval_status,
    }

    receipt_mode: str
    api_mode: Literal["released", "released_advisory", "held"]
    notice_id: str

    if gate.decision == "block":
        receipt_mode = "hard_veto_block"
        api_mode = "held"
        notice_map = {
            "open_blocking_objection": "NOTICE-HOLD-01",
            "binding_claim_unverified": "NOTICE-HOLD-02",
            "empty_claim_set": "NOTICE-HOLD-03",
            "model_unavailable": "NOTICE-HOLD-06",
        }
        notice_id = notice_map.get(gate.block_reason or "", "NOTICE-HOLD-07")
        final_text = _render_notice(notices, notice_id, ctx)
    elif gate.decision == "withhold_drift":
        if is_advisory:
            receipt_mode = "annotated_release_drift_warning"
            api_mode = "released_advisory"
            notice_id = "NOTICE-ADV-02"
            notice_text = _render_notice(notices, notice_id, ctx)
            final_text = f"{notice_text}\n\n{draft_text}".strip()
        else:
            receipt_mode = "review_required"
            api_mode = "held"
            notice_id = "NOTICE-HOLD-05"
            final_text = _render_notice(notices, notice_id, ctx)
    elif gate.decision == "abstain_or_explain":
        if is_advisory:
            receipt_mode = "annotated_release_ka39"
            api_mode = "released_advisory"
            notice_id = "NOTICE-ADV-01"
            notice_text = _render_notice(notices, notice_id, ctx)
            final_text = f"{notice_text}\n\n{draft_text}".strip()
        else:
            receipt_mode = "abstained"
            api_mode = "held"
            notice_id = "NOTICE-HOLD-04"
            final_text = _render_notice(notices, notice_id, ctx)
    else:
        receipt_mode = "gate_passed"
        api_mode = "released"
        notice_id = "NOTICE-REL-01"
        final_text = draft_text

    return DisclosureOutcome(
        receipt_release_mode=receipt_mode,
        api_release_mode=api_mode,
        notice_id=notice_id,
        final_text=final_text,
        response_sha256=sha256_text(final_text),
    )


__all__ = [
    "CalibrationArtifact",
    "DisclosureOutcome",
    "GateDecision",
    "LedgerObjection",
    "apply_disclosure",
    "evaluate_compliance_veto",
    "evaluate_release_gate",
    "safety_policy_check",
    "update_cusum_drift",
]
