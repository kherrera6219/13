"""End-to-end 12-step governed FROST orchestrator and receipt workflow (``H1``).

Implements FR-WF-01..07, FR-FL-01..07, FR-QP-01..08, FR-TOOL-02..05,
FR-API-04..06, FR-VER-01..03, FR-REL-01..04, FR-RCPT-01..03, and AGENTS.md
rule 11 (fail closed with a valid signed 3.8.0 receipt on errors).
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from dle.config import DleConfig
from dle.config.models import FunctionFlagsConfig
from dle.edge.sessions import session_id_after_response
from dle.edge.tools import ToolBridge, extract_function_calls, extract_model_content
from dle.edge.translator import RunRequest
from dle.errors import ModelUnavailable
from dle.host.frost import FrostTrace
from dle.host.functions import FunctionContext, FunctionRecord, FunctionRegistry
from dle.host.services.claim_extractor import ClaimExtractor
from dle.host.services.coordinate import (
    CoordinateParseResult,
    evaluate_temporal_applicability,
    parse_coordinate,
    propose_anchors_from_query,
    resolve_jurisdiction_precedence,
)
from dle.host.services.evidence import EvidenceService, RetrievalResult, RetrievedPassage
from dle.host.services.graph import (
    GraphExpansionResult,
    align_crosswalk_terms,
    expand_bounded_ppr,
)
from dle.host.services.intake import (
    IntakeDecision,
    IntakeRouter,
    ModelCallBudget,
    safe_compute_cost,
)
from dle.host.services.ledger import LedgerService
from dle.host.services.overlay import SessionOverlay
from dle.host.services.pareto import (
    CandidateOption,
    ParetoObjective,
    filter_pareto_options,
)
from dle.host.services.personas import (
    AXIS_FOR_ROLE,
    ROLE_FOR_AXIS,
    ProfileCandidate,
    RoleCallOutcome,
    allocate_role_tokens,
    build_persona_profile,
    build_role_packet,
    compute_role_ppr_mass,
    execute_role_call,
    match_profiles,
    order_role_execution,
)
from dle.host.services.policy_control import (
    ConsequentialToolHit,
    RetryPolicyInput,
    check_consequential_functions,
    decide_retry_policy,
    evaluate_binding_escalation,
)
from dle.host.services.receipts import ReceiptSealer
from dle.host.services.reference import ReferenceCatalog
from dle.host.services.registry import RegistrySnapshot
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
from dle.host.services.writer import RoleFinding, WriterService
from dle.models import ModelPort, ModelRegistry
from dle.observability import get_logger, sha256_text
from dle.store.repositories import OpsRepository, RegistryRepository, SessionRepository

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
    """Outcome of executing the 12-step governed FROST orchestrator and sealer."""

    release_mode: Literal["released", "released_advisory", "held", "passthrough"]
    receipt_id: str
    tier: int
    body: dict[str, object]
    notice_id: str
    hold_reason: str | None
    terminal_u: float
    receipt: dict[str, object]
    function_records: tuple[FunctionRecord, ...]
    retries: int = 0
    escalated: bool = False
    steps: tuple[dict[str, object], ...] = ()
    personas: tuple[dict[str, object], ...] = ()


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


def _has_client_function_declarations(run_req: RunRequest) -> bool:
    raw_fc = run_req.raw_body.get("toolConfig")
    if isinstance(raw_fc, Mapping):
        fc_cfg = raw_fc.get("functionCallingConfig")
        if isinstance(fc_cfg, Mapping) and fc_cfg.get("mode") == "NONE":
            return False
    for t in run_req.tools:
        decls = t.get("functionDeclarations")
        if isinstance(decls, list) and len(decls) > 0:
            return True
    return False


def _extract_tool_passages(
    contents: Sequence[Mapping[str, object]],
    *,
    utc_iso: str,
) -> tuple[RetrievedPassage, ...]:
    out: list[RetrievedPassage] = []
    idx = 0
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
            idx += 1
            fn_name = str(fr.get("name", "tool")).strip() or "tool"
            resp_obj = fr.get("response", {})
            if isinstance(resp_obj, Mapping) and isinstance(resp_obj.get("result"), str):
                body_str = str(resp_obj["result"]).strip()
            else:
                body_str = json.dumps(resp_obj, sort_keys=True)
            if not body_str:
                continue
            out.append(
                RetrievedPassage(
                    f"app_tool:{fn_name}@1#call_{idx}",
                    f"app_tool:{fn_name}",
                    f"Client Tool Response ({fn_name})",
                    "app_tool",
                    "1",
                    f"call_{idx}",
                    sha256_text(body_str),
                    body_str,
                    None,
                    None,
                    None,
                    False,
                    utc_iso,
                    0.90,
                    True,
                )
            )
    return tuple(out)


def _build_coordinate_metadata(
    coord_res: CoordinateParseResult,
    *,
    manifest_sha256: str,
) -> dict[str, object]:
    atoms_by_axis: dict[str, list[str]] = {}
    for key, value in coord_res.coordinate.items():
        if key.startswith("axis_") and key != "axis_13_temporal" and isinstance(value, list):
            atoms = [
                str(item["canonical_str"])
                for item in value
                if isinstance(item, Mapping) and isinstance(item.get("canonical_str"), str)
            ]
            if atoms:
                atoms_by_axis[key] = atoms
    return {
        "manifestSha256": manifest_sha256,
        "jurisdictionState": coord_res.coordinate.get("jurisdiction_state", "unscoped"),
        "activeAxes": list(coord_res.active_axes),
        "activatedRoles": list(coord_res.activated_roles),
        "atomsByAxis": atoms_by_axis,
    }


def _build_graph_metadata(
    *,
    ppr_enabled: bool,
    hops: int,
    ppr_res: GraphExpansionResult | None,
    graph_sha256: str,
    vertices_retained: int,
) -> dict[str, object]:
    if ppr_res is None:
        return {
            "pprEnabled": ppr_enabled,
            "hops": hops,
            "pprIterations": 0,
            "verticesRetained": vertices_retained,
            "graphSha256": graph_sha256,
            "nodes": [],
            "edges": [],
        }
    return {
        "pprEnabled": ppr_enabled,
        "hops": ppr_res.effective_hops,
        "pprIterations": ppr_res.ppr_iterations,
        "verticesRetained": len(ppr_res.vertices),
        "graphSha256": ppr_res.graph_sha256,
        "nodes": [
            {
                "vertexId": v.vertex_id,
                "axisId": v.axis_id,
                "score": round(v.score, 6),
                "hop": v.hop,
                "synthetic": v.synthetic,
            }
            for v in ppr_res.vertices[:12]
        ],
        "edges": [
            {
                "src": e.src,
                "dst": e.dst,
                "edgeType": e.edge_type,
                "weight": round(e.weight, 4),
            }
            for e in ppr_res.edges[:20]
        ],
    }


def _build_governed_gemini_body(
    *,
    release_mode: Literal["released", "released_advisory", "held"],
    receipt_id: str,
    tier: int,
    final_content: str,
    hold_reason: str | None,
    writer_body: Mapping[str, object] | None,
    grounding_metadata: dict[str, object] | None,
    extra_dle_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if release_mode == "held":
        dle_meta: dict[str, object] = {
            "releaseMode": "held",
            "receiptId": receipt_id,
            "tier": tier,
            "holdReason": hold_reason or "verification_hold",
        }
        if extra_dle_metadata:
            dle_meta.update(extra_dle_metadata)
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
            "dleMetadata": dle_meta,
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

    rel_meta: dict[str, object] = {
        "releaseMode": release_mode,
        "receiptId": receipt_id,
        "tier": tier,
    }
    if extra_dle_metadata:
        rel_meta.update(extra_dle_metadata)
    out["dleMetadata"] = rel_meta
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


def _canonical_atoms(coord_res: CoordinateParseResult | None, key: str) -> list[str]:
    if coord_res is None:
        return []
    raw = coord_res.coordinate.get(key)
    if not isinstance(raw, list):
        return []
    return [
        str(item["canonical_str"])
        for item in raw
        if isinstance(item, Mapping) and isinstance(item.get("canonical_str"), str)
    ]


def _passage_dicts(passages: Sequence[RetrievedPassage]) -> list[dict[str, object]]:
    return [
        {
            "passage_id": p.passage_id,
            "content_str": p.text,
            "source_id": p.source_id,
            "authority_class": p.authority_class,
        }
        for p in passages
    ]


def _role_input_atoms_map(
    coord_res: CoordinateParseResult | None,
) -> dict[str, list[str]]:
    return {
        "scholar": _canonical_atoms(coord_res, "axis_1_pillars") or ["[PL:1.1.0.0]"],
        "practitioner": (
            _canonical_atoms(coord_res, "axis_2_sectors")
            + _canonical_atoms(coord_res, "axis_5_nodes")
        ),
        "regulator": _canonical_atoms(coord_res, "axis_6_octopus"),
        "harmonizer": _canonical_atoms(coord_res, "axis_7_spiderweb"),
    }


def _select_role_profile(
    *,
    role_name: str,
    run_id: str,
    tier: int,
    coord_res: CoordinateParseResult | None,
    snapshot: RegistrySnapshot | None,
    reference_catalog: ReferenceCatalog | None,
    registry_repo: RegistryRepository | None,
    p10_enabled: bool,
) -> tuple[dict[str, object], float, bool, bool]:
    axis = AXIS_FOR_ROLE[role_name]
    if snapshot is None:
        fallback_doc: dict[str, object] = {
            "profile_id": f"[ROLE:{axis}.1]",
            "axis": axis,
            "role_name": ROLE_FOR_AXIS[axis],
            "mandate": f"Execute governed {ROLE_FOR_AXIS[axis]} check.",
            "prohibited_decisions": ["unauthorized_release"],
            "visibility_policy": "sealed_packet",
            "low_fit": True,
        }
        return fallback_doc, 0.0, True, False

    pillars = _canonical_atoms(coord_res, "axis_1_pillars")
    branches = _canonical_atoms(coord_res, "axis_4_branches")
    links = _canonical_atoms(coord_res, "axis_3_honeycomb")
    sectors = _canonical_atoms(coord_res, "axis_2_sectors")
    nodes = _canonical_atoms(coord_res, "axis_5_nodes")
    hubs = _canonical_atoms(coord_res, "axis_6_octopus")
    meshes = _canonical_atoms(coord_res, "axis_7_spiderweb")
    jurs = _canonical_atoms(coord_res, "axis_12_jurisdiction")
    jur = jurs[0] if jurs else None
    hub_arms: list[str] = []
    for hid in hubs:
        rec = snapshot.hubs.get(hid)
        arms = rec.get("arms", []) if isinstance(rec, Mapping) else []
        if isinstance(arms, list):
            for arm in arms:
                if isinstance(arm, Mapping) and isinstance(arm.get("arm_id"), str):
                    hub_arms.append(f"{hid}#{arm['arm_id']}")

    built = build_persona_profile(
        role_axis=axis,
        snapshot=snapshot,
        run_id=run_id,
        pillars=pillars,
        branches=branches,
        links=links,
        sectors=sectors,
        nodes=nodes,
        hubs=hubs,
        hub_arms=hub_arms,
        meshes=meshes,
        jurisdiction=jur,
        reference_catalog=reference_catalog,
        repository=registry_repo,
    )
    candidates: list[ProfileCandidate] = []
    if built is not None:
        candidates.append(
            ProfileCandidate(
                profile_id=str(built["profile_id"]),
                role_axis=axis,
                mandatory_met=True,
                direct_e=1.0,
                direct_c=0.5,
                direct_x=0.8,
                matched_credentials=1,
                sector_lineage_match=1.0,
                profile_doc=built,
            )
        )
    sel = match_profiles(
        role_axis=axis,
        candidates=candidates,
        tier=tier,
        p10_enabled=p10_enabled,
    )
    doc = dict(sel.selected_profile) if sel.selected_profile is not None else {}
    doc.setdefault("profile_id", sel.selected_profile_id)
    doc.setdefault("axis", axis)
    doc.setdefault("role_name", ROLE_FOR_AXIS[axis])
    return doc, sel.m_score, sel.low_fit, sel.harmonizer_low_fit_objection


async def _execute_deliberation_round(
    *,
    run_id: str,
    attempt_id: str,
    tier: int,
    active_roles: Sequence[str],
    query_str: str,
    proposal_id: str,
    passages: Sequence[RetrievedPassage],
    ledger: LedgerService,
    coord_res: CoordinateParseResult | None,
    ppr_res: GraphExpansionResult | None,
    snapshot: RegistrySnapshot | None,
    config: DleConfig,
    function_registry: FunctionRegistry,
    model_registry: ModelRegistry,
    model_port: ModelPort,
    ops_repo: OpsRepository,
    registry_repo: RegistryRepository | None,
    reference_catalog: ReferenceCatalog | None,
    profile_name: str,
    blinded: bool,
    api_key: str,
    utc_iso: str,
    records: list[FunctionRecord],
) -> tuple[
    list[RoleCallOutcome],
    list[RoleFinding],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    bool,
    int,
    float,
]:
    profile_cfg = config.profiles.get(profile_name)
    toggles = profile_cfg.policy_functions if profile_cfg is not None else {}
    p08_on = toggles.get("DVSS-P08", "on") != "off"
    p10_on = toggles.get("DVSS-P10", "on") != "off"
    p11_toggle = toggles.get("DVSS-P11", "tier3")
    p11_on = p11_toggle == "on" or (p11_toggle == "tier3" and tier >= 3)

    mass_map = compute_role_ppr_mass(ppr_res, _role_input_atoms_map(coord_res))
    budget_res = allocate_role_tokens(
        active_roles=active_roles,
        total_tokens=1200,
        ppr_mass_by_role=mass_map,
        p08_enabled=p08_on,
    )
    function_registry.invoke(
        "DVSS-P08",
        FunctionContext(
            run_id=run_id,
            attempt_id=attempt_id,
            profile=profile_name,
            tier=tier,
            payload={
                "roles": list(active_roles),
                "total_tokens": 1200,
                "allocation": dict(budget_res.allocation),
                "strategy": budget_res.strategy,
            },
        ),
        records=records,
    )

    personas_model = model_registry.pin_for_job("personas")
    waves = order_role_execution(active_roles, blinded_assurance_roles=blinded)
    passage_payloads = _passage_dicts(passages)
    carry_objs = ledger.carry_forward_snapshot(run_id)

    outcomes: list[RoleCallOutcome] = []
    findings: list[RoleFinding] = []
    role_call_entries: list[dict[str, object]] = []
    raw_role_objs: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    low_fit_objection = False
    selected_profile_ids: list[str] = []
    p_scores: dict[str, float] = {}
    round_calls = 0
    round_cost_usd = 0.0

    for wave in waves:
        for role_name in wave:
            axis = AXIS_FOR_ROLE[role_name]
            prof_doc, m_score, low_fit, harm_obj = _select_role_profile(
                role_name=role_name,
                run_id=run_id,
                tier=tier,
                coord_res=coord_res,
                snapshot=snapshot,
                reference_catalog=reference_catalog,
                registry_repo=registry_repo,
                p10_enabled=p10_on,
            )
            if harm_obj:
                low_fit_objection = True
            pid = str(prof_doc.get("profile_id", f"[ROLE:{axis}.1]"))
            selected_profile_ids.append(pid)
            p_scores[role_name] = m_score

            is_blinded_call = blinded and axis in (10, 11)
            token_budget = budget_res.allocation.get(role_name, 300)
            packet = build_role_packet(
                role_axis=axis,
                question=query_str or "Evaluate proposal against evidence.",
                proposal_id=proposal_id,
                proposal_summary=(query_str or "Evaluate proposal")[:160],
                profile=prof_doc,
                conduct_config=config.conduct,
                passages=passage_payloads,
                open_objections=carry_objs,
                token_budget=token_budget,
                tier=tier,
                p11_enabled=p11_on,
                blinded=is_blinded_call,
            )

            call_t0 = time.perf_counter()
            outcome = await execute_role_call(
                packet=packet,
                model_port=model_port,
                model_id=personas_model,
                api_key=api_key,
            )
            call_ms = (time.perf_counter() - call_t0) * 1000.0
            call_cost = safe_compute_cost(
                model_registry,
                outcome.model_id,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                model_version=outcome.model_version,
            )
            round_calls += 1
            round_cost_usd += call_cost
            ops_repo.record_model_call(
                call_id=str(uuid.uuid4()),
                run_id=run_id,
                job="personas",
                model_id=outcome.model_id,
                model_version=outcome.model_version,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                thought_tokens=0,
                cost_usd=call_cost,
                duration_ms=round(call_ms, 3),
                attempts=outcome.attempts,
                status="ok" if outcome.valid else "failed",
                called_utc=utc_iso,
            )
            outcomes.append(outcome)

            raw_claims = outcome.artifact.get("claims", [])
            claims_list = raw_claims if isinstance(raw_claims, list) else []
            for cl in claims_list:
                if not isinstance(cl, Mapping):
                    continue
                pids = cl.get("passage_ids", [])
                findings.append(
                    RoleFinding(
                        role_axis=axis,
                        role_name=outcome.role_name,
                        profile_id=outcome.profile_id,
                        scope=str(cl.get("scope", "general")),
                        assertion=str(cl.get("assertion", "")),
                        passage_ids=(tuple(str(x) for x in pids) if isinstance(pids, list) else ()),
                        minority=bool(outcome.role_axis == 11),
                    )
                )

            raw_objs = outcome.artifact.get("objections", [])
            objs_list = raw_objs if isinstance(raw_objs, list) else []
            for obj in objs_list:
                if isinstance(obj, Mapping):
                    raw_role_objs.append({str(k): v for k, v in obj.items()})

            role_call_entries.append(
                {
                    "role_axes": [outcome.role_axis],
                    "profile_ids": [outcome.profile_id],
                    "input_sha256": outcome.input_sha256,
                    "output_sha256": outcome.output_sha256,
                    "model_id": outcome.model_id,
                    "model_version": outcome.model_version,
                    "temperature": 0.2,
                    "top_p": 0.95,
                    "seed": None,
                }
            )
            summaries.append(
                {
                    "roleAxis": outcome.role_axis,
                    "roleName": outcome.role_name,
                    "profileId": outcome.profile_id,
                    "mScore": round(m_score, 4),
                    "tokenBudget": token_budget,
                    "lowFit": low_fit,
                    "blinded": is_blinded_call,
                    "falsificationEnabled": packet.falsification_enabled,
                    "valid": outcome.valid,
                    "claimsCount": len(claims_list),
                    "objectionsCount": len(objs_list),
                    "inputSha256": outcome.input_sha256,
                    "outputSha256": outcome.output_sha256,
                    "findings": [
                        {
                            "scope": str(cl.get("scope", "general")),
                            "assertion": str(cl.get("assertion", "")),
                            "passageIds": (
                                [str(x) for x in cl.get("passage_ids", [])]
                                if isinstance(cl.get("passage_ids"), list)
                                else []
                            ),
                        }
                        for cl in claims_list
                        if isinstance(cl, Mapping)
                    ],
                }
            )

    function_registry.invoke(
        "DVSS-K03",
        FunctionContext(
            run_id=run_id,
            attempt_id=attempt_id,
            profile=profile_name,
            tier=tier,
            payload={
                "roles": list(active_roles),
                "selected_profile_ids": selected_profile_ids,
                "m_scores": p_scores,
            },
        ),
        records=records,
    )
    function_registry.invoke(
        "DVSS-P10",
        FunctionContext(
            run_id=run_id,
            attempt_id=attempt_id,
            profile=profile_name,
            tier=tier,
            payload={"p10_enabled": p10_on, "profile_ids": selected_profile_ids},
        ),
        records=records,
    )
    function_registry.invoke(
        "DVSS-P11",
        FunctionContext(
            run_id=run_id,
            attempt_id=attempt_id,
            profile=profile_name,
            tier=tier,
            payload={"tier": tier, "falsification_enabled": p11_on},
        ),
        records=records,
    )
    return (
        outcomes,
        findings,
        role_call_entries,
        raw_role_objs,
        summaries,
        low_fit_objection,
        round_calls,
        round(round_cost_usd, 8),
    )


def _build_attempt_record(
    *,
    attempt_id: str,
    parent_id: str | None,
    event: Literal["initial", "tier_escalation", "retry"],
    reason: str,
    tier: int,
    hops: int,
    ppr_iterations: int,
    vertices_retained: int,
    graph_sha256: str,
    passages: Sequence[RetrievedPassage],
    role_call_entries: Sequence[Mapping[str, object]],
    scored_claims: Sequence[ScoredClaim],
    objections: Sequence[LedgerObjection],
    candidate_sha256: str,
) -> dict[str, object]:
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
    source_manifest = sha256_text("|".join(sorted(p.passage_id for p in passages)))
    return {
        "attempt_id": attempt_id,
        "parent_id": parent_id,
        "event": event,
        "reason": reason,
        "tier": tier,
        "hops": min(4, max(1, hops)),
        "ppr_iterations": min(80, max(0, ppr_iterations)),
        "vertices_retained": min(250, max(0, vertices_retained)),
        "graph_sha256": graph_sha256,
        "source_manifest_sha256": source_manifest,
        "role_calls": [dict(rc) for rc in role_call_entries],
        "claims": claim_dicts,
        "objections": obj_dicts,
        "candidate_sha256": candidate_sha256,
    }


def _build_receipt_payload(
    *,
    run_id: str,
    utc_iso: str,
    terminal_attempt_id: str,
    policy_sha256: str,
    profile: str,
    passages: Sequence[RetrievedPassage],
    attempts: Sequence[Mapping[str, object]],
    calibration: CalibrationArtifact | None,
    hard_gate: bool,
    drift_latched: bool,
    cusum: float,
    terminal_u: float,
    receipt_release_mode: str,
    response_sha256: str,
    records: Sequence[FunctionRecord],
    coordinate_manifest_sha256: str | None = None,
) -> dict[str, object]:
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
    return {
        "schema_version": "3.8.0",
        "run_id": run_id,
        "utc": utc_iso,
        "chain_id": "main",
        "previous_hash": "GENESIS",
        "coordinate_manifest_sha256": (
            coordinate_manifest_sha256 or sha256_text("phase2-coordinate-manifest")
        ),
        "policy_sha256": policy_sha256,
        "verifier_version": "0.1.0",
        "attempts": [dict(a) for a in attempts],
        "sources": src_dicts,
        "calibration": _calibration_block(calibration),
        "decision": {
            "hard_gate": hard_gate,
            "drift_latched": drift_latched,
            "cusum": round(max(0.0, cusum), 6),
            "terminal_u": round(min(1.0, max(0.0, terminal_u)), 6),
            "terminal_attempt_id": terminal_attempt_id,
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
    query_digest = sha256_text(_extract_latest_user_query(run_req.contents))
    cancel_attempt = _build_attempt_record(
        attempt_id="att-0",
        parent_id=None,
        event="initial",
        reason="client_stream_cancelled",
        tier=1,
        hops=1,
        ppr_iterations=0,
        vertices_retained=0,
        graph_sha256=sha256_text("cancelled"),
        passages=(),
        role_call_entries=[
            {
                "role_axes": [8],
                "profile_ids": ["scholar-cancelled"],
                "input_sha256": query_digest,
                "output_sha256": empty_sha,
                "model_id": writer_model,
                "model_version": f"{writer_model}-001",
                "temperature": 0.0,
                "top_p": 1.0,
                "seed": None,
            }
        ],
        scored_claims=(),
        objections=(),
        candidate_sha256=empty_sha,
    )
    payload = _build_receipt_payload(
        run_id=run_req.run_id,
        utc_iso=utc_iso,
        terminal_attempt_id="att-0",
        policy_sha256=config.policy_sha256,
        profile=profile,
        passages=(),
        attempts=[cancel_attempt],
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
    registry_snapshot: RegistrySnapshot | None = None,
    enable_ppr: bool = True,
    registry_repo: RegistryRepository | None = None,
    reference_catalog: ReferenceCatalog | None = None,
    tool_bridge: ToolBridge | None = None,
    intake_router: IntakeRouter | None = None,
    function_flags_override: FunctionFlagsConfig | None = None,
    tenant: str = "default",
    explicit_session: str | None = None,
    triage_override: Mapping[str, object] | None = None,
    retry_sources: Sequence[str] = (),
    pareto_options: Sequence[CandidateOption] = (),
    pareto_objectives: Sequence[ParetoObjective] = (),
) -> GovernedRunResult:
    """Execute the full 12-step FROST orchestrator, Quad Personas, retries, and receipt."""
    log = get_logger("dle.host.workflow.governed")
    start_clock = time.perf_counter()
    profile = run_req.profile or "strict"
    profile_cfg = config.profiles.get(profile)
    blinded_assurance = bool(profile_cfg.blinded_assurance_roles) if profile_cfg else False
    eff_function_flags = (
        function_flags_override if function_flags_override is not None else config.function_flags
    )
    proposal_id = "p0"
    records: list[FunctionRecord] = []
    trace = FrostTrace()
    query_str = _extract_latest_user_query(run_req.contents)
    query_digest = sha256_text(query_str)
    writer_model = model_registry.pin_for_job("writer")
    utc_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    coord_manifest_sha = (
        registry_snapshot.manifest_sha256
        if registry_snapshot is not None
        else sha256_text("phase2-coordinate-manifest")
    )
    overlay: SessionOverlay | None = None
    ledger = LedgerService(session_repo)
    writer_service = WriterService()
    run_cost_usd = 0.0

    try:
        # ------------------------------------------------------------------ s01_ingest (L1)
        s01_t0 = time.perf_counter()
        k01_res = function_registry.invoke(
            "DVSS-K01",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id="att-0",
                profile=profile,
                payload={"model": run_req.model, "turn_count": len(run_req.contents)},
            ),
            records=records,
        )
        if k01_res.outcome != "ok":
            raise ValueError("DVSS-K01 request validation rejected governed payload")

        input_safety = safety_policy_check(input_content=query_str, proposal_id=proposal_id)
        if run_req.has_function_responses:
            if tool_bridge is not None:
                tool_bridge.resume(run_req.session_id)
            session_repo.pop_parked_run(run_req.session_id)

        consequential_hits: tuple[ConsequentialToolHit, ...] = check_consequential_functions(
            run_req.contents,
            eff_function_flags,
        )
        app_tool_passages = _extract_tool_passages(run_req.contents, utc_iso=utc_iso)

        coord_res: CoordinateParseResult | None = None
        proposed_anchors: list[str] = []
        extra_dle_meta: dict[str, object] = {}
        if registry_snapshot is not None:
            proposed_anchors = propose_anchors_from_query(
                query_str or "warehouse", registry_snapshot
            )
            binding_hint = any(a.startswith("[HUB:") for a in proposed_anchors) or bool(
                consequential_hits
            )
            coord_res = parse_coordinate(
                proposed_anchors=proposed_anchors,
                snapshot=registry_snapshot,
                as_of=datetime.now(UTC).date(),
                binding_claim=binding_hint,
            )

        intake_decision: IntakeDecision | None = None
        if triage_override is not None:
            triage_payload: dict[str, object] = dict(triage_override)
        elif intake_router is not None:
            intake_decision = await intake_router.evaluate(
                query_str=query_str,
                coordinate=coord_res.coordinate if coord_res is not None else None,
                consequential_tool_hit=bool(consequential_hits),
                api_key=api_key,
            )
            ops_repo.record_model_call(
                call_id=str(uuid.uuid4()),
                run_id=run_req.run_id,
                job="intake",
                model_id=intake_decision.model_id,
                model_version=intake_decision.model_version,
                input_tokens=intake_decision.input_tokens,
                output_tokens=intake_decision.output_tokens,
                thought_tokens=0,
                cost_usd=intake_decision.cost_usd,
                duration_ms=intake_decision.duration_ms,
                attempts=1,
                status="ok",
                called_utc=utc_iso,
            )
            run_cost_usd += intake_decision.cost_usd
            triage_payload = intake_decision.to_k10_payload()
            extra_dle_meta["intake"] = intake_decision.to_public_metadata()
        else:
            triage_payload = {"d": 0, "r": 0, "m": 0, "binding": False, "z_hit": False}

        k10_res = function_registry.invoke(
            "DVSS-K10",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id="att-0",
                profile=profile,
                payload=triage_payload,
            ),
            records=records,
        )
        raw_tier = k10_res.output.get("tier", 1)
        tier = int(raw_tier) if isinstance(raw_tier, int | float) else 1
        initial_tier = tier
        raw_s = k10_res.output.get("s", 0)
        s_score = int(raw_s) if isinstance(raw_s, int | float) else 0
        raw_seff = k10_res.output.get("s_eff", s_score)
        s_eff = int(raw_seff) if isinstance(raw_seff, int | float) else s_score
        raw_z = k10_res.output.get("z", 0)
        z_flag = int(raw_z) if isinstance(raw_z, int | float) else 0
        raw_roles = k10_res.output.get("active_roles", ["scholar"])
        active_roles: tuple[str, ...] = (
            tuple(str(r).lower().strip() for r in raw_roles if str(r).strip())
            if isinstance(raw_roles, list) and raw_roles
            else ("scholar",)
        )
        call_budget = ModelCallBudget(config.tiers, initial_tier=initial_tier)
        if intake_decision is not None:
            call_budget.record_call(1)
        trace.record(
            step_id="s01_ingest",
            attempt_id="att-0",
            event="initial",
            status="ok",
            dvss_ids=("DVSS-K01", "DVSS-P13", "DVSS-K10"),
            duration_ms=(time.perf_counter() - s01_t0) * 1000.0,
        )

        # ------------------------------------------------------------------ s02_anchor (L1)
        s02_t0 = time.perf_counter()
        if coord_res is not None:
            function_registry.invoke(
                "DVSS-K02",
                FunctionContext(
                    run_id=run_req.run_id,
                    attempt_id="att-0",
                    profile=profile,
                    tier=tier,
                    payload={
                        "coordinate": coord_res.coordinate,
                        "active_axes": list(coord_res.active_axes),
                        "manifest_sha256": coord_manifest_sha,
                    },
                ),
                records=records,
            )
            extra_dle_meta["coordinate"] = _build_coordinate_metadata(
                coord_res, manifest_sha256=coord_manifest_sha
            )
        trace.record(
            step_id="s02_anchor",
            attempt_id="att-0",
            event="initial",
            status="ok",
            dvss_ids=("DVSS-K02",),
            duration_ms=(time.perf_counter() - s02_t0) * 1000.0,
        )

        # ------------------------------------------------------------------ s03_screen (L2)
        s03_t0 = time.perf_counter()
        overlay = SessionOverlay(run_req.session_id)
        if coord_res is not None and coord_res.open_dependencies:
            first_dep = coord_res.open_dependencies[0]
            overlay.synthesize_hypothesis(
                label=f"Open dependency on axis {first_dep.axis_id}: {first_dep.reason}",
                anchor_atoms=proposed_anchors[:2] or ["[PL:1.1.0.0]"],
            )
        function_registry.invoke(
            "DVSS-P03",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id="att-0",
                profile=profile,
                tier=tier,
                payload={"tmp_node_count": len(overlay.list_nodes())},
            ),
            records=records,
        )
        trace.record(
            step_id="s03_screen",
            attempt_id="att-0",
            event="initial",
            status="ok",
            dvss_ids=("DVSS-P03",),
            duration_ms=(time.perf_counter() - s03_t0) * 1000.0,
        )

        # ---------------------------------------- s04_retrieve Tool Parking Check (FR-TOOL-02)
        if _has_client_function_declarations(run_req) and not run_req.has_function_responses:
            s04_t0 = time.perf_counter()
            probe_res = await model_port.generate(
                writer_model,
                run_req.raw_body,
                api_key=api_key,
                job="passthrough",
            )
            call_budget.record_call(1)
            tool_calls = extract_function_calls(probe_res.body)
            if tool_calls:
                model_content = extract_model_content(probe_res.body)
                if model_content is not None:
                    next_sid = session_id_after_response(
                        tenant=tenant,
                        model=run_req.model,
                        system_instruction=run_req.system_instruction,
                        contents=run_req.contents,
                        response_content=model_content,
                        explicit_session=explicit_session,
                    )
                else:
                    next_sid = run_req.session_id
                park_state: dict[str, object] = {
                    "step": "s04_retrieve",
                    "tier": tier,
                    "active_roles": list(active_roles),
                    "model": run_req.model,
                }
                if tool_bridge is not None:
                    tool_bridge.park(
                        run_id=run_req.run_id,
                        session_id=next_sid,
                        pending_calls=tool_calls,
                        run_state=park_state,
                    )
                session_repo.touch_session(
                    session_id=next_sid,
                    tenant=tenant,
                    model=run_req.model,
                    now_utc=utc_iso,
                    expires_utc=utc_iso,
                )
                session_repo.park_run(
                    run_id=run_req.run_id,
                    session_id=next_sid,
                    pending_calls=list(tool_calls),
                    run_state=park_state,
                    parked_utc=utc_iso,
                )
                trace.record(
                    step_id="s04_retrieve",
                    attempt_id="att-0",
                    event="initial",
                    status="parked",
                    dvss_ids=("DVSS-K05",),
                    duration_ms=(time.perf_counter() - s04_t0) * 1000.0,
                )
                return GovernedRunResult(
                    release_mode="passthrough",
                    receipt_id="",
                    tier=tier,
                    body=copy.deepcopy(probe_res.body),
                    notice_id="NOTICE-TOOL-01",
                    hold_reason=None,
                    terminal_u=0.0,
                    receipt={},
                    function_records=tuple(records),
                    retries=0,
                    escalated=False,
                    steps=tuple(trace.to_metadata_list()),
                    personas=(),
                )

        if input_safety:
            ledger.record_objections(
                run_id=run_req.run_id,
                attempt_id="att-0",
                objections=input_safety,
                utc_iso=utc_iso,
            )

        # ----------------------------------------------------- Bounded Multi-Attempt Loop
        retries_used = 0
        escalated_once = False
        escalation_reason: str | None = None
        seen_source_ids: set[str] = set()
        attempts_log: list[dict[str, object]] = []
        last_event: Literal["initial", "tier_escalation", "retry"] = "initial"
        last_reason = f"tier_{tier}_frost_orchestrator"
        parent_attempt_id: str | None = None
        attempt_idx = 0

        final_attempt_id = "att-0"
        final_passages: tuple[RetrievedPassage, ...] = ()
        final_verification = None
        final_term_score: TerminalScore | None = None
        final_open_blocking: tuple[LedgerObjection, ...] = ()
        final_draft_str = ""
        final_writer_body: dict[str, object] = {}
        final_persona_summaries: list[dict[str, object]] = []

        while attempt_idx < 4:
            attempt_id = f"att-{attempt_idx}"

            # -------------------------------------------------------------- s04_retrieve (L2)
            s04_t0 = time.perf_counter()
            ppr_res: GraphExpansionResult | None = None
            ppr_iters = 0
            eff_hops = 1 if tier <= 1 else min(4, 2 + retries_used)
            eff_vertices = 0
            eff_graph_sha = sha256_text(
                "dense-only" if not enable_ppr else "phase4-frost-retrieval"
            )

            if registry_snapshot is not None and enable_ppr:
                limits = config.tiers.graph_limits
                ppr_res = expand_bounded_ppr(
                    anchors=proposed_anchors,
                    snapshot=registry_snapshot,
                    tier=tier,
                    retry_count=retries_used,
                    overlay=overlay,
                    damping=limits.ppr_damping,
                    max_iterations=limits.ppr_max_iterations,
                    tolerance=limits.ppr_tolerance,
                    max_vertices=limits.max_vertices,
                )
                ppr_iters = ppr_res.ppr_iterations
                eff_hops = ppr_res.effective_hops
                eff_vertices = len(ppr_res.vertices)
                eff_graph_sha = ppr_res.graph_sha256
                function_registry.invoke(
                    "DVSS-K07",
                    FunctionContext(
                        run_id=run_req.run_id,
                        attempt_id=attempt_id,
                        profile=profile,
                        tier=tier,
                        payload={
                            "vertices": [v.vertex_id for v in ppr_res.vertices],
                            "ppr_iterations": ppr_iters,
                        },
                    ),
                    records=records,
                )
                extra_dle_meta["graph"] = _build_graph_metadata(
                    ppr_enabled=True,
                    hops=eff_hops,
                    ppr_res=ppr_res,
                    graph_sha256=eff_graph_sha,
                    vertices_retained=eff_vertices,
                )

            hint_suffix = (
                f" {retry_sources[retries_used - 1]}"
                if retries_used > 0 and retries_used - 1 < len(retry_sources)
                else ""
            )
            attempt_query = (query_str or "warehouse substitution policy") + hint_suffix
            retrieval: RetrievalResult = await evidence_service.retrieve(
                query=attempt_query.strip(),
                limit=8,
                idempotency_key=f"{run_req.run_id}:{attempt_id}",
                api_key=api_key,
            )
            merged_passages: tuple[RetrievedPassage, ...] = (
                *retrieval.passages,
                *app_tool_passages,
            )
            current_src_ids = {p.passage_id for p in merged_passages}
            new_evidence_found = bool(current_src_ids - seen_source_ids)
            seen_source_ids.update(current_src_ids)

            if registry_snapshot is not None and not enable_ppr:
                eff_vertices = len(merged_passages)
                extra_dle_meta["graph"] = _build_graph_metadata(
                    ppr_enabled=False,
                    hops=eff_hops,
                    ppr_res=None,
                    graph_sha256=eff_graph_sha,
                    vertices_retained=eff_vertices,
                )
            elif registry_snapshot is None:
                eff_vertices = len(merged_passages)

            function_registry.invoke(
                "DVSS-K05",
                FunctionContext(
                    run_id=run_req.run_id,
                    attempt_id=attempt_id,
                    profile=profile,
                    tier=tier,
                    payload={"passage_count": len(merged_passages)},
                ),
                records=records,
            )
            trace.record(
                step_id="s04_retrieve",
                attempt_id=attempt_id,
                event=last_event,
                status="ok",
                dvss_ids=("DVSS-K07", "DVSS-K05") if enable_ppr else ("DVSS-K05",),
                duration_ms=(time.perf_counter() - s04_t0) * 1000.0,
            )

            # ------------------------------------------------- s05_deliberate (L3 / L4)
            s05_t0 = time.perf_counter()
            (
                _role_outcomes,
                role_findings,
                role_call_entries,
                raw_role_objs,
                persona_summaries,
                low_fit_obj,
                round_calls,
                round_cost_usd,
            ) = await _execute_deliberation_round(
                run_id=run_req.run_id,
                attempt_id=attempt_id,
                tier=tier,
                active_roles=active_roles,
                query_str=query_str,
                proposal_id=proposal_id,
                passages=merged_passages,
                ledger=ledger,
                coord_res=coord_res,
                ppr_res=ppr_res,
                snapshot=registry_snapshot,
                config=config,
                function_registry=function_registry,
                model_registry=model_registry,
                model_port=model_port,
                ops_repo=ops_repo,
                registry_repo=registry_repo,
                reference_catalog=reference_catalog,
                profile_name=profile,
                blinded=blinded_assurance,
                api_key=api_key,
                utc_iso=utc_iso,
                records=records,
            )
            call_budget.record_call(round_calls)
            run_cost_usd += round_cost_usd
            trace.record(
                step_id="s05_deliberate",
                attempt_id=attempt_id,
                event=last_event,
                status="ok",
                dvss_ids=("DVSS-K03", "DVSS-P08", "DVSS-P10", "DVSS-P11"),
                duration_ms=(time.perf_counter() - s05_t0) * 1000.0,
                layer_override="l03_persona_selection",
            )
            trace.record(
                step_id="s05_deliberate",
                attempt_id=attempt_id,
                event=last_event,
                status="ok",
                dvss_ids=("DVSS-P11",),
                duration_ms=0.0,
                layer_override="l04_deliberation",
            )

            # ------------------------------------------------- s06_reconcile (L5)
            s06_t0 = time.perf_counter()
            if raw_role_objs:
                ledger.record_role_objections(
                    run_id=run_req.run_id,
                    attempt_id=attempt_id,
                    raw_objections=raw_role_objs,
                    utc_iso=utc_iso,
                )
            if low_fit_obj:
                ledger.record_objections(
                    run_id=run_req.run_id,
                    attempt_id=attempt_id,
                    objections=[
                        LedgerObjection(
                            objection_id=f"harm-low-fit-{attempt_id}",
                            role_axis=11,
                            proposal_id=proposal_id,
                            blocking=False,
                            predicate="low_fit_generic_role_profile_at_tier3",
                            state="open",
                        )
                    ],
                    utc_iso=utc_iso,
                )
            pareto_res = filter_pareto_options(
                options=pareto_options,
                objectives=pareto_objectives,
            )
            function_registry.invoke(
                "DVSS-P02",
                FunctionContext(
                    run_id=run_req.run_id,
                    attempt_id=attempt_id,
                    profile=profile,
                    tier=tier,
                    payload={
                        "applied": pareto_res.applied,
                        "retained_count": len(pareto_res.retained),
                    },
                ),
                records=records,
            )
            trace.record(
                step_id="s06_reconcile",
                attempt_id=attempt_id,
                event=last_event,
                status="ok",
                dvss_ids=("DVSS-P02",),
                duration_ms=(time.perf_counter() - s06_t0) * 1000.0,
            )

            # ------------------------------------------------- s07_crosswalk (L6)
            s07_t0 = time.perf_counter()
            aligned_count = 0
            if registry_snapshot is not None and ppr_res is not None:
                aligned = align_crosswalk_terms(
                    atoms=[v.vertex_id for v in ppr_res.vertices],
                    snapshot=registry_snapshot,
                )
                aligned_count = len(aligned.groups)
            function_registry.invoke(
                "DVSS-P06",
                FunctionContext(
                    run_id=run_req.run_id,
                    attempt_id=attempt_id,
                    profile=profile,
                    tier=tier,
                    payload={"aligned_groups": aligned_count},
                ),
                records=records,
            )
            trace.record(
                step_id="s07_crosswalk",
                attempt_id=attempt_id,
                event=last_event,
                status="ok",
                dvss_ids=("DVSS-P06",),
                duration_ms=(time.perf_counter() - s07_t0) * 1000.0,
            )

            # ------------------------------------------------- s08_scope (L7)
            s08_t0 = time.perf_counter()
            jur_state_str = (
                str(coord_res.coordinate.get("jurisdiction_state", "unscoped"))
                if coord_res is not None
                else "unscoped"
            )
            if registry_snapshot is not None and registry_snapshot.intervals:
                _temp_res = evaluate_temporal_applicability(
                    list(registry_snapshot.intervals.values()),
                    as_of=datetime.now(UTC).date(),
                )
            jurs = _canonical_atoms(coord_res, "axis_12_jurisdiction")
            if (
                registry_snapshot is not None
                and jurs
                and jurs[0] in registry_snapshot.jurisdictions
            ):
                jur_rec = registry_snapshot.jurisdictions[jurs[0]]
                hub_atoms = _canonical_atoms(coord_res, "axis_6_octopus")
                arms_for_p01: list[dict[str, object]] = []
                for hid in hub_atoms:
                    h_rec = registry_snapshot.hubs.get(hid)
                    raw_arms = h_rec.get("arms", []) if isinstance(h_rec, Mapping) else []
                    if isinstance(raw_arms, list):
                        for arm in raw_arms:
                            if isinstance(arm, Mapping):
                                arms_for_p01.append({str(k): v for k, v in arm.items()})
                _jur_res = resolve_jurisdiction_precedence(
                    jurisdiction_record=jur_rec,
                    hub_arms=arms_for_p01,
                    as_of=datetime.now(UTC).date(),
                    hub_id=hub_atoms[0] if hub_atoms else "[HUB:6.0]",
                    binding_claim=bool(hub_atoms),
                )
                jur_state_str = _jur_res.jurisdiction_state
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
            function_registry.invoke(
                "DVSS-P01",
                FunctionContext(
                    run_id=run_req.run_id,
                    attempt_id=attempt_id,
                    profile=profile,
                    tier=tier,
                    payload={"jurisdiction_state": jur_state_str},
                ),
                records=records,
            )
            trace.record(
                step_id="s08_scope",
                attempt_id=attempt_id,
                event=last_event,
                status="ok",
                dvss_ids=("DVSS-K06", "DVSS-P01"),
                duration_ms=(time.perf_counter() - s08_t0) * 1000.0,
            )

            # ------------------------------------------------- s09_verify_authority (L8)
            s09_t0 = time.perf_counter()
            writer_packet = writer_service.build_packet(
                question=query_str or "Provide verified response.",
                proposal_id=proposal_id,
                findings=role_findings,
                supported_claims=[],
                open_objections=ledger.open_blocking_objections(run_req.run_id),
                pareto_options=pareto_res.retained,
                passages=_passage_dicts(merged_passages),
                conduct_config=config.conduct,
            )
            call_t0 = time.perf_counter()
            writer_res = await writer_service.draft(
                packet=writer_packet,
                model_port=model_port,
                model_id=writer_model,
                api_key=api_key,
            )
            call_ms = (time.perf_counter() - call_t0) * 1000.0
            writer_cost = safe_compute_cost(
                model_registry,
                writer_res.model_id,
                input_tokens=writer_res.input_tokens,
                output_tokens=writer_res.output_tokens,
                model_version=writer_res.model_version,
            )
            call_budget.record_call(1)
            run_cost_usd += writer_cost
            ops_repo.record_model_call(
                call_id=str(uuid.uuid4()),
                run_id=run_req.run_id,
                job="writer",
                model_id=writer_res.model_id,
                model_version=writer_res.model_version,
                input_tokens=writer_res.input_tokens,
                output_tokens=writer_res.output_tokens,
                thought_tokens=0,
                cost_usd=writer_cost,
                duration_ms=round(call_ms, 3),
                attempts=writer_res.attempts,
                status="ok",
                called_utc=utc_iso,
            )
            draft_str = writer_res.draft_body
            writer_body_dict: dict[str, object] = {
                "candidates": [
                    {
                        "index": 0,
                        "content": {"role": "model", "parts": [{"text": draft_str}]},
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": writer_res.model_version,
            }

            extraction = await claim_extractor.extract(
                run_id=run_req.run_id,
                attempt_id=attempt_id,
                proposal_id=proposal_id,
                draft_text=draft_str,
                api_key=api_key,
            )
            call_budget.record_call(1)
            verification = claim_verifier.verify(
                claims=extraction.claims,
                passages=merged_passages,
                draft_text=draft_str,
            )
            output_safety = safety_policy_check(
                output_content=draft_str,
                proposal_id=proposal_id,
            )
            span_objections = [
                LedgerObjection(
                    objection_id=f"{so['objection_id']}-{attempt_id}",
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
                    objection_id=f"contra-{attempt_id}-{idx}",
                    role_axis=10,
                    proposal_id=proposal_id,
                    blocking=True,
                    predicate=c.reason,
                    state="open",
                )
                for idx, c in enumerate(verification.contradictions, start=1)
            ]
            host_objs = [*output_safety, *span_objections, *contra_objections]
            if host_objs:
                ledger.record_objections(
                    run_id=run_req.run_id,
                    attempt_id=attempt_id,
                    objections=host_objs,
                    utc_iso=utc_iso,
                )
            trace.record(
                step_id="s09_verify_authority",
                attempt_id=attempt_id,
                event=last_event,
                status="ok",
                dvss_ids=("DVSS-P04", "DVSS-P13", "DVSS-K05"),
                duration_ms=(time.perf_counter() - s09_t0) * 1000.0,
            )

            # ------------------------------------------------- s10_score (L8)
            s10_t0 = time.perf_counter()
            current_ledger = ledger.current_state(run_req.run_id)
            norm_objections, open_blocking = evaluate_compliance_veto(current_ledger)
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
            term_score = compute_terminal_u(
                verification.scored_claims,
                open_objections=len(open_blocking),
                total_objections=len(norm_objections),
            )
            attempts_log.append(
                _build_attempt_record(
                    attempt_id=attempt_id,
                    parent_id=parent_attempt_id,
                    event=last_event,
                    reason=last_reason,
                    tier=tier,
                    hops=eff_hops,
                    ppr_iterations=ppr_iters,
                    vertices_retained=eff_vertices,
                    graph_sha256=eff_graph_sha,
                    passages=merged_passages,
                    role_call_entries=role_call_entries,
                    scored_claims=verification.scored_claims,
                    objections=norm_objections,
                    candidate_sha256=sha256_text(draft_str),
                )
            )
            trace.record(
                step_id="s10_score",
                attempt_id=attempt_id,
                event=last_event,
                status="ok",
                dvss_ids=("DVSS-K12", "DVSS-K08"),
                duration_ms=(time.perf_counter() - s10_t0) * 1000.0,
            )

            final_attempt_id = attempt_id
            final_passages = merged_passages
            final_verification = verification
            final_term_score = term_score
            final_open_blocking = open_blocking
            final_draft_str = draft_str
            final_writer_body = writer_body_dict
            final_persona_summaries = persona_summaries

            # ------------------------------------------------- s11_refine_decide: P07 then K09
            has_binding = any(c.binding for c in verification.scored_claims) or bool(
                consequential_hits
            )
            esc = evaluate_binding_escalation(
                tier=tier,
                s_score=s_score,
                z_flag=z_flag,
                active_roles=active_roles,
                has_binding_claim=has_binding,
                escalated_once=escalated_once,
                consequential_tool_used=bool(consequential_hits),
            )
            function_registry.invoke(
                "DVSS-P07",
                FunctionContext(
                    run_id=run_req.run_id,
                    attempt_id=attempt_id,
                    profile=profile,
                    tier=tier,
                    payload={
                        "has_binding": has_binding,
                        "has_regulator": "regulator" in active_roles,
                        "escalated_once": escalated_once,
                        "escalate": esc.should_escalate,
                    },
                ),
                records=records,
            )
            if esc.should_escalate:
                tier = esc.new_tier
                active_roles = esc.new_roles
                escalated_once = True
                escalation_reason = esc.reason
                call_budget.on_escalate(next_tier=tier)
                parent_attempt_id = attempt_id
                last_event = "tier_escalation"
                last_reason = esc.reason
                trace.record(
                    step_id="s11_refine_decide",
                    attempt_id=attempt_id,
                    event="initial",
                    status="escalated",
                    dvss_ids=("DVSS-P07",),
                )
                if not call_budget.can_spend(len(active_roles) + 2):
                    break
                attempt_idx += 1
                continue

            next_auth_src = (
                retry_sources[retries_used] if retries_used < len(retry_sources) else None
            )
            has_gap = bool(
                next_auth_src
                and (
                    not verification.scored_claims
                    or not verification.all_binding_verified
                    or any(c.support_z < 0.70 for c in verification.scored_claims)
                )
            )
            retry_dec = decide_retry_policy(
                RetryPolicyInput(
                    retries_used=retries_used,
                    max_retries=2,
                    has_recoverable_gap=has_gap,
                    gap_reason="missing_supporting_evidence" if has_gap else None,
                    authorized_next_source=next_auth_src,
                    has_permanent_veto=bool(input_safety or output_safety),
                    new_evidence_found=True if attempt_idx == 0 else new_evidence_found,
                    resolved=bool(
                        verification.scored_claims
                        and verification.all_binding_verified
                        and all(c.support_z >= 0.70 for c in verification.scored_claims)
                        and not open_blocking
                    ),
                    candidate_id=attempt_id,
                )
            )
            function_registry.invoke(
                "DVSS-K09",
                FunctionContext(
                    run_id=run_req.run_id,
                    attempt_id=attempt_id,
                    profile=profile,
                    tier=tier,
                    payload={
                        "retries": retries_used,
                        "action": retry_dec.action,
                        "reason": retry_dec.reason,
                    },
                ),
                records=records,
            )
            if retry_dec.action == "retry":
                needed_retry_calls = len(active_roles) + 2
                if not call_budget.can_spend(needed_retry_calls):
                    trace.record(
                        step_id="s11_refine_decide",
                        attempt_id=attempt_id,
                        event=last_event,
                        status="call_budget_exhausted",
                        dvss_ids=("DVSS-K09",),
                    )
                    break
                retries_used += 1
                parent_attempt_id = attempt_id
                last_event = "retry"
                last_reason = retry_dec.reason
                trace.record(
                    step_id="s11_refine_decide",
                    attempt_id=attempt_id,
                    event="retry",
                    status="retrying",
                    dvss_ids=("DVSS-K09",),
                )
                attempt_idx += 1
                continue

            break

        # ---------------------------------------------- Terminal Decision & s12_seal (L9/L10)
        if final_verification is None or final_term_score is None:
            raise RuntimeError("orchestrator completed without terminal verification score")
        s11_t0 = time.perf_counter()
        prior_drift = ops_repo.get_drift_state()
        prev_c = float(str(prior_drift["c_t"])) if prior_drift is not None else 0.0
        prev_latched = bool(prior_drift["is_latched"]) if prior_drift is not None else False
        prev_latch_reason = (
            str(prior_drift["latch_reason"])
            if prior_drift is not None and prior_drift.get("latch_reason")
            else None
        )
        eff_cal = calibration if calibration is not None else DEFAULT_PHASE2_CALIBRATION
        cusum_c, drift_latched, _reason = update_cusum_drift(
            previous_c_t=prev_c,
            u_t=final_term_score.u,
            calibration=eff_cal,
            previous_latched=prev_latched or model_registry.drift_latched,
            previous_latch_reason=prev_latch_reason,
            ops_repo=ops_repo,
        )
        gate = evaluate_release_gate(
            schema_scope_valid=True,
            claims=final_verification.scored_claims,
            all_binding_verified=final_verification.all_binding_verified,
            open_blocking_objections=final_open_blocking,
            score=final_term_score,
            calibration=calibration,
            drift_latched=drift_latched,
            cusum=cusum_c,
        )
        function_registry.invoke(
            "DVSS-K04",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id=final_attempt_id,
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
        flagged_count = sum(1 for c in final_verification.scored_claims if c.support_z < 0.70)
        weakest_text = ""
        if final_term_score.weakest_claim_id:
            weak_hit = next(
                (
                    c
                    for c in final_verification.scored_claims
                    if c.claim_id == final_term_score.weakest_claim_id
                ),
                None,
            )
            weakest_text = weak_hit.assertion[:80] if weak_hit is not None else ""

        disclosure = apply_disclosure(
            gate=gate,
            profile=profile,
            draft_text=final_draft_str,
            notices=config.notices,
            receipt_id=run_req.run_id,
            source_count=len(final_passages),
            flagged_count=max(1, flagged_count),
            weakest_claim_summary=weakest_text or "unsupported assertion",
            objection_predicate=(
                final_open_blocking[0].predicate if final_open_blocking else "compliance"
            ),
        )
        function_registry.invoke(
            "DVSS-K11",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id=final_attempt_id,
                profile=profile,
                tier=tier,
                payload={
                    "decision": gate.decision,
                    "draft_text": final_draft_str,
                    "drift_latched": drift_latched,
                    "flagged_count": max(1, flagged_count),
                    "hold_notice": (
                        disclosure.final_text if disclosure.api_release_mode == "held" else None
                    ),
                },
            ),
            records=records,
        )
        trace.record(
            step_id="s11_refine_decide",
            attempt_id=final_attempt_id,
            event=last_event,
            status=gate.decision,
            dvss_ids=("DVSS-P12", "DVSS-K04", "DVSS-K11"),
            duration_ms=(time.perf_counter() - s11_t0) * 1000.0,
        )

        # Replace final attempt's candidate_sha256 with disclosed response digest per contract.
        if attempts_log:
            attempts_log[-1]["candidate_sha256"] = disclosure.response_sha256

        _record_remaining_kernel_hooks(
            registry=function_registry,
            run_id=run_req.run_id,
            attempt_id=final_attempt_id,
            profile=profile,
            tier=tier,
            records=records,
        )

        s12_t0 = time.perf_counter()
        trace.record(
            step_id="s12_seal",
            attempt_id=final_attempt_id,
            event=last_event,
            status=disclosure.receipt_release_mode,
            dvss_ids=("DVSS-K11",),
            duration_ms=(time.perf_counter() - s12_t0) * 1000.0,
        )
        step_metadata = trace.to_metadata_list()
        extra_dle_meta["runSummary"] = {
            "initialTier": initial_tier,
            "finalTier": tier,
            "escalated": escalated_once,
            "escalationReason": escalation_reason,
            "retries": retries_used,
            "maxRetries": 2,
            "attemptsCount": len(attempts_log),
            "blindedAssuranceRoles": blinded_assurance,
            "consequentialTools": [h.name for h in consequential_hits],
            "sEff": s_eff,
            "modelCallsUsed": call_budget.used,
            "modelCallBudget": call_budget.limit,
            "costUsd": round(run_cost_usd, 6),
        }
        extra_dle_meta["personas"] = final_persona_summaries
        extra_dle_meta["steps"] = step_metadata

        response_body = _build_governed_gemini_body(
            release_mode=disclosure.api_release_mode,
            receipt_id=run_req.run_id,
            tier=tier,
            final_content=disclosure.final_text,
            hold_reason=gate.block_reason if disclosure.api_release_mode == "held" else None,
            writer_body=final_writer_body,
            grounding_metadata=final_verification.grounding_metadata,
            extra_dle_metadata=extra_dle_meta,
        )

        receipt_payload = _build_receipt_payload(
            run_id=run_req.run_id,
            utc_iso=utc_iso,
            terminal_attempt_id=final_attempt_id,
            policy_sha256=config.policy_sha256,
            profile=profile,
            passages=final_passages,
            attempts=attempts_log,
            calibration=calibration,
            hard_gate=gate.hard_gate,
            drift_latched=gate.drift_latched,
            cusum=cusum_c,
            terminal_u=final_term_score.u,
            receipt_release_mode=disclosure.receipt_release_mode,
            response_sha256=disclosure.response_sha256,
            records=records,
            coordinate_manifest_sha256=coord_manifest_sha,
        )
        sealed = receipt_sealer.seal_receipt(
            payload=receipt_payload,
            api_release_mode=disclosure.api_release_mode,
        )
        if overlay is not None:
            overlay.clear_on_seal()
        ops_repo.record_run_metrics(
            run_id=run_req.run_id,
            tier=tier,
            profile=profile,
            release_mode=disclosure.api_release_mode,
            retries=retries_used,
            escalated=escalated_once,
            u=final_term_score.u,
            duration_ms=round((time.perf_counter() - start_clock) * 1000.0, 3),
            cost_usd=round(run_cost_usd, 6),
            finished_utc=utc_iso,
        )
        return GovernedRunResult(
            release_mode=disclosure.api_release_mode,
            receipt_id=run_req.run_id,
            tier=tier,
            body=response_body,
            notice_id=disclosure.notice_id,
            hold_reason=gate.block_reason if disclosure.api_release_mode == "held" else None,
            terminal_u=final_term_score.u,
            receipt=sealed,
            function_records=tuple(records),
            retries=retries_used,
            escalated=escalated_once,
            steps=tuple(step_metadata),
            personas=tuple(final_persona_summaries),
        )
    except ModelUnavailable:
        hold_notice_id = "NOTICE-HOLD-06"
        hold_reason = "model_unavailable"
        log.warning("workflow.model_unavailable", run_id=run_req.run_id)
    except Exception as exc:
        hold_notice_id = "NOTICE-HOLD-07"
        hold_reason = "internal_error"
        log.error(
            "workflow.internal_error",
            run_id=run_req.run_id,
            error_type=type(exc).__name__,
        )

    hold_notice = next(
        (n.text for n in config.notices.notices if n.id == hold_notice_id),
        "Held: verification could not complete.",
    ).format(receipt_id=run_req.run_id)
    _record_remaining_kernel_hooks(
        registry=function_registry,
        run_id=run_req.run_id,
        attempt_id="att-0",
        profile=profile,
        tier=1,
        records=records,
        overrides={
            "DVSS-K04": {"hard_gate": False, "u": 1.0, "cutoff": 0.0, "drift_latched": False},
            "DVSS-K11": {"decision": "block", "hold_notice": hold_notice},
        },
    )
    resp_sha = sha256_text(hold_notice)
    fail_attempt = _build_attempt_record(
        attempt_id="att-0",
        parent_id=None,
        event="initial",
        reason=hold_reason,
        tier=1,
        hops=1,
        ppr_iterations=0,
        vertices_retained=0,
        graph_sha256=sha256_text("fail-closed"),
        passages=(),
        role_call_entries=[
            {
                "role_axes": [8],
                "profile_ids": ["scholar-failclosed"],
                "input_sha256": query_digest,
                "output_sha256": resp_sha,
                "model_id": writer_model,
                "model_version": f"{writer_model}-001",
                "temperature": 0.0,
                "top_p": 1.0,
                "seed": None,
            }
        ],
        scored_claims=(),
        objections=(),
        candidate_sha256=resp_sha,
    )
    fail_payload = _build_receipt_payload(
        run_id=run_req.run_id,
        utc_iso=utc_iso,
        terminal_attempt_id="att-0",
        policy_sha256=config.policy_sha256,
        profile=profile,
        passages=(),
        attempts=[fail_attempt],
        calibration=calibration,
        hard_gate=False,
        drift_latched=model_registry.drift_latched,
        cusum=0.0,
        terminal_u=1.0,
        receipt_release_mode="hard_veto_block",
        response_sha256=resp_sha,
        records=records,
        coordinate_manifest_sha256=coord_manifest_sha,
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


run_governed_workflow = run_governed_phase2

__all__ = [
    "DEFAULT_PHASE2_CALIBRATION",
    "GovernedRunResult",
    "run_governed_phase2",
    "run_governed_workflow",
    "seal_cancelled_receipt",
]
