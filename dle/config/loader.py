"""Configuration loader and RFC 8785 (JCS) policy digest computation.

Implements FR-FN-03 and ADR-010. Identical configuration trees in any dict
key order yield the exact same ``policy_sha256`` digest. Any attempt to omit
or disable a kernel function raises ``KernelNotOptional``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path

import rfc8785
import yaml
from pydantic import BaseModel, ValidationError

from dle.config.models import (
    DleConfig,
    EgressConfig,
    FunctionFlagsConfig,
    FunctionsConfig,
    ModelPinsConfig,
    NoticesConfig,
    PersonaConductConfig,
    PolicyToggle,
    ProfileConfig,
    ReceiptsConfig,
    TiersConfig,
)
from dle.errors import ConfigError, KernelNotOptional

type _JsonScalar = bool | int | str | float | None
type _JsonValue = _JsonScalar | Sequence[_JsonValue] | Mapping[str, _JsonValue]


def _coerce_jcs_value(value: object) -> _JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Mapping):
        return {str(k): _coerce_jcs_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_coerce_jcs_value(item) for item in value]
    raise ConfigError(f"value of type {type(value).__name__} is not JCS JSON serializable")


def canonicalize_jcs(payload: Mapping[str, object]) -> bytes:
    """Return RFC 8785 JCS canonical UTF-8 bytes for ``payload``."""
    normalized: dict[str, _JsonValue] = {str(k): _coerce_jcs_value(v) for k, v in payload.items()}
    return rfc8785.dumps(normalized)


def compute_policy_digest(payload: Mapping[str, object]) -> str:
    """Return lowercase hex SHA-256 of the RFC 8785 JCS canonicalization of ``payload``."""
    return hashlib.sha256(canonicalize_jcs(payload)).hexdigest()


def _read_yaml_mapping(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ConfigError(f"required config file missing: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"failed to parse YAML {path.name}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"config file {path.name} must contain a top-level mapping")
    return {str(k): v for k, v in loaded.items()}


def _validate_model[ModelT: BaseModel](
    model_cls: type[ModelT], raw: Mapping[str, object], source: str
) -> ModelT:
    try:
        return model_cls.model_validate(dict(raw))
    except (KernelNotOptional, ConfigError):
        raise
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration in {source}: {exc}") from exc


def _normalize_toggle(raw_value: object, *, profile: str, fn_id: str) -> PolicyToggle:
    # Check bool before int because bool is a subclass of int.
    if isinstance(raw_value, bool):
        return "on" if raw_value else "off"
    if raw_value in ("on", "off", "tier3") and isinstance(raw_value, str):
        return raw_value
    raise ConfigError(
        f"profile {profile!r} function {fn_id} has invalid toggle {raw_value!r}; "
        "expected 'on', 'off', or 'tier3'"
    )


def _guard_kernel_in_raw_profile(raw: Mapping[str, object], profile_name: str) -> None:
    if "kernel_functions" in raw:
        raise KernelNotOptional(
            f"profile {profile_name!r} attempts to configure kernel_functions",
            details={"profile": profile_name},
        )
    raw_policy = raw.get("policy_functions")
    if isinstance(raw_policy, Mapping):
        for fn_id in raw_policy:
            if str(fn_id).startswith("DVSS-K"):
                raise KernelNotOptional(
                    f"profile {profile_name!r} attempts to override kernel function {fn_id}",
                    details={"profile": profile_name, "dvss_id": str(fn_id)},
                )


def _resolve_profile_dict(
    name: str,
    raw_profiles: Mapping[str, dict[str, object]],
    known_policy_ids: frozenset[str],
    stack: list[str],
    cache: dict[str, dict[str, object]],
) -> dict[str, object]:
    if name in cache:
        return dict(cache[name])
    if name in stack:
        cycle = " -> ".join([*stack, name])
        raise ConfigError(f"profile inheritance cycle detected: {cycle}")
    if name not in raw_profiles:
        raise ConfigError(f"profile references missing parent {name!r}")

    raw = raw_profiles[name]
    _guard_kernel_in_raw_profile(raw, name)

    parent_name = raw.get("extends")
    merged: dict[str, object]
    if parent_name is not None:
        if not isinstance(parent_name, str) or not parent_name:
            raise ConfigError(f"profile {name!r} has invalid 'extends' value: {parent_name!r}")
        parent = _resolve_profile_dict(
            parent_name, raw_profiles, known_policy_ids, [*stack, name], cache
        )
        parent_release = parent.get("release")
        merged_release: dict[str, object] = (
            {str(k): v for k, v in parent_release.items()}
            if isinstance(parent_release, Mapping)
            else {}
        )
        parent_policy = parent.get("policy_functions")
        merged_policy: dict[str, object] = (
            {str(k): v for k, v in parent_policy.items()}
            if isinstance(parent_policy, Mapping)
            else {}
        )
        raw_release = raw.get("release")
        if isinstance(raw_release, Mapping):
            merged_release.update({str(k): v for k, v in raw_release.items()})
        raw_policy_override = raw.get("policy_functions")
        if isinstance(raw_policy_override, Mapping):
            merged_policy.update({str(k): v for k, v in raw_policy_override.items()})
        merged = {
            "schema_version": raw.get("schema_version", parent["schema_version"]),
            "name": raw.get("name", name),
            "release": merged_release,
            "alpha": raw.get("alpha", parent["alpha"]),
            "policy_functions": merged_policy,
            "blinded_assurance_roles": raw.get(
                "blinded_assurance_roles", parent.get("blinded_assurance_roles", False)
            ),
            "extends": parent_name,
        }
    else:
        merged = dict(raw)

    raw_policy = merged.get("policy_functions")
    if raw_policy is None:
        raw_policy = {}
    if not isinstance(raw_policy, Mapping):
        raise ConfigError(f"profile {name!r} field 'policy_functions' must be a mapping")

    normalized_policy: dict[str, PolicyToggle] = {}
    for k, v in raw_policy.items():
        fn_id = str(k)
        if fn_id.startswith("DVSS-K"):
            raise KernelNotOptional(
                f"profile {name!r} cannot toggle kernel function {fn_id}",
                details={"profile": name, "dvss_id": fn_id},
            )
        if fn_id not in known_policy_ids:
            raise ConfigError(f"profile {name!r} references unknown policy function {fn_id!r}")
        normalized_policy[fn_id] = _normalize_toggle(v, profile=name, fn_id=fn_id)

    merged["policy_functions"] = normalized_policy
    cache[name] = merged
    return dict(merged)


def _load_profiles(
    profiles_dir: Path, known_policy_ids: frozenset[str]
) -> dict[str, ProfileConfig]:
    if not profiles_dir.is_dir():
        raise ConfigError(f"profiles directory missing: {profiles_dir}")
    paths = sorted(profiles_dir.glob("*.yaml"))
    if not paths:
        raise ConfigError(f"no profile YAML files found in {profiles_dir}")

    raw_profiles: dict[str, dict[str, object]] = {}
    for path in paths:
        raw = _read_yaml_mapping(path)
        profile_name = str(raw.get("name") or path.stem)
        if profile_name in raw_profiles:
            raise ConfigError(f"duplicate profile name {profile_name!r}")
        raw_profiles[profile_name] = raw

    resolved_cache: dict[str, dict[str, object]] = {}
    profiles: dict[str, ProfileConfig] = {}
    for name in sorted(raw_profiles):
        resolved = _resolve_profile_dict(name, raw_profiles, known_policy_ids, [], resolved_cache)
        profiles[name] = _validate_model(ProfileConfig, resolved, f"config/profiles/{name}.yaml")
    return profiles


def load_config(config_dir: Path) -> DleConfig:
    """Load, validate, and compute the JCS SHA-256 policy digest for ``config_dir``."""
    root = config_dir.resolve()
    if not root.is_dir():
        raise ConfigError(f"config directory does not exist: {root}")

    functions = _validate_model(
        FunctionsConfig, _read_yaml_mapping(root / "functions.yaml"), "functions.yaml"
    )
    known_policy_ids = frozenset(fn.id for fn in functions.functions if fn.level == "policy")
    profiles = _load_profiles(root / "profiles", known_policy_ids)
    tiers = _validate_model(TiersConfig, _read_yaml_mapping(root / "tiers.yaml"), "tiers.yaml")
    egress = _validate_model(EgressConfig, _read_yaml_mapping(root / "egress.yaml"), "egress.yaml")
    model_pins = _validate_model(
        ModelPinsConfig, _read_yaml_mapping(root / "model_pins.yaml"), "model_pins.yaml"
    )
    notices = _validate_model(
        NoticesConfig, _read_yaml_mapping(root / "notices.yaml"), "notices.yaml"
    )
    receipts = _validate_model(
        ReceiptsConfig, _read_yaml_mapping(root / "receipts.yaml"), "receipts.yaml"
    )
    function_flags = _validate_model(
        FunctionFlagsConfig,
        _read_yaml_mapping(root / "function_flags.yaml"),
        "function_flags.yaml",
    )
    conduct = _validate_model(
        PersonaConductConfig,
        _read_yaml_mapping(root / "personas" / "conduct.yaml"),
        "personas/conduct.yaml",
    )

    canonical_payload: dict[str, object] = {
        "functions": functions.model_dump(mode="json", by_alias=True),
        "profiles": {
            name: prof.model_dump(mode="json", by_alias=True)
            for name, prof in sorted(profiles.items())
        },
        "tiers": tiers.model_dump(mode="json", by_alias=True),
        "egress": egress.model_dump(mode="json", by_alias=True),
        "model_pins": model_pins.model_dump(mode="json", by_alias=True),
        "notices": notices.model_dump(mode="json", by_alias=True),
        "receipts": receipts.model_dump(mode="json", by_alias=True),
        "function_flags": function_flags.model_dump(mode="json", by_alias=True),
        "conduct": conduct.model_dump(mode="json", by_alias=True),
    }
    policy_sha256 = compute_policy_digest(canonical_payload)

    return DleConfig(
        functions=functions,
        profiles=profiles,
        tiers=tiers,
        egress=egress,
        model_pins=model_pins,
        notices=notices,
        receipts=receipts,
        function_flags=function_flags,
        conduct=conduct,
        policy_sha256=policy_sha256,
    )


__all__ = ["compute_policy_digest", "load_config"]
