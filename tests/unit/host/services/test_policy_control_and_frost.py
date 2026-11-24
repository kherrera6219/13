"""Unit, contract & property tests for Phase 4 Wave 4B (DVSS-K09, DVSS-P07, FROST, Flags)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dle.config.models import ConsequentialFunctionFlag, FunctionFlagsConfig
from dle.host.frost import FROST_LAYERS, STEP_IDS, STEP_TO_LAYER, FrostTrace
from dle.host.services.policy_control import (
    RetryPolicyInput,
    check_consequential_functions,
    decide_retry_policy,
    evaluate_binding_escalation,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACTS_FN = REPO_ROOT / "contracts" / "functions"


def _validate_fn_contract(fn_name: str, direction: str, payload: dict[str, object]) -> None:
    schema = json.loads((CONTRACTS_FN / f"{fn_name}.{direction}.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=payload, schema=schema)


def test_dvss_k09_cutoff_blind_two_retry_limit_and_stop_conditions() -> None:
    """T-UNIT-FN-K09-01..05: Retry limit <= 2, permanent veto, no new evidence & cutoff-blind."""
    k09_in_schema = json.loads((CONTRACTS_FN / "k09.in.json").read_text(encoding="utf-8"))
    forbidden_fields = {"cutoff", "threshold", "drift_latched", "label", "labels"}
    assert not (forbidden_fields & set(k09_in_schema["properties"]))
    assert k09_in_schema["additionalProperties"] is False

    in_0 = RetryPolicyInput(
        retries_used=0,
        max_retries=2,
        has_recoverable_gap=True,
        gap_reason="missing_annex",
        authorized_next_source="src-annex-1",
        has_permanent_veto=False,
        new_evidence_found=True,
        resolved=False,
        candidate_id="att-0",
    )
    _validate_fn_contract(
        "k09",
        "in",
        {
            "retries_used": in_0.retries_used,
            "max_retries": in_0.max_retries,
            "has_recoverable_gap": in_0.has_recoverable_gap,
            "gap_reason": in_0.gap_reason,
            "authorized_next_source": in_0.authorized_next_source,
            "has_permanent_veto": in_0.has_permanent_veto,
            "new_evidence_found": in_0.new_evidence_found,
            "resolved": in_0.resolved,
            "candidate_id": in_0.candidate_id,
        },
    )
    d0 = decide_retry_policy(in_0)
    assert d0.action == "retry" and d0.hop_increment == 1 and d0.next_source == "src-annex-1"
    _validate_fn_contract(
        "k09",
        "out",
        {
            "action": d0.action,
            "reason": d0.reason,
            "candidate_id": d0.candidate_id,
            "next_source": d0.next_source,
            "hop_increment": d0.hop_increment,
        },
    )

    # Hard cap <= 2 even if caller tries max_retries > 2
    d_cap = decide_retry_policy(
        RetryPolicyInput(
            retries_used=2,
            max_retries=5,
            has_recoverable_gap=True,
            gap_reason="missing_annex",
            authorized_next_source="src-annex-3",
            has_permanent_veto=False,
            new_evidence_found=True,
            resolved=False,
            candidate_id="att-2",
        )
    )
    assert d_cap.action == "terminal" and d_cap.reason == "retry_budget_exhausted"

    # Permanent veto immediately stops
    d_veto = decide_retry_policy(
        RetryPolicyInput(
            retries_used=0,
            has_recoverable_gap=True,
            authorized_next_source="src-annex-1",
            has_permanent_veto=True,
            new_evidence_found=True,
            resolved=False,
            candidate_id="att-0",
        )
    )
    assert d_veto.action == "terminal" and d_veto.reason == "permanent_veto"

    # Second retry stopped if previous retry found no useful new evidence
    d_stale = decide_retry_policy(
        RetryPolicyInput(
            retries_used=1,
            has_recoverable_gap=True,
            authorized_next_source="src-annex-2",
            has_permanent_veto=False,
            new_evidence_found=False,
            resolved=False,
            candidate_id="att-1",
        )
    )
    assert d_stale.action == "terminal" and d_stale.reason == "no_useful_new_evidence"


@settings(max_examples=80)
@given(
    retries_used=st.integers(min_value=0, max_value=6),
    max_retries=st.integers(min_value=0, max_value=6),
    gap=st.booleans(),
    veto=st.booleans(),
    new_ev=st.booleans(),
    resolved=st.booleans(),
    has_src=st.booleans(),
)
def test_dvss_k09_property_never_exceeds_two_retries(
    retries_used: int,
    max_retries: int,
    gap: bool,
    veto: bool,
    new_ev: bool,
    resolved: bool,
    has_src: bool,
) -> None:
    """Property check: DVSS-K09 never permits a 3rd retry under any inputs."""
    dec = decide_retry_policy(
        RetryPolicyInput(
            retries_used=retries_used,
            max_retries=max_retries,
            has_recoverable_gap=gap,
            authorized_next_source="src-next" if has_src else None,
            has_permanent_veto=veto,
            new_evidence_found=new_ev,
            resolved=resolved,
            candidate_id="att-p",
        )
    )
    if retries_used >= 2:
        assert dec.action == "terminal"
    assert dec.hop_increment == (1 if dec.action == "retry" else 0)


def test_dvss_p07_binding_escalation_and_consequential_flags() -> None:
    """T-UNIT-FN-P07-01..04: One-time Regulator escalation & consequential function flags."""
    _validate_fn_contract(
        "p07",
        "in",
        {
            "tier": 1,
            "s_score": 1,
            "z_flag": 0,
            "active_roles": ["scholar"],
            "has_binding_claim": True,
            "escalated_once": False,
            "consequential_tool_used": False,
        },
    )
    esc1 = evaluate_binding_escalation(
        tier=1,
        s_score=1,
        z_flag=0,
        active_roles=["scholar"],
        has_binding_claim=True,
        escalated_once=False,
    )
    assert esc1.should_escalate is True
    assert esc1.new_tier == 2 and esc1.new_s_eff == 3
    assert "regulator" in esc1.new_roles and "practitioner" in esc1.new_roles
    _validate_fn_contract(
        "p07",
        "out",
        {
            "should_escalate": esc1.should_escalate,
            "new_tier": esc1.new_tier,
            "new_s_eff": esc1.new_s_eff,
            "new_roles": list(esc1.new_roles),
            "reason": esc1.reason,
        },
    )

    # Strictly one-time: second call with escalated_once=True refuses escalation
    esc2 = evaluate_binding_escalation(
        tier=2,
        s_score=3,
        z_flag=0,
        active_roles=["scholar", "practitioner"],
        has_binding_claim=True,
        escalated_once=True,
    )
    assert esc2.should_escalate is False and esc2.reason == "already_escalated"

    # Consequential tool flag hits cleanly without blocking
    flags_cfg = FunctionFlagsConfig(
        schema_version="1.0.0",
        consequential_functions=(
            ConsequentialFunctionFlag(
                name="submit_purchase_order",
                reason="Creates a financial commitment",
            ),
        ),
    )
    hits = check_consequential_functions(
        contents=[
            {
                "role": "function",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "submit_purchase_order",
                            "response": {"po_id": "PO-101"},
                        }
                    }
                ],
            }
        ],
        function_flags=flags_cfg,
    )
    assert len(hits) == 1 and hits[0].name == "submit_purchase_order"

    esc_tool = evaluate_binding_escalation(
        tier=1,
        s_score=0,
        z_flag=0,
        active_roles=["scholar"],
        has_binding_claim=False,
        escalated_once=False,
        consequential_tool_used=True,
    )
    assert esc_tool.should_escalate is True
    assert esc_tool.reason == "consequential_tool_requires_regulator"


def test_frost_layers_mapping_and_trace() -> None:
    """Verify all 12 steps and 10 FROST layers map canonically without unknown IDs."""
    assert len(STEP_IDS) == 12
    assert len(FROST_LAYERS) == 10
    assert set(STEP_TO_LAYER.values()) <= set(FROST_LAYERS)

    trace = FrostTrace()
    for step in STEP_IDS:
        if step == "s05_deliberate":
            trace.record(
                step_id=step,
                attempt_id="att-0",
                event="initial",
                status="ok",
                dvss_ids=("DVSS-K03",),
                layer_override="l03_persona_selection",
            )
        trace.record(step_id=step, attempt_id="att-0", event="initial", status="ok")
    assert trace.completed_steps() == STEP_IDS
    assert trace.completed_layers() == FROST_LAYERS
    meta = trace.to_metadata_list()
    assert len(meta) == 13 and all("stepId" in item and "layerId" in item for item in meta)

    with pytest.raises(ValueError, match="unknown DLE step_id"):
        trace.record(step_id="s99_invalid", attempt_id="att-0", event="initial", status="ok")
