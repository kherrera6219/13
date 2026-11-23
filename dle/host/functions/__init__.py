"""H16 bound function dispatcher and Phase 1 kernel/fallback registrations."""

from dle.host.functions.registry import (
    HOLD_ALLOWED_DVSS_IDS,
    KERNEL_DVSS_IDS,
    FunctionContext,
    FunctionHandler,
    FunctionRecord,
    FunctionRegistry,
    FunctionResult,
)
from dle.host.functions.stubs import register_phase1_functions

__all__ = [
    "HOLD_ALLOWED_DVSS_IDS",
    "KERNEL_DVSS_IDS",
    "FunctionContext",
    "FunctionHandler",
    "FunctionRecord",
    "FunctionRegistry",
    "FunctionResult",
    "register_phase1_functions",
]
