"""Phase 1 governed-path stub orchestrator (`H1`).

Implements FR-WF-01 (stub) and AGENTS.md rule 11 (fail closed). Dispatches
``DVSS-K01`` and ``DVSS-K10`` through ``FunctionRegistry``, calls the pinned
writer model through ``ModelPort``, and returns ``released_advisory`` (or a
fail-closed ``held`` outcome on upstream unavailability or internal error).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dle.edge.translator import RunRequest
from dle.errors import ModelUnavailable
from dle.host.functions import FunctionContext, FunctionRecord, FunctionRegistry
from dle.models import ModelPort, ModelRegistry
from dle.observability import get_logger


@dataclass(frozen=True)
class GovernedStubResult:
    """Outcome of executing the Phase 1 governed-path stub."""

    release_mode: Literal["released", "released_advisory", "held"]
    receipt_id: str
    tier: int
    body: dict[str, object] | None
    notice_id: str | None
    notice_context: dict[str, object]
    hold_reason: str | None
    function_records: tuple[FunctionRecord, ...]


async def run_governed_stub(
    *,
    run_req: RunRequest,
    function_registry: FunctionRegistry,
    model_registry: ModelRegistry,
    model_port: ModelPort,
    api_key: str,
) -> GovernedStubResult:
    """Run the Phase 1 governed stub pipeline, failing closed on unexpected errors."""
    log = get_logger("dle.host.workflow.stub")
    profile = run_req.profile or "strict"
    attempt_id = "att-0"
    records: list[FunctionRecord] = []

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
            return GovernedStubResult(
                release_mode="held",
                receipt_id=run_req.run_id,
                tier=1,
                body=None,
                notice_id="NOTICE-HOLD-07",
                notice_context={"receipt_id": run_req.run_id},
                hold_reason="internal_error",
                function_records=tuple(records),
            )

        k10_res = function_registry.invoke(
            "DVSS-K10",
            FunctionContext(
                run_id=run_req.run_id,
                attempt_id=attempt_id,
                profile=profile,
                payload={
                    "d": 0,
                    "r": 0,
                    "m": 0,
                    "binding": False,
                    "z_hit": False,
                },
            ),
            records=records,
        )
        raw_tier = k10_res.output.get("tier", 1)
        tier = int(raw_tier) if isinstance(raw_tier, int | float) else 1

        writer_model = model_registry.pin_for_job("writer")
        writer_res = await model_port.generate(
            writer_model,
            run_req.raw_body,
            api_key=api_key,
            job="writer",
        )
        return GovernedStubResult(
            release_mode="released_advisory",
            receipt_id=run_req.run_id,
            tier=tier,
            body=writer_res.body,
            notice_id=None,
            notice_context={},
            hold_reason=None,
            function_records=tuple(records),
        )
    except ModelUnavailable:
        log.warning("workflow.stub_model_unavailable", run_id=run_req.run_id)
        return GovernedStubResult(
            release_mode="held",
            receipt_id=run_req.run_id,
            tier=1,
            body=None,
            notice_id="NOTICE-HOLD-06",
            notice_context={},
            hold_reason="model_unavailable",
            function_records=tuple(records),
        )
    except Exception as exc:
        log.error(
            "workflow.stub_internal_error",
            run_id=run_req.run_id,
            error_type=type(exc).__name__,
        )
        return GovernedStubResult(
            release_mode="held",
            receipt_id=run_req.run_id,
            tier=1,
            body=None,
            notice_id="NOTICE-HOLD-07",
            notice_context={"receipt_id": run_req.run_id},
            hold_reason="internal_error",
            function_records=tuple(records),
        )


__all__ = ["GovernedStubResult", "run_governed_stub"]
