"""Phase 2 end-to-end governed verify-and-gate workflow orchestrator (``H1``).

Implements FR-WF-01, FR-API-04..06, FR-VER-01..03, FR-REL-01..04, FR-RCPT-01..03,
and AGENTS.md rule 11 (fail closed with a valid signed 3.8.0 receipt on errors).
"""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from dle.config import DleConfig
from dle.edge.translator import RunRequest
from dle.errors import ModelUnavailable
from dle.host.functions import FunctionContext, FunctionRecord, FunctionRegistry
from dle.host.services.claim_extractor import ClaimExtractor
from dle.host.services.evidence import EvidenceService, RetrievedPassage
from dle.host.services.receipts import ReceiptSealer
from dle.host.services.release import (
    CalibrationArtifact,
    LedgerObjection,
    apply_disclosure,
    evaluate_compliance_veto,
    evaluate_release_gate,
    safety_policy_check,
    update_cusum_drift,
)
from dle.host.services.scorer import ScoredClaim, TerminalScore, compute_terminal_u
from dle.host.services.verifier import ClaimVerifier
from dle.models import ModelPort, ModelRegistry
from dle.observability import get_logger, sha256_text
from dle.store.repositories import OpsRepository, SessionRepository

DEFAULT_PHASE2_CALIBRATION = CalibrationArtifact(
    artifact_id="cal-phase2-dev-001",
    artifact_sha256=sha256_text("cal-phase2-dev-001"),
    n_cal=100,
    alpha=0.05,
    threshold=0.25,
    mu_0=0.05,
    drift_lambda=4.0,
    drift_delta=0.02,
)


@dataclass(frozen=True)
class GovernedRunResult:
    """Outcome of running the Phase 2 verification pipeline and receipt sealer."""

    release_mode: Literal["released", "released_advisory", "held"]
    receipt_id: str
    tier: int
    body: dict[str, object]
    notice_id: str
    hold_reason: str | None
    terminal_u: float
    receipt: dict[str, object]
    function_records: tuple[FunctionRecord, ...]


def _extract_latest_user_query(contents: Sequence[Mapping[str, object]]) -> str:
    for turn in reversed(contents):
        parts = turn.get("parts")
        if not isinstance(parts, list):
            continue
        chunks = [
            str(p["text"])
            for p in parts
            if isinstance(p, Mapping) and isinstance(p.get("text"), str) and not p.get("thought")
        ]
        if chunks:
            return "\n".join(chunks).strip()
    return ""


def _extract_writer_text(body: Mapping[str, object]) -> str:
    cands = body.get("candidates")
    if isinstance(cands, list) and cands and isinstance(cands[0], Mapping):
        content = cands[0].get("content")
        if isinstance(content, Mapping) and isinstance(content.get("parts"), list):
            texts = [
                str(p["text"])
                for p in content["parts"]
                if isinstance(p, Mapping)
                and isinstance(p.get("text"), str)
                and not p.get("thought")
            ]
            if texts:
                return "\n".join(texts)
    return ""


def _build_governed_gemini_body(
    *,
    release_mode: Literal["released", "released_advisory", "held"],
    receipt_id: str,
    tier: int,
    final_content: str,
    hold_reason: str | None,
    writer_body: Mapping[str, object] | None,
    grounding_metadata: dict[str, object] | None,
) -> dict[str, object]:
    if release_mode == "held":
        return {
            "candidates": [
                {
                    "index": 0,
                    "content": {
                        "role": "model",
                        "parts": [{"text": final_content}],
                    },
                    "finishReason": "STOP",
                }
            ],
            "dleMetadata": {
                "releaseMode": "held",
                "receiptId": receipt_id,
                "tier": tier,
                "holdReason": hold_reason or "verification_hold",
            },
        }

    out = copy.deepcopy({str(k): v for k, v in writer_body.items()}) if writer_body else {}
    cands = out.get("candidates")
    if not isinstance(cands, list) or not cands or not isinstance(cands[0], dict):
        out["candidates"] = [
            {
                "index": 0,
                "content": {"role": "model", "parts": [{"text": final_content}]},
                "finishReason": "STOP",
            }
        ]
    else:
        cand0 = cands[0]
        content = cand0.get("content")
        if isinstance(content, dict) and isinstance(content.get("parts"), list):
            parts = content["parts"]
            replaced = False
            for part in parts:
                if (
                    isinstance(part, dict)
                    and isinstance(part.get("text"), str)
                    and not part.get("thought")
                ):
                    part["text"] = final_content
                    replaced = True
                    break
            if not replaced:
                parts.insert(0, {"text": final_content})
        else:
            cand0["content"] = {"role": "model", "parts": [{"text": final_content}]}
        cand0["finishReason"] = cand0.get("finishReason") or "STOP"

    if grounding_metadata is not None:
        first_cand = out["candidates"][0]  # type: ignore[index]
        if isinstance(first_cand, dict):
            first_cand["groundingMetadata"] = grounding_metadata

    out["dleMetadata"] = {
        "releaseMode": release_mode,
        "receiptId": receipt_id,
        "tier": tier,
    }
    return out


def _record_remaining_kernel_hooks(
    *,
    registry: FunctionRegistry,
    run_id: str,
    attempt_id: str,
    profile: str,
    tier: int,
    records: list[FunctionRecord],
    overrides: Mapping[str, dict[str, object]] | None = None,
) -> None:
    seen = {rec.dvss_id for rec in records}
    defaults: dict[str, dict[str, object]] = {f"DVSS-K{i:02d}": {} for i in range(1, 13)}
    if overrides:
        for kid, payload in overrides.items():
            defaults[kid] = dict(payload)
    for kid in sorted(defaults):
        if kid in seen:
            continue
        registry.invoke(
            kid,
            FunctionContext(
                run_id=run_id,
                attempt_id=attempt_id,
                profile=profile,
                tier=tier,
                payload=defaults[kid],
            ),
            records=records,
        )


def _calibration_block(calibration: CalibrationArtifact | None) -> dict[str, object]:
    eff = calibration if calibration is not None else DEFAULT_PHASE2_CALIBRATION
    return {
        "artifact_id": eff.artifact_id,
        "artifact_sha256": eff.artifact_sha256,
        "n_cal": eff.n_cal,
        "alpha": eff.alpha,
        "threshold": eff.threshold,
        "mu_0": eff.mu_0,
        "drift_lambda": eff.drift_lambda,
        "drift_delta": eff.drift_delta,
    }


def _build_receipt_payload(
    *,
    run_id: str,
    utc_iso: str,
    attempt_id: str,
    tier: int,
    policy_sha256: str,
    profile: str,
    writer_model: str,
    writer_version: str,
    query_digest: str,
    draft_digest: str,
    passages: Sequence[RetrievedPassage],
    scored_claims: Sequence[ScoredClaim],
    objections: Sequence[LedgerObjection],
    calibration: CalibrationArtifact | None,
    hard_gate: bool,
    drift_latched: bool,
    cusum: float,
    terminal_u: float,
    receipt_release_mode: str,
    response_sha256: str,
    records: Sequence[FunctionRecord],
) -> dict[str, object]:
    role_axes: list[int] = [8]
    role_profiles: list[str] = ["scholar-default"]
    if tier >= 2 or any(c.binding for c in scored_claims):
        role_axes = [8, 9, 10]
        role_profiles = ["scholar-default", "practitioner-default", "regulator-default"]

    claim_dicts = [
        {
            "claim_id": c.claim_id,
            "proposal_id": c.proposal_id,
            "assertion": c.assertion,
            "binding": c.binding,
            "scope": c.scope_label,
            "passage_ids": list(c.passage_ids),
            "entailment": min(1.0, max(0.0, round(c.entailment, 6))),
            "provenance": min(1.0, max(0.0, round(c.provenance, 6))),
            "belief": min(1.0, max(0.0, round(c.belief, 6))),
        }
        for c in scored_claims
    ]
    obj_dicts = [
        {
            "objection_id": o.objection_id,
            "role_axis": o.role_axis,
            "proposal_id": o.proposal_id,
            "blocking": o.blocking,
            "predicate": o.predicate,
            "state": o.state,
            "closure_evidence": list(o.closure_evidence),
        }
        for o in objections
    ]
    src_dicts = [
        {
            "source_id": p.source_id,
            "revision": p.revision,
            "document_sha256": p.content_sha256,
            "passage_id": p.passage_id,
            "locator": p.locator,
            "passage_sha256": p.content_sha256,
            "scope": p.jurisdiction or "general",
            "access_policy": "tenant",
            "retrieved_utc": p.retrieved_utc,
        }
        for p in passages
    ]
    source_manifest = sha256_text("|".join(sorted(p.passage_id for p in passages)))
    return {
        "schema_version": "3.8.0",
        "run_id": run_id,
        "utc": utc_iso,
        "chain_id": "main",
        "previous_hash": "GENESIS",
        "coordinate_manifest_sha256": sha256_text("phase2-coordinate-manifest"),
        "policy_sha256": policy_sha256,
        "verifier_version": "0.1.0",
        "attempts": [
            {
                "attempt_id": attempt_id,
                "parent_id": None,
                "event": "initial",
                "reason": f"tier_{tier}_phase2_verify",
                "tier": tier,
                "hops": 1 if tier == 1 else 2,
                "ppr_iterations": 0,
                "vertices_retained": len(passages),
                "graph_sha256": sha256_text("phase2-hybrid-retrieval"),
                "source_manifest_sha256": source_manifest,
                "role_calls": [
                    {
                        "role_axes": role_axes,
                        "profile_ids": role_profiles,
                        "input_sha256": query_digest,
                        "output_sha256": draft_digest,
                        "model_id": writer_model,
                        "model_version": writer_version or f"{writer_model}-001",
                        "temperature": 0.0,
                        "top_p": 1.0,
                        "seed": None,
                    }
                ],
                "claims": claim_dicts,
                "objections": obj_dicts,
                "candidate_sha256": response_sha256,
            }
        ],
        "sources": src_dicts,
        "calibration": _calibration_block(calibration),
        "decision": {
            "hard_gate": hard_gate,
            "drift_latched": drift_latched,
            "cusum": round(max(0.0, cusum), 6),
            "terminal_u": round(min(1.0, max(0.0, terminal_u)), 6),
            "terminal_attempt_id": attempt_id,
            "release_mode": receipt_release_mode,
            "profile": profile,
        },
        "response_sha256": response_sha256,
        "profile": profile,
        "function_invocations": [r.to_receipt_dict() for r in records],
    }


def seal_cancelled_receipt(
    *,
    run_req: RunRequest,
    config: DleConfig,
    function_registry: FunctionRegistry,
    model_registry: ModelRegistry,
    receipt_sealer: ReceiptSealer,
    calibration: CalibrationArtifact | None = None,
) -> dict[str, object]:
    """Seal an append-only 3.8.0 receipt with ``release_mode='cancelled'`` (GC-25)."""
    profile = run_req.profile or "strict"
    records: list[FunctionRecord] = []
    _record_remaining_kernel_hooks(
        registry=function_registry,
        run_id=run_req.run_id,
        attempt_id="att-0",
        profile=profile,
        tier=1,
        records=records,
    )
    utc_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    empty_sha = sha256_text("")
    writer_model = model_registry.pin_for_job("writer")
    payload = _build_receipt_payload(
        run_id=run_req.run_id,
        utc_iso=utc_iso,
        attempt_id="att-0",
        tier=1,
        policy_sha256=config.policy_sha256,
        profile=profile,
        writer_model=writer_model,
        writer_version=f"{writer_model}-001",
        query_digest=sha256_text(_extract_latest_user_query(run_req.contents)),
        draft_digest=empty_sha,
        passages=(),
        scored_claims=(),
        objections=(),
        calibration=calibration,
        hard_gate=False,
        drift_latched=model_registry.drift_latched,
        cusum=0.0,
        terminal_u=1.0,
        receipt_release_mode="cancelled",
        response_sha256=empty_sha,
        records=records,
    )
    return receipt_sealer.seal_receipt(payload=payload, api_release_mode="cancelled")


async def run_governed_phase2(
    *,
    run_req: RunRequest,
    config: DleConfig,
    function_registry: FunctionRegistry,
    model_registry: ModelRegistry,
    model_port: ModelPort,
    evidence_service: EvidenceService,
    claim_extractor: ClaimExtractor,
    claim_verifier: ClaimVerifier,
    receipt_sealer: ReceiptSealer,
    ops_repo: OpsRepository,
    session_repo: SessionRepository,
    calibration: CalibrationArtifact | None,
    api_key: str,
) -> GovernedRunResult:
    """Execute the full Phase 2 verification, gate, disclosure, and sealing workflow."""
    log = get_logger("dle.host.workflow.governed")
    start_clock = time.perf_counter()
    profile = run_req.profile or "strict"
    attempt_id = "att-0"
    proposal_id = "p0"
    records: list[FunctionRecord] = []
    query_str = _extract_latest_user_query(run_req.contents)
    query_digest = sha256_text(query_str)
    writer_model = model_registry.pin_for_job("writer")
    utc_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        k01_res = function_registry.invoke(
            "DVSS-K01",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id=attempt_id,
                profile=profile,
                payload={"model": run_req.model, "turn_count": len(run_req.contents)},
            ),
            records=records,
        )
        if k01_res.outcome != "ok":
            raise ValueError("DVSS-K01 request validation rejected governed payload")

        input_safety = safety_policy_check(input_content=query_str, proposal_id=proposal_id)
        k10_res = function_registry.invoke(
            "DVSS-K10",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id=attempt_id,
                profile=profile,
                payload={"d": 0, "r": 0, "m": 0, "binding": False, "z_hit": False},
            ),
            records=records,
        )
        raw_tier = k10_res.output.get("tier", 1)
        tier = int(raw_tier) if isinstance(raw_tier, int | float) else 1

        # Acquire relevant evidence passages first (DVSS-K05 / K06).
        retrieval = await evidence_service.retrieve(
            query=query_str or "warehouse substitution policy",
            limit=8,
            idempotency_key=f"{run_req.run_id}:{attempt_id}",
            api_key=api_key,
        )
        function_registry.invoke(
            "DVSS-K05",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id=attempt_id,
                profile=profile,
                tier=tier,
                payload={"passage_count": len(retrieval.passages)},
            ),
            records=records,
        )
        function_registry.invoke(
            "DVSS-K06",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id=attempt_id,
                profile=profile,
                tier=tier,
                payload={"excluded_count": len(retrieval.excluded_temporal)},
            ),
            records=records,
        )

        # Generate draft answer via pinned writer model.
        call_t0 = time.perf_counter()
        writer_res = await model_port.generate(
            writer_model,
            run_req.raw_body,
            api_key=api_key,
            job="writer",
        )
        call_ms = (time.perf_counter() - call_t0) * 1000.0
        usage = writer_res.body.get("usageMetadata")
        in_tok = int(str(usage.get("promptTokenCount", 0))) if isinstance(usage, Mapping) else 0
        out_tok = (
            int(str(usage.get("candidatesTokenCount", 0))) if isinstance(usage, Mapping) else 0
        )
        writer_ver = writer_res.model_version or str(
            writer_res.body.get("modelVersion", f"{writer_model}-001")
        )
        ops_repo.record_model_call(
            call_id=str(uuid.uuid4()),
            run_id=run_req.run_id,
            job="writer",
            model_id=writer_model,
            model_version=writer_ver,
            input_tokens=in_tok,
            output_tokens=out_tok,
            thought_tokens=0,
            cost_usd=0.0,
            duration_ms=round(call_ms, 3),
            attempts=writer_res.attempts,
            status="ok",
            called_utc=utc_iso,
        )

        draft_str = _extract_writer_text(writer_res.body)
        draft_digest = sha256_text(draft_str)

        # H10 claim extraction -> H12 verification & groundingMetadata -> P04 contradictions.
        extraction = await claim_extractor.extract(
            run_id=run_req.run_id,
            attempt_id=attempt_id,
            proposal_id=proposal_id,
            draft_text=draft_str,
            api_key=api_key,
        )
        verification = claim_verifier.verify(
            claims=extraction.claims,
            passages=retrieval.passages,
            draft_text=draft_str,
        )
        function_registry.invoke(
            "DVSS-K08",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id=attempt_id,
                profile=profile,
                tier=tier,
                payload={"belief": [c.belief for c in verification.scored_claims]},
            ),
            records=records,
        )

        output_safety = safety_policy_check(output_content=draft_str, proposal_id=proposal_id)
        span_objections = [
            LedgerObjection(
                objection_id=str(so["objection_id"]),
                role_axis=10,
                proposal_id=proposal_id,
                blocking=True,
                predicate=str(so["predicate"]),
                state="open",
            )
            for so in extraction.span_objections
        ]
        contra_objections = [
            LedgerObjection(
                objection_id=f"contra-{idx}",
                role_axis=10,
                proposal_id=proposal_id,
                blocking=True,
                predicate=c.reason,
                state="open",
            )
            for idx, c in enumerate(verification.contradictions, start=1)
        ]
        all_objections = [*input_safety, *output_safety, *span_objections, *contra_objections]
        for obj in all_objections:
            session_repo.append_ledger_entry(
                run_id=run_req.run_id,
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

        norm_objections, open_blocking = evaluate_compliance_veto(all_objections)
        function_registry.invoke(
            "DVSS-K12",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id=attempt_id,
                profile=profile,
                tier=tier,
                payload={
                    "existing_objections": [
                        {
                            "objection_id": o.objection_id,
                            "blocking": o.blocking,
                            "state": o.state,
                            "closure_evidence": list(o.closure_evidence),
                        }
                        for o in norm_objections
                    ]
                },
            ),
            records=records,
        )

        term_score: TerminalScore = compute_terminal_u(
            verification.scored_claims,
            open_objections=len(open_blocking),
            total_objections=len(norm_objections),
        )
        prior_drift = ops_repo.get_drift_state()
        prev_c = float(str(prior_drift["c_t"])) if prior_drift is not None else 0.0
        prev_latched = bool(prior_drift["is_latched"]) if prior_drift is not None else False
        eff_cal = calibration if calibration is not None else DEFAULT_PHASE2_CALIBRATION
        cusum_c, drift_latched, _reason = update_cusum_drift(
            previous_c_t=prev_c,
            u_t=term_score.u,
            calibration=eff_cal,
            previous_latched=prev_latched or model_registry.drift_latched,
            ops_repo=ops_repo,
        )

        gate = evaluate_release_gate(
            schema_scope_valid=True,
            claims=verification.scored_claims,
            all_binding_verified=verification.all_binding_verified,
            open_blocking_objections=open_blocking,
            score=term_score,
            calibration=calibration,
            drift_latched=drift_latched,
            cusum=cusum_c,
        )
        function_registry.invoke(
            "DVSS-K04",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id=attempt_id,
                profile=profile,
                tier=tier,
                payload={
                    "hard_gate": gate.hard_gate,
                    "u": gate.u,
                    "cutoff": gate.cutoff,
                    "drift_latched": gate.drift_latched,
                },
            ),
            records=records,
        )

        flagged_count = sum(1 for c in verification.scored_claims if c.support_z < 0.70)
        weakest_text = ""
        if term_score.weakest_claim_id:
            weak_hit = next(
                (
                    c
                    for c in verification.scored_claims
                    if c.claim_id == term_score.weakest_claim_id
                ),
                None,
            )
            weakest_text = weak_hit.assertion[:80] if weak_hit is not None else ""

        disclosure = apply_disclosure(
            gate=gate,
            profile=profile,
            draft_text=draft_str,
            notices=config.notices,
            receipt_id=run_req.run_id,
            source_count=len(retrieval.passages),
            flagged_count=max(1, flagged_count),
            weakest_claim_summary=weakest_text or "unsupported assertion",
            objection_predicate=open_blocking[0].predicate if open_blocking else "compliance",
        )
        function_registry.invoke(
            "DVSS-K11",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id=attempt_id,
                profile=profile,
                tier=tier,
                payload={
                    "decision": gate.decision,
                    "draft_text": draft_str,
                    "drift_latched": drift_latched,
                    "flagged_count": max(1, flagged_count),
                    "hold_notice": disclosure.final_text
                    if disclosure.api_release_mode == "held"
                    else None,
                },
            ),
            records=records,
        )

        # Ensure all 12 kernel bindings appear in receipt.function_invocations.
        _record_remaining_kernel_hooks(
            registry=function_registry,
            run_id=run_req.run_id,
            attempt_id=attempt_id,
            profile=profile,
            tier=tier,
            records=records,
        )

        response_body = _build_governed_gemini_body(
            release_mode=disclosure.api_release_mode,
            receipt_id=run_req.run_id,
            tier=tier,
            final_content=disclosure.final_text,
            hold_reason=gate.block_reason if disclosure.api_release_mode == "held" else None,
            writer_body=writer_res.body,
            grounding_metadata=verification.grounding_metadata,
        )

        receipt_payload = _build_receipt_payload(
            run_id=run_req.run_id,
            utc_iso=utc_iso,
            attempt_id=attempt_id,
            tier=tier,
            policy_sha256=config.policy_sha256,
            profile=profile,
            writer_model=writer_model,
            writer_version=writer_ver,
            query_digest=query_digest,
            draft_digest=draft_digest,
            passages=retrieval.passages,
            scored_claims=verification.scored_claims,
            objections=norm_objections,
            calibration=calibration,
            hard_gate=gate.hard_gate,
            drift_latched=gate.drift_latched,
            cusum=cusum_c,
            terminal_u=term_score.u,
            receipt_release_mode=disclosure.receipt_release_mode,
            response_sha256=disclosure.response_sha256,
            records=records,
        )
        sealed = receipt_sealer.seal_receipt(
            payload=receipt_payload,
            api_release_mode=disclosure.api_release_mode,
        )
        ops_repo.record_run_metrics(
            run_id=run_req.run_id,
            tier=tier,
            profile=profile,
            release_mode=disclosure.api_release_mode,
            retries=0,
            escalated=False,
            u=term_score.u,
            duration_ms=round((time.perf_counter() - start_clock) * 1000.0, 3),
            cost_usd=0.0,
            finished_utc=utc_iso,
        )
        return GovernedRunResult(
            release_mode=disclosure.api_release_mode,
            receipt_id=run_req.run_id,
            tier=tier,
            body=response_body,
            notice_id=disclosure.notice_id,
            hold_reason=gate.block_reason if disclosure.api_release_mode == "held" else None,
            terminal_u=term_score.u,
            receipt=sealed,
            function_records=tuple(records),
        )
    except ModelUnavailable:
        hold_notice_id = "NOTICE-HOLD-06"
        hold_reason = "model_unavailable"
        log.warning("workflow.phase2_model_unavailable", run_id=run_req.run_id)
    except Exception as exc:
        hold_notice_id = "NOTICE-HOLD-07"
        hold_reason = "internal_error"
        log.error(
            "workflow.phase2_internal_error",
            run_id=run_req.run_id,
            error_type=type(exc).__name__,
        )

    # Fail closed AND still record a signed 3.8.0 hard_veto_block receipt.
    hold_notice = next(
        (n.text for n in config.notices.notices if n.id == hold_notice_id),
        "Held: verification could not complete.",
    ).format(receipt_id=run_req.run_id)
    _record_remaining_kernel_hooks(
        registry=function_registry,
        run_id=run_req.run_id,
        attempt_id=attempt_id,
        profile=profile,
        tier=1,
        records=records,
        overrides={
            "DVSS-K04": {"hard_gate": False, "u": 1.0, "cutoff": 0.0, "drift_latched": False},
            "DVSS-K11": {"decision": "block", "hold_notice": hold_notice},
        },
    )
    resp_sha = sha256_text(hold_notice)
    fail_payload = _build_receipt_payload(
        run_id=run_req.run_id,
        utc_iso=utc_iso,
        attempt_id=attempt_id,
        tier=1,
        policy_sha256=config.policy_sha256,
        profile=profile,
        writer_model=writer_model,
        writer_version=f"{writer_model}-001",
        query_digest=query_digest,
        draft_digest=resp_sha,
        passages=(),
        scored_claims=(),
        objections=(),
        calibration=calibration,
        hard_gate=False,
        drift_latched=model_registry.drift_latched,
        cusum=0.0,
        terminal_u=1.0,
        receipt_release_mode="hard_veto_block",
        response_sha256=resp_sha,
        records=records,
    )
    sealed_fail = receipt_sealer.seal_receipt(payload=fail_payload, api_release_mode="held")
    fail_body = _build_governed_gemini_body(
        release_mode="held",
        receipt_id=run_req.run_id,
        tier=1,
        final_content=hold_notice,
        hold_reason=hold_reason,
        writer_body=None,
        grounding_metadata=None,
    )
    return GovernedRunResult(
        release_mode="held",
        receipt_id=run_req.run_id,
        tier=1,
        body=fail_body,
        notice_id=hold_notice_id,
        hold_reason=hold_reason,
        terminal_u=1.0,
        receipt=sealed_fail,
        function_records=tuple(records),
    )


__all__ = [
    "DEFAULT_PHASE2_CALIBRATION",
    "GovernedRunResult",
    "run_governed_phase2",
    "seal_cancelled_receipt",
]
