"""Strict Pydantic v2 models for ``config/`` artifacts.

Implements FR-FN-03, FR-TIER-01..04, NFR-SEC-03, NFR-COST-01, FR-RCPT-01..03,
and ADR-009/ADR-010 invariants.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dle.errors import ConfigError, KernelNotOptional

KERNEL_FUNCTION_IDS: frozenset[str] = frozenset(f"DVSS-K{i:02d}" for i in range(1, 13))
HOLD_CAPABLE_IDS: frozenset[str] = frozenset({"DVSS-K04", "DVSS-K11", "DVSS-K12"})

ReleaseModeLiteral = Literal["released", "released_advisory", "held"]
PolicyToggle = Literal["on", "off", "tier3"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FunctionPermissions(_StrictModel):
    """Read and write scopes permitted to a bound DVSS function."""

    reads: tuple[str, ...]
    writes: tuple[str, ...]


class FunctionBinding(_StrictModel):
    """Single bound function entry in ``config/functions.yaml``."""

    id: str = Field(pattern=r"^DVSS-(K(0[1-9]|1[0-2])|P(0[1-9]|1[0-4]))$")
    name: str = Field(min_length=1)
    level: Literal["kernel", "policy"]
    legacy_ka: str = Field(pattern=r"^KA-\d{3}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    hooks: tuple[str, ...] = Field(min_length=1)
    layers: tuple[str, ...]
    component: str = Field(min_length=1)
    can_hold: bool
    host_fallback: Literal["none", "required"] | None = None
    runtime: bool = True
    permissions: FunctionPermissions


class FunctionsConfig(_StrictModel):
    """Validated ``config/functions.yaml`` enforcing kernel non-optionality and hold limits."""

    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    functions: tuple[FunctionBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _enforce_kernel_and_hold_rules(self) -> FunctionsConfig:
        seen: set[str] = set()
        for fn in self.functions:
            if fn.id in seen:
                raise ConfigError(f"duplicate DVSS function binding {fn.id}")
            seen.add(fn.id)

            if fn.id.startswith("DVSS-K"):
                if fn.level != "kernel" or not fn.runtime:
                    raise KernelNotOptional(
                        f"kernel function {fn.id} must remain level='kernel' and runtime=true"
                    )
            elif fn.level != "policy":
                raise ConfigError(f"policy function {fn.id} cannot claim level='kernel'")

            if fn.can_hold and fn.id not in HOLD_CAPABLE_IDS:
                raise ConfigError(
                    f"only DVSS-K04, DVSS-K11, and DVSS-K12 may produce holds; got {fn.id}"
                )

        missing_kernel = sorted(KERNEL_FUNCTION_IDS - seen)
        if missing_kernel:
            raise KernelNotOptional(
                f"missing mandatory kernel function(s): {', '.join(missing_kernel)}",
                details={"missing": missing_kernel},
            )
        return self


class ReleaseMapping(_StrictModel):
    """Mapping from gate outcomes to public API release modes."""

    below_cutoff: ReleaseModeLiteral
    at_or_above_cutoff: ReleaseModeLiteral
    drift_latched: ReleaseModeLiteral


class ProfileConfig(_StrictModel):
    """Validated release profile (resolved with any ``extends`` parent)."""

    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    release: ReleaseMapping
    alpha: float = Field(gt=0.0, lt=1.0)
    policy_functions: dict[str, PolicyToggle]
    blinded_assurance_roles: bool = False
    extends: str | None = None

    @model_validator(mode="after")
    def _reject_kernel_toggles(self) -> ProfileConfig:
        for fn_id in self.policy_functions:
            if fn_id.startswith("DVSS-K"):
                raise KernelNotOptional(
                    f"profile {self.name!r} cannot toggle kernel function {fn_id}",
                    details={"profile": self.name, "dvss_id": fn_id},
                )
        return self


class TierSpec(_StrictModel):
    """Execution depth and call budget specification for a single tier."""

    tier: Literal[1, 2, 3]
    s_eff: tuple[int, int]
    roles: tuple[str, ...] | Literal["all_when_b_or_z_else_relevant"]
    on_demand: dict[str, str] = Field(default_factory=dict)
    starting_hops: int = Field(ge=1)
    max_retries: int = Field(ge=0, le=2)
    max_hops: int = Field(ge=1)
    escalation: str = Field(min_length=1)
    max_model_calls: int = Field(ge=1)
    max_model_calls_escalated: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_bounds(self) -> TierSpec:
        if self.s_eff[0] < 0 or self.s_eff[0] > self.s_eff[1]:
            raise ConfigError(f"tier {self.tier} invalid s_eff bounds: {self.s_eff}")
        if self.starting_hops > self.max_hops:
            raise ConfigError(
                f"tier {self.tier} starting_hops ({self.starting_hops}) "
                f"exceeds max_hops ({self.max_hops})"
            )
        return self


class GraphLimits(_StrictModel):
    """Bounded graph expansion and PPR convergence limits."""

    max_vertices: int = Field(ge=1)
    ppr_damping: float = Field(gt=0.0, lt=1.0)
    ppr_max_iterations: int = Field(ge=1)
    ppr_tolerance: float = Field(gt=0.0)


class DistanceWeights(_StrictModel):
    """Strictly positive distance weights per DLE-SPC-003 §5."""

    w3: float = Field(gt=0.0)
    w67: float = Field(gt=0.0)


class TiersConfig(_StrictModel):
    """Validated ``config/tiers.yaml``."""

    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    s_eff: str = Field(min_length=1)
    tiers: tuple[TierSpec, ...] = Field(min_length=3, max_length=3)
    graph_limits: GraphLimits
    distance_weights: DistanceWeights

    @model_validator(mode="after")
    def _validate_tier_set(self) -> TiersConfig:
        if {t.tier for t in self.tiers} != {1, 2, 3}:
            raise ConfigError("tiers.yaml must define exactly tiers 1, 2, and 3")
        return self


class EgressAllowRule(_StrictModel):
    """Single allowed outbound host and TCP port."""

    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    purpose: str = Field(min_length=1)


class EgressConfig(_StrictModel):
    """Validated ``config/egress.yaml`` allowlist."""

    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    allow: tuple[EgressAllowRule, ...]


class DatedPrice(BaseModel):
    """Dated per-million-token pricing entry using half-open ``[from, to)`` dates."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    from_date: date = Field(alias="from")
    to_date: date | None = Field(default=None, alias="to")
    input: float = Field(ge=0.0)
    output: float = Field(ge=0.0)
    cached_input: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _validate_window(self) -> DatedPrice:
        if self.to_date is not None and self.from_date >= self.to_date:
            raise ConfigError(
                f"invalid price interval [{self.from_date}, {self.to_date}): "
                "'from' must precede 'to'"
            )
        return self


class LocalModelPin(_StrictModel):
    """Pinned local auxiliary model identifier and SHA-256 digest."""

    id: str = Field(min_length=1)
    sha256: str = Field(min_length=1)


class ModelPinsConfig(_StrictModel):
    """Validated ``config/model_pins.yaml``."""

    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    jobs: dict[str, str] = Field(min_length=1)
    prices_usd_per_million_tokens: dict[str, tuple[DatedPrice, ...]]
    local_models: dict[str, LocalModelPin] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_job_prices(self) -> ModelPinsConfig:
        for job_name, model_id in self.jobs.items():
            entries = self.prices_usd_per_million_tokens.get(model_id)
            if not entries:
                raise ConfigError(
                    f"job {job_name!r} pins model {model_id!r} with no price schedule"
                )
        return self


class NoticeTemplate(_StrictModel):
    """Single user-facing notice template from ``config/notices.yaml``."""

    id: str = Field(pattern=r"^NOTICE-[A-Z]+-\d{2}$")
    when: str = Field(min_length=1)
    badge: str = Field(min_length=1)
    text: str = Field(min_length=1)


class NoticesConfig(_StrictModel):
    """Validated ``config/notices.yaml``."""

    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    notices: tuple[NoticeTemplate, ...] = Field(min_length=1)


class ReceiptsConfig(_StrictModel):
    """Validated ``config/receipts.yaml``."""

    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    anchoring_profile: Literal[
        "local_worm_merkle",
        "customer_hosted_log",
        "external_transparency_log",
    ]
    merkle_checkpoint_every: int = Field(ge=1)
    retention_years: int = Field(ge=1)
    signature: Literal["ed25519"]
    canonicalization: Literal["jcs_rfc8785"]


class ConsequentialFunctionFlag(_StrictModel):
    """Client tool flagged consequential for mandatory Regulator claim review."""

    name: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class FunctionFlagsConfig(_StrictModel):
    """Validated ``config/function_flags.yaml``."""

    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    consequential_functions: tuple[ConsequentialFunctionFlag, ...] = ()


class RoleConduct(_StrictModel):
    """Persona conduct guardrails and synthesis weight for one Quad role."""

    role_name: str = Field(min_length=1)
    traits: tuple[str, ...]
    must: tuple[str, ...]
    must_not: tuple[str, ...]
    veto_on: tuple[str, ...]
    synthesis_weight: float = Field(gt=0.0, le=1.0)


class PersonaConductConfig(_StrictModel):
    """Validated ``config/personas/conduct.yaml``."""

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    axis8: RoleConduct
    axis9: RoleConduct
    axis10: RoleConduct
    axis11: RoleConduct

    @model_validator(mode="after")
    def _validate_weights(self) -> PersonaConductConfig:
        total = (
            self.axis8.synthesis_weight
            + self.axis9.synthesis_weight
            + self.axis10.synthesis_weight
            + self.axis11.synthesis_weight
        )
        if abs(total - 1.0) > 1e-6:
            raise ConfigError(f"persona conduct synthesis_weight must sum to 1.0, got {total}")
        return self


class DleConfig(_StrictModel):
    """Complete validated middleware configuration with deterministic JCS policy SHA-256."""

    functions: FunctionsConfig
    profiles: dict[str, ProfileConfig]
    tiers: TiersConfig
    egress: EgressConfig
    model_pins: ModelPinsConfig
    notices: NoticesConfig
    receipts: ReceiptsConfig
    function_flags: FunctionFlagsConfig
    conduct: PersonaConductConfig
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
