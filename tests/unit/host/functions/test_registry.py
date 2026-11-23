"""Unit tests for H16 FunctionRegistry (P1-14, FR-FN-01..04, ADR-009, ADR-010)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dle.config import load_config
from dle.errors import IllegalHoldError, KernelNotOptional, UnboundFunction
from dle.host.functions import (
    FunctionContext,
    FunctionRecord,
    FunctionRegistry,
    FunctionResult,
    register_phase1_functions,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_missing_kernel_fails_self_check_and_ka_dispatch_rejected():
    """T-ENG-FN-01: startup self-check rejects missing kernel; KA-* IDs raise UnboundFunction."""
    cfg = load_config(REPO_ROOT / "config")
    reg = FunctionRegistry(cfg.functions, cfg.profiles)
    reg.register("DVSS-K01", lambda _ctx: FunctionResult("ok", {}))

    with pytest.raises(UnboundFunction, match="DVSS-K02"):
        reg.self_check()

    register_phase1_functions(reg, cfg.notices)
    reg.self_check()

    ctx = FunctionContext(run_id="r1", attempt_id="a1", profile="strict", payload={})
    legacy_id = "KA-" + "015"
    with pytest.raises(UnboundFunction, match="DVSS"):
        reg.invoke(legacy_id, ctx)

    with pytest.raises(KernelNotOptional):
        reg.register(
            "DVSS-K01",
            lambda _ctx: FunctionResult("ok", {}),
            implementation="adapter",
            adapter_id="ext",
        )


def test_hold_authority_and_profile_policy_skip_vs_fallback():
    """T-ENG-FN-02: only K04/K11/K12 may hold; kernel_only skips P01 and runs P07 fallback."""
    cfg = load_config(REPO_ROOT / "config")
    reg = FunctionRegistry(cfg.functions, cfg.profiles)
    register_phase1_functions(reg, cfg.notices)
    reg.register("DVSS-P01", lambda _ctx: FunctionResult("hold", {}))
    reg.register("DVSS-P11", lambda _ctx: FunctionResult("ok", {"falsification": True}))

    ctx_strict_t1 = FunctionContext(
        run_id="r2", attempt_id="a1", profile="strict", payload={}, tier=1
    )
    with pytest.raises(IllegalHoldError, match="DVSS-P01"):
        reg.invoke("DVSS-P01", ctx_strict_t1)

    records: list[FunctionRecord] = []
    # Tier 1 under strict skips P11 (which is configured as tier3)
    res_p11_t1 = reg.invoke("DVSS-P11", ctx_strict_t1, records=records)
    assert res_p11_t1.outcome == "skipped"

    # Tier 3 under strict runs P11
    ctx_strict_t3 = FunctionContext(
        run_id="r2", attempt_id="a1", profile="strict", payload={}, tier=3
    )
    res_p11_t3 = reg.invoke("DVSS-P11", ctx_strict_t3, records=records)
    assert res_p11_t3.outcome == "ok"

    # kernel_only runs P07 host fallback even with empty policy_functions
    ctx_konly = FunctionContext(
        run_id="r3",
        attempt_id="a1",
        profile="kernel_only",
        payload={"has_binding": True, "has_regulator": False},
    )
    res_p07 = reg.invoke("DVSS-P07", ctx_konly, records=records)
    assert res_p07.output["escalate"] is True
    assert records[-1].implementation == "host_fallback"


def test_handler_exception_records_error_outcome():
    """T-ENG-FN-03: unexpected handler exception fails closed as outcome='error'."""
    cfg = load_config(REPO_ROOT / "config")
    reg = FunctionRegistry(cfg.functions, cfg.profiles)
    register_phase1_functions(reg, cfg.notices)

    def broken(_ctx: FunctionContext) -> FunctionResult:
        raise RuntimeError("boom")

    reg.register("DVSS-P02", broken)
    records: list[FunctionRecord] = []
    res = reg.invoke(
        "DVSS-P02",
        FunctionContext(run_id="r4", attempt_id="a1", profile="strict", payload={}),
        records=records,
    )
    assert res.outcome == "error"
    assert res.output == {"error_type": "RuntimeError"}
    assert records[0].outcome == "error"
