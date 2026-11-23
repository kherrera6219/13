"""Gateway runtime settings and loopback-by-default bind enforcement.

Implements NFR-SEC-01, NFR-SEC-02, and ADR-011 Docker bind configuration.
Non-loopback bind addresses (such as ``0.0.0.0``) are refused unless
``allow_lan=True`` (``DLE_ALLOW_LAN=true``) is explicitly set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dle.errors import ConfigError, UnsafeBindError
from dle.observability import register_secret

LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = DEFAULT_REPO_ROOT / "config"
DEFAULT_UI_DIST_DIR = DEFAULT_REPO_ROOT / "ui" / "dist"


def validate_bind(bind_address: str, *, allow_lan: bool) -> None:
    """Refuse non-loopback binds unless ``allow_lan`` is explicitly enabled."""
    normalized = bind_address.strip().lower()
    if not normalized:
        raise UnsafeBindError("bind_address must not be empty")
    if normalized not in LOOPBACK_HOSTS and not allow_lan:
        raise UnsafeBindError(
            f"refusing non-loopback bind {bind_address!r} without DLE_ALLOW_LAN=true",
            details={"bind_address": bind_address, "allow_lan": allow_lan},
        )


def _parse_bool_env(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_key_set(
    multi_env: str,
    single_env: str,
    default_values: frozenset[str],
) -> frozenset[str]:
    raw_multi = os.getenv(multi_env)
    raw_single = os.getenv(single_env)
    collected: list[str] = []
    for raw in (raw_multi, raw_single):
        if raw:
            collected.extend(part.strip() for part in raw.split(",") if part.strip())
    if collected:
        return frozenset(collected)
    return default_values


@dataclass(frozen=True)
class GatewaySettings:
    """Validated gateway configuration controlling network bind, auth, and backend."""

    bind_address: str = "127.0.0.1"
    port: int = 8740
    allow_lan: bool = False
    client_api_keys: frozenset[str] = frozenset({"dev-client-key"})
    admin_api_keys: frozenset[str] = frozenset({"dev-admin-key"})
    model_backend: Literal["fake", "gemini"] = "fake"
    gemini_api_key: str | None = None
    config_dir: Path = DEFAULT_CONFIG_DIR
    ui_dist_dir: Path | None = DEFAULT_UI_DIST_DIR
    cors_origins: tuple[str, ...] = (
        "http://127.0.0.1:8740",
        "http://localhost:8740",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )

    def register_secrets(self) -> None:
        """Register configured client, admin, and Gemini keys with the log scrubber."""
        for key in self.client_api_keys | self.admin_api_keys:
            register_secret(key)
        if self.gemini_api_key:
            register_secret(self.gemini_api_key)

    @classmethod
    def from_env(cls) -> GatewaySettings:
        """Load ``GatewaySettings`` from environment variables with secure defaults."""
        bind_address = os.getenv("DLE_BIND_ADDRESS", "127.0.0.1").strip()
        allow_lan = _parse_bool_env(os.getenv("DLE_ALLOW_LAN"), default=False)
        validate_bind(bind_address, allow_lan=allow_lan)

        raw_port = os.getenv("DLE_PORT", "8740").strip()
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ConfigError(f"invalid DLE_PORT {raw_port!r}") from exc
        if not 1 <= port <= 65535:
            raise ConfigError(f"DLE_PORT out of range: {port}")

        backend_raw = os.getenv("DLE_MODEL_BACKEND", "fake").strip().lower()
        if backend_raw == "fake":
            model_backend: Literal["fake", "gemini"] = "fake"
        elif backend_raw == "gemini":
            model_backend = "gemini"
        else:
            raise ConfigError(
                f"invalid DLE_MODEL_BACKEND {backend_raw!r}; expected 'fake' or 'gemini'"
            )

        raw_config = os.getenv("DLE_CONFIG_DIR")
        config_dir = Path(raw_config) if raw_config else DEFAULT_CONFIG_DIR

        raw_ui = os.getenv("DLE_UI_DIST_DIR")
        ui_dist_dir = Path(raw_ui) if raw_ui else DEFAULT_UI_DIST_DIR

        raw_cors = os.getenv("DLE_CORS_ORIGINS")
        if raw_cors:
            cors_origins = tuple(origin.strip() for origin in raw_cors.split(",") if origin.strip())
        else:
            cors_origins = cls.cors_origins

        settings = cls(
            bind_address=bind_address,
            port=port,
            allow_lan=allow_lan,
            client_api_keys=_parse_key_set(
                "DLE_CLIENT_API_KEYS",
                "DLE_CLIENT_API_KEY",
                frozenset({"dev-client-key"}),
            ),
            admin_api_keys=_parse_key_set(
                "DLE_ADMIN_API_KEYS",
                "DLE_ADMIN_API_KEY",
                frozenset({"dev-admin-key"}),
            ),
            model_backend=model_backend,
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            config_dir=config_dir,
            ui_dist_dir=ui_dist_dir,
            cors_origins=cors_origins,
        )
        settings.register_secrets()
        return settings


__all__ = [
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_UI_DIST_DIR",
    "LOOPBACK_HOSTS",
    "GatewaySettings",
    "validate_bind",
]
