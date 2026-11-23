"""H16 single registry dispatching all bound DVSS functions by DVSS ID only.

Implements FR-FN-01, FR-FN-02, FR-FN-04, FR-FN-08, ADR-009, ADR-010, and
AGENTS.md rules 4-6. Legacy catalog identifiers are rejected with
``UnboundFunction``, kernel bindings ``DVSS-K01``..``DVSS-K12`` must all be
present as host code at startup, and only ``DVSS-K04``, ``DVSS-K11``, and
``DVSS-K12`` may return ``outcome == "hold"``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from dle.config.loader import compute_policy_digest
from dle.config.models import FunctionBinding, FunctionsConfig, ProfileConfig
from dle.errors import ConfigError, IllegalHoldError, KernelNotOptional, UnboundFunction
from dle.observability import get_logger

HOLD_ALLOWED_DVSS_IDS: frozenset[str] = frozenset({"DVSS-K04", "DVSS-K11", "DVSS-K12"})
KERNEL_DVSS_IDS: frozenset[str] = frozenset(f"DVSS-K{i:02d}" for i in range(1, 13))

FunctionImplementation = Literal["host", "adapter", "host_fallback"]
FunctionOutcome = Literal["ok", "skipped", "flag", "objection", "hold", "error"]


@dataclass(frozen=True)
class FunctionRecord:
    """Append-only invocation record conforming to receipt schema 3.8.0."""

    seq: int
    attempt_id: str
    dvss_id: str
    version: str
    level: Literal["kernel", "policy"]
    implementation: FunctionImplementation
    adapter_id: str | None
    outcome: FunctionOutcome
    input_sha256: str
    output_sha256: str
    duration_ms: float

    def to_receipt_dict(self) -> dict[str, object]:
        """Serialize into the exact JSON object shape expected by ``receipt.schema.json``."""
        return {
            "seq": self.seq,
            "attempt_id": self.attempt_id,
            "dvss_id": self.dvss_id,
            "version": self.version,
            "level": self.level,
            "implementation": self.implementation,
            "adapter_id": self.adapter_id,
            "outcome": self.outcome,
            "input_sha256": self.input_sha256,
            "output_sha256": self.output_sha256,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class FunctionResult:
    """Outcome and JSON-compatible output payload returned by a bound function handler."""

    outcome: FunctionOutcome
    output: dict[str, object]


@dataclass
class FunctionContext:
    """Execution context supplied to bound DVSS handlers."""

    run_id: str
    attempt_id: str
    profile: str
    payload: dict[str, object]
    tier: int = 1


FunctionHandler = Callable[[FunctionContext], FunctionResult]


@dataclass(frozen=True)
class _RegisteredSlot:
    handler: FunctionHandler
    implementation: Literal["host", "adapter"]
    adapter_id: str | None


class FunctionRegistry:
    """Central H16 registry enforcing DVSS IDs, kernel presence, and hold authority."""

    def __init__(
        self,
        functions_cfg: FunctionsConfig,
        profiles: Mapping[str, ProfileConfig],
    ) -> None:
        """Initialize bindings from validated ``functions.yaml`` and release profiles."""
        self._bindings: dict[str, FunctionBinding] = {fn.id: fn for fn in functions_cfg.functions}
        self._profiles: dict[str, ProfileConfig] = dict(profiles)
        self._slots: dict[str, _RegisteredSlot] = {}
        self._fallbacks: dict[str, FunctionHandler] = {}
        self._log = get_logger("dle.host.functions.registry")

    def register(
        self,
        dvss_id: str,
        handler: FunctionHandler,
        *,
        implementation: Literal["host", "adapter"] = "host",
        adapter_id: str | None = None,
        fallback: FunctionHandler | None = None,
    ) -> None:
        """Register a handler (and optional host fallback) for a bound DVSS ID."""
        if dvss_id.startswith("KA-") or dvss_id not in self._bindings:
            raise UnboundFunction(f"cannot register unknown or legacy identifier {dvss_id!r}")
        binding = self._bindings[dvss_id]
        if binding.level == "kernel" and implementation != "host":
            raise KernelNotOptional(
                f"kernel function {dvss_id} must use host implementation, got {implementation!r}"
            )
        if implementation == "adapter" and not adapter_id:
            raise UnboundFunction(f"adapter registration for {dvss_id} requires adapter_id")

        self._slots[dvss_id] = _RegisteredSlot(
            handler=handler,
            implementation=implementation,
            adapter_id=adapter_id,
        )
        if fallback is not None:
            self._fallbacks[dvss_id] = fallback

    def register_fallback(self, dvss_id: str, fallback: FunctionHandler) -> None:
        """Register a required host fallback for a policy binding."""
        if dvss_id not in self._bindings:
            raise UnboundFunction(f"cannot register fallback for unknown ID {dvss_id!r}")
        self._fallbacks[dvss_id] = fallback

    def self_check(self) -> None:
        """Verify all 12 kernel bindings and required policy fallbacks are registered."""
        missing_kernel = sorted(kid for kid in KERNEL_DVSS_IDS if kid not in self._slots)
        if missing_kernel:
            raise UnboundFunction(
                "startup self-check failed; missing kernel binding(s): "
                + ", ".join(missing_kernel),
                details={"missing": missing_kernel},
            )
        missing_fallbacks = sorted(
            fn.id
            for fn in self._bindings.values()
            if fn.host_fallback == "required"
            and fn.id not in self._fallbacks
            and fn.id not in self._slots
        )
        if missing_fallbacks:
            raise UnboundFunction(
                "startup self-check failed; missing required host fallback(s): "
                + ", ".join(missing_fallbacks),
                details={"missing_fallbacks": missing_fallbacks},
            )

    def invoke(
        self,
        dvss_id: str,
        ctx: FunctionContext,
        *,
        records: list[FunctionRecord] | None = None,
    ) -> FunctionResult:
        """Invoke a bound function by DVSS ID and optionally append a ``FunctionRecord``."""
        if dvss_id.startswith("KA-"):
            raise UnboundFunction(
                f"legacy catalog ID {dvss_id!r} cannot be dispatched; use DVSS IDs only"
            )
        binding = self._bindings.get(dvss_id)
        if binding is None:
            raise UnboundFunction(f"unregistered DVSS function ID {dvss_id!r}")

        profile = self._profiles.get(ctx.profile)
        if profile is None:
            raise ConfigError(f"unknown release profile {ctx.profile!r}")

        seq = len(records) if records is not None else 0
        input_sha = compute_policy_digest(ctx.payload)
        start = time.perf_counter()

        handler: FunctionHandler | None = None
        implementation: FunctionImplementation = "host"
        adapter_id: str | None = None

        if binding.level == "kernel":
            slot = self._slots.get(dvss_id)
            if slot is None:
                raise UnboundFunction(f"kernel function {dvss_id} has no registered handler")
            handler = slot.handler
            implementation = slot.implementation
            adapter_id = slot.adapter_id
        else:
            toggle = profile.policy_functions.get(dvss_id, "off")
            policy_active = toggle == "on" or (toggle == "tier3" and ctx.tier >= 3)
            if policy_active and dvss_id in self._slots:
                slot = self._slots[dvss_id]
                handler = slot.handler
                implementation = slot.implementation
                adapter_id = slot.adapter_id
            elif binding.host_fallback == "required":
                fb = self._fallbacks.get(dvss_id) or (
                    self._slots[dvss_id].handler if dvss_id in self._slots else None
                )
                if fb is None:
                    raise UnboundFunction(
                        f"policy function {dvss_id} missing required host fallback"
                    )
                handler = fb
                implementation = "host_fallback"
            else:
                result = FunctionResult(outcome="skipped", output={"reason": "disabled_by_profile"})
                self._append_record(
                    records=records,
                    seq=seq,
                    ctx=ctx,
                    binding=binding,
                    implementation="host",
                    adapter_id=None,
                    result=result,
                    input_sha=input_sha,
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                )
                return result

        try:
            result = handler(ctx)
        except (IllegalHoldError, UnboundFunction):
            raise
        except Exception as exc:
            result = FunctionResult(
                outcome="error",
                output={"error_type": type(exc).__name__},
            )

        if result.outcome == "hold" and dvss_id not in HOLD_ALLOWED_DVSS_IDS:
            raise IllegalHoldError(
                f"function {dvss_id} is not permitted to return outcome='hold'",
                details={"dvss_id": dvss_id},
            )

        duration_ms = (time.perf_counter() - start) * 1000.0
        self._append_record(
            records=records,
            seq=seq,
            ctx=ctx,
            binding=binding,
            implementation=implementation,
            adapter_id=adapter_id,
            result=result,
            input_sha=input_sha,
            duration_ms=duration_ms,
        )
        return result

    def _append_record(
        self,
        *,
        records: list[FunctionRecord] | None,
        seq: int,
        ctx: FunctionContext,
        binding: FunctionBinding,
        implementation: FunctionImplementation,
        adapter_id: str | None,
        result: FunctionResult,
        input_sha: str,
        duration_ms: float,
    ) -> None:
        output_sha = compute_policy_digest(result.output)
        record = FunctionRecord(
            seq=seq,
            attempt_id=ctx.attempt_id,
            dvss_id=binding.id,
            version=binding.version,
            level=binding.level,
            implementation=implementation,
            adapter_id=adapter_id,
            outcome=result.outcome,
            input_sha256=input_sha,
            output_sha256=output_sha,
            duration_ms=round(duration_ms, 3),
        )
        self._log.info(
            "function.invoked",
            run_id=ctx.run_id,
            attempt_id=ctx.attempt_id,
            dvss_id=binding.id,
            implementation=implementation,
            outcome=result.outcome,
            duration_ms=record.duration_ms,
        )
        if records is not None:
            records.append(record)


__all__ = [
    "HOLD_ALLOWED_DVSS_IDS",
    "KERNEL_DVSS_IDS",
    "FunctionContext",
    "FunctionHandler",
    "FunctionImplementation",
    "FunctionOutcome",
    "FunctionRecord",
    "FunctionRegistry",
    "FunctionResult",
]
