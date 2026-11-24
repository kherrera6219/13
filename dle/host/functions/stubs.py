"""Phase 1 host kernel handlers and required policy fallbacks registered on H16.

Implements FR-FN-01..02, FR-WF-01 (stub), DLE-FNS-001 canonical K11 mapping,
and DLE-PLN-001 pilot K10/K11/K12 execution through H16.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping

from dle.config.models import NoticesConfig
from dle.host.functions.registry import (
    FunctionContext,
    FunctionHandler,
    FunctionRegistry,
    FunctionResult,
)
from dle.observability import sha256_text


def _as_int(val: object, default: int = 0) -> int:
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int | float):
        return int(val)
    return default


def _k01_validate(ctx: FunctionContext) -> FunctionResult:
    if not isinstance(ctx.payload, dict):
        return FunctionResult("error", {"valid": False, "errors": ["payload must be a mapping"]})
    return FunctionResult("ok", {"valid": True, "errors": []})


def _k02_coordinate_parse(ctx: FunctionContext) -> FunctionResult:
    return FunctionResult("ok", {"coordinate": ctx.payload.get("coordinate", {}), "status": "stub"})


def _k03_profile_match(ctx: FunctionContext) -> FunctionResult:
    return FunctionResult("ok", {"roles": ctx.payload.get("roles", ["scholar"]), "status": "stub"})


def _k04_gate(ctx: FunctionContext) -> FunctionResult:
    hard_gate = bool(ctx.payload.get("hard_gate", False))
    drift_latched = bool(ctx.payload.get("drift_latched", False))
    raw_u = ctx.payload.get("terminal_u", 1.0)
    raw_cutoff = ctx.payload.get("cutoff", 0.0)
    u = float(raw_u) if isinstance(raw_u, int | float) else 1.0
    cutoff = float(raw_cutoff) if isinstance(raw_cutoff, int | float) else 0.0

    if not hard_gate:
        decision = "block"
    elif drift_latched:
        decision = "withhold_drift"
    elif u >= cutoff:
        decision = "abstain_or_explain"
    else:
        decision = "release"
    return FunctionResult(
        "hold" if decision == "block" else "ok",
        {"hard_gate": hard_gate, "u": u, "cutoff": cutoff, "decision": decision},
    )


def _k05_evidence(ctx: FunctionContext) -> FunctionResult:
    return FunctionResult("ok", {"passages": ctx.payload.get("passages", []), "status": "stub"})


def _k06_temporal(ctx: FunctionContext) -> FunctionResult:
    return FunctionResult("ok", {"applicable": ctx.payload.get("passages", []), "status": "stub"})


def _k07_expansion(ctx: FunctionContext) -> FunctionResult:
    return FunctionResult("ok", {"vertices": ctx.payload.get("vertices", []), "status": "stub"})


def _k08_decay(ctx: FunctionContext) -> FunctionResult:
    return FunctionResult("ok", {"belief": ctx.payload.get("belief", []), "status": "stub"})


def _k09_retry(ctx: FunctionContext) -> FunctionResult:
    retries = _as_int(ctx.payload.get("retries", 0))
    if retries >= 2:
        return FunctionResult("ok", {"action": "terminal", "reason": "retry_budget_exhausted"})
    return FunctionResult("ok", {"action": "terminal", "reason": "phase1_stub"})


def _k10_hybrid_triage(ctx: FunctionContext) -> FunctionResult:
    d_score = max(0, min(3, _as_int(ctx.payload.get("d", 0))))
    r_score = max(0, min(3, _as_int(ctx.payload.get("r", 0))))
    m_score = max(0, min(3, _as_int(ctx.payload.get("m", 0))))
    has_axis7 = bool(ctx.payload.get("has_axis7", False))
    b_flag = 1 if bool(ctx.payload.get("binding", False)) or r_score >= 2 else 0
    z_flag = 1 if bool(ctx.payload.get("z_hit", False)) else 0
    s_score = d_score + r_score + m_score
    s_eff = max(s_score, 3 * b_flag, 6 * z_flag)

    if s_eff >= 6:
        tier = 3
        starting_hops = 2
        max_calls = 18
        max_calls_esc = 18
        if b_flag or z_flag:
            roles = ["scholar", "practitioner", "regulator", "harmonizer"]
        else:
            roles = ["scholar", "practitioner"]
            if r_score >= 1:
                roles.append("regulator")
            if has_axis7:
                roles.append("harmonizer")
    elif s_eff >= 3:
        tier = 2
        starting_hops = 2
        max_calls = 18
        max_calls_esc = 22
        roles = ["scholar", "practitioner"]
        if b_flag:
            roles.append("regulator")
        if has_axis7:
            roles.append("harmonizer")
    else:
        tier = 1
        starting_hops = 1
        max_calls = 9
        max_calls_esc = 21
        roles = ["scholar"]
        if b_flag:
            roles.append("regulator")

    output: dict[str, object] = {
        "s": s_score,
        "b": b_flag,
        "z": z_flag,
        "s_eff": s_eff,
        "tier": tier,
        "active_roles": roles,
        "starting_hops": starting_hops,
        "max_model_calls": max_calls,
        "max_model_calls_escalated": max_calls_esc,
    }
    raw_evidence = ctx.payload.get("evidence")
    if isinstance(raw_evidence, Mapping):
        output["evidence"] = dict(raw_evidence)

    return FunctionResult("ok", output)


def _k12_ledger_merge(ctx: FunctionContext) -> FunctionResult:
    """Enforce verifier-only closure and preserve open blocking objections across escalations."""
    raw_prior = ctx.payload.get("existing_objections", [])
    raw_new = ctx.payload.get("new_objections", [])
    merged_by_id: dict[str, dict[str, object]] = {}

    if isinstance(raw_prior, list):
        for item in raw_prior:
            if isinstance(item, Mapping) and isinstance(item.get("objection_id"), str):
                copied = copy.deepcopy({str(k): v for k, v in item.items()})
                merged_by_id[
                    copied["objection_id"] if isinstance(copied["objection_id"], str) else ""
                ] = copied

    if isinstance(raw_new, list):
        for item in raw_new:
            if not isinstance(item, Mapping) or not isinstance(item.get("objection_id"), str):
                continue
            oid = item["objection_id"]
            evidence = item.get("closure_evidence")
            has_evidence = isinstance(evidence, list) and len(evidence) > 0
            verifier_closed = bool(item.get("verifier_closed", False))

            if oid not in merged_by_id:
                normalized = copy.deepcopy({str(k): v for k, v in item.items()})
                normalized.pop("verifier_closed", None)
                # T13/T16: blocking objection first seen closed stays open unless verified.
                if bool(normalized.get("blocking", True)) and (
                    normalized.get("state") == "closed" and not (verifier_closed and has_evidence)
                ):
                    normalized["state"] = "open"
                    normalized["closure_evidence"] = []
                elif "closure_evidence" not in normalized:
                    normalized["closure_evidence"] = []
                merged_by_id[oid] = normalized
            else:
                existing = merged_by_id[oid]
                if item.get("state") == "closed" and verifier_closed and has_evidence:
                    existing["state"] = "closed"
                    existing["closure_evidence"] = (
                        list(evidence) if isinstance(evidence, list) else []
                    )

    merged = list(merged_by_id.values())
    open_blocking = [
        o for o in merged if bool(o.get("blocking", False)) and o.get("state") == "open"
    ]
    return FunctionResult(
        "hold" if open_blocking else "ok",
        {
            "objections": merged,
            "open_blocking_count": len(open_blocking),
        },
    )


def _make_k11_disclosure(notices: NoticesConfig) -> FunctionHandler:
    by_id = {n.id: n.text for n in notices.notices}

    def _k11_disclosure(ctx: FunctionContext) -> FunctionResult:
        decision = str(ctx.payload.get("decision", "block"))
        draft_text = str(ctx.payload.get("draft_text", ""))
        drift_latched = bool(ctx.payload.get("drift_latched", False))
        profile = ctx.profile
        is_advisory = profile == "advisory"

        if decision == "block":
            hold_notice = str(
                ctx.payload.get("hold_notice")
                or "Held: hard verification gate failed or unresolved blocking objection."
            )
            return FunctionResult(
                "hold",
                {
                    "receipt_release_mode": "hard_veto_block",
                    "api_release_mode": "held",
                    "returned_text": hold_notice,
                    "response_sha256": sha256_text(hold_notice),
                },
            )

        if drift_latched or decision == "withhold_drift":
            if is_advisory:
                warning = by_id.get(
                    "NOTICE-ADV-02",
                    "Advisory: verification is being recalibrated; this answer is not certified.",
                )
                returned = f"{warning}\n\n{draft_text}" if draft_text else warning
                return FunctionResult(
                    "ok",
                    {
                        "receipt_release_mode": "annotated_release_drift_warning",
                        "api_release_mode": "released_advisory",
                        "returned_text": returned,
                        "response_sha256": sha256_text(returned),
                    },
                )
            hold_msg = by_id.get(
                "NOTICE-HOLD-05",
                "Held: verification is paused while the system is recalibrated.",
            )
            return FunctionResult(
                "hold",
                {
                    "receipt_release_mode": "review_required",
                    "api_release_mode": "held",
                    "returned_text": hold_msg,
                    "response_sha256": sha256_text(hold_msg),
                },
            )

        if decision == "abstain_or_explain":
            if is_advisory:
                adv = by_id.get(
                    "NOTICE-ADV-01",
                    "Advisory: not fully verified.",
                ).format(flagged_count=_as_int(ctx.payload.get("flagged_count", 1), 1))
                returned = f"{adv}\n\n{draft_text}" if draft_text else adv
                return FunctionResult(
                    "ok",
                    {
                        "receipt_release_mode": "annotated_release_ka39",
                        "api_release_mode": "released_advisory",
                        "returned_text": returned,
                        "response_sha256": sha256_text(returned),
                    },
                )
            abstain_msg = "Held: the answer's support did not meet the verification threshold."
            return FunctionResult(
                "hold",
                {
                    "receipt_release_mode": "abstained",
                    "api_release_mode": "held",
                    "returned_text": abstain_msg,
                    "response_sha256": sha256_text(abstain_msg),
                },
            )

        return FunctionResult(
            "ok",
            {
                "receipt_release_mode": "gate_passed",
                "api_release_mode": "released",
                "returned_text": draft_text,
                "response_sha256": sha256_text(draft_text),
            },
        )

    return _k11_disclosure


def _p07_fallback_escalation(ctx: FunctionContext) -> FunctionResult:
    has_binding = bool(ctx.payload.get("has_binding", False))
    has_regulator = bool(ctx.payload.get("has_regulator", False))
    escalated_once = bool(ctx.payload.get("escalated_once", False))
    should_escalate = has_binding and not has_regulator and not escalated_once
    return FunctionResult("ok", {"escalate": should_escalate})


def _p08_fallback_equal_split(ctx: FunctionContext) -> FunctionResult:
    roles = ctx.payload.get("roles", ["scholar"])
    budget = _as_int(ctx.payload.get("total_tokens", 1000), 1000)
    role_list = [str(r) for r in roles] if isinstance(roles, list) and roles else ["scholar"]
    per_role = budget // len(role_list)
    allocation = {r: per_role for r in role_list}
    return FunctionResult("ok", {"allocation": allocation, "strategy": "equal_split"})


def _p12_fallback_drift(ctx: FunctionContext) -> FunctionResult:
    return FunctionResult("ok", {"drift_latched": bool(ctx.payload.get("drift_latched", False))})


def register_phase1_functions(registry: FunctionRegistry, notices: NoticesConfig) -> None:
    """Register all 12 kernel host handlers and required policy fallbacks on ``registry``."""
    registry.register("DVSS-K01", _k01_validate)
    registry.register("DVSS-K02", _k02_coordinate_parse)
    registry.register("DVSS-K03", _k03_profile_match)
    registry.register("DVSS-K04", _k04_gate)
    registry.register("DVSS-K05", _k05_evidence)
    registry.register("DVSS-K06", _k06_temporal)
    registry.register("DVSS-K07", _k07_expansion)
    registry.register("DVSS-K08", _k08_decay)
    registry.register("DVSS-K09", _k09_retry)
    registry.register("DVSS-K10", _k10_hybrid_triage)
    registry.register("DVSS-K11", _make_k11_disclosure(notices))
    registry.register("DVSS-K12", _k12_ledger_merge)

    registry.register_fallback("DVSS-P07", _p07_fallback_escalation)
    registry.register_fallback("DVSS-P08", _p08_fallback_equal_split)
    registry.register_fallback("DVSS-P12", _p12_fallback_drift)


__all__ = ["register_phase1_functions"]
