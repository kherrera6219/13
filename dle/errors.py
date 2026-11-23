"""Typed exception hierarchy and error codes for dle-middleware.

Implements DLE-STD-001 §1 error numbering (`DLE-E<nnnn>`), NFR-MAINT-01,
NFR-SEC-03, and FR-FN-03.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar


class DleError(Exception):
    """Base exception for all middleware errors (`DLE-E0001`).

    Attributes:
        code: Stable error identifier formatted as ``DLE-E<nnnn>``.
        message: Human-readable summary free of raw user content or secrets.
        details: Optional non-sensitive structured metadata.
    """

    default_code: ClassVar[str] = "DLE-E0001"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Initialize a DLE exception with a stable error code and optional details."""
        self.code: str = code or self.default_code
        self.message: str = message
        self.details: dict[str, Any] = dict(details) if details is not None else {}
        super().__init__(f"[{self.code}] {message}")


class ConfigError(DleError):
    """Configuration loading or validation failure (`DLE-E1001`, FR-FN-03)."""

    default_code: ClassVar[str] = "DLE-E1001"


class KernelNotOptional(ConfigError):
    """Raised when a profile disables or omits a kernel function (`DLE-E1002`, FR-FN-03)."""

    default_code: ClassVar[str] = "DLE-E1002"


class ContractValidationError(DleError):
    """Schema, OpenAPI, or function contract validation error (`DLE-E1003`, IR-01..07)."""

    default_code: ClassVar[str] = "DLE-E1003"

    def __init__(
        self,
        message: str,
        *,
        file_path: str | None = None,
        pointer: str | None = None,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Initialize with optional file path and RFC 6901 JSON pointer."""
        merged = dict(details) if details is not None else {}
        if file_path is not None:
            merged["file_path"] = file_path
        if pointer is not None:
            merged["pointer"] = pointer
        self.file_path: str | None = file_path
        self.pointer: str | None = pointer
        super().__init__(message, code=code, details=merged)


class EgressDenied(DleError):
    """Raised when outbound HTTP targets a host/port off the allowlist (`DLE-E1101`, NFR-SEC-03)."""

    default_code: ClassVar[str] = "DLE-E1101"

    def __init__(
        self,
        host: str,
        port: int,
        reason: str = "host not on egress allowlist",
        *,
        code: str | None = None,
    ) -> None:
        """Initialize with denied target host, port, and rejection reason."""
        self.host: str = host
        self.port: int = port
        super().__init__(
            f"egress denied for {host or '<empty>'}:{port}: {reason}",
            code=code,
            details={"host": host, "port": port, "reason": reason},
        )


class AuthError(DleError):
    """Authentication or authorization failure (`DLE-E1102`, NFR-SEC-02)."""

    default_code: ClassVar[str] = "DLE-E1102"


class UnsafeBindError(DleError):
    """Server attempted non-loopback bind without opt-in (`DLE-E1103`, NFR-SEC-01)."""

    default_code: ClassVar[str] = "DLE-E1103"


class UnboundFunction(DleError):
    """Attempted invocation of an unregistered or KA-* function ID (`DLE-E1201`, FR-FN-04)."""

    default_code: ClassVar[str] = "DLE-E1201"


class IllegalHoldError(DleError):
    """Non-hold-capable function attempted to produce a hold (`DLE-E1202`, AGENTS rule 6)."""

    default_code: ClassVar[str] = "DLE-E1202"


class SessionError(DleError):
    """Session resolution or state error (`DLE-E1203`, FR-SES-01..03)."""

    default_code: ClassVar[str] = "DLE-E1203"


class ModelUnavailable(DleError):
    """Upstream model failed after configured retries (`DLE-E1301`, NFR-REL-02)."""

    default_code: ClassVar[str] = "DLE-E1301"


__all__ = [
    "AuthError",
    "ConfigError",
    "ContractValidationError",
    "DleError",
    "EgressDenied",
    "IllegalHoldError",
    "KernelNotOptional",
    "ModelUnavailable",
    "SessionError",
    "UnboundFunction",
    "UnsafeBindError",
]
