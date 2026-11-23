"""Unit tests for the DLE typed exception hierarchy (P1-01, DLE-STD-001)."""

from __future__ import annotations

import re

from dle.errors import (
    AuthError,
    ConfigError,
    ContractValidationError,
    DleError,
    EgressDenied,
    IllegalHoldError,
    KernelNotOptional,
    ModelUnavailable,
    SessionError,
    UnboundFunction,
    UnsafeBindError,
)

ALL_ERROR_CLASSES = [
    DleError,
    ConfigError,
    KernelNotOptional,
    ContractValidationError,
    EgressDenied,
    AuthError,
    UnsafeBindError,
    UnboundFunction,
    IllegalHoldError,
    SessionError,
    ModelUnavailable,
]


def test_error_codes_match_convention_and_are_unique():
    """Every DLE error class defines a unique DLE-E<nnnn> code."""
    pattern = re.compile(r"^DLE-E\d{4}$")
    codes = [cls.default_code for cls in ALL_ERROR_CLASSES]
    for cls, code in zip(ALL_ERROR_CLASSES, codes, strict=True):
        assert pattern.match(code), f"{cls.__name__} invalid code: {code}"
        assert issubclass(cls, DleError)
    assert len(codes) == len(set(codes))


def test_inheritance_and_formatting():
    """KernelNotOptional inherits ConfigError and DleError formats code prefix."""
    assert issubclass(KernelNotOptional, ConfigError)
    err = KernelNotOptional("cannot disable DVSS-K01", details={"dvss_id": "DVSS-K01"})
    assert err.code == "DLE-E1002"
    assert err.message == "cannot disable DVSS-K01"
    assert err.details == {"dvss_id": "DVSS-K01"}
    assert str(err) == "[DLE-E1002] cannot disable DVSS-K01"


def test_egress_denied_and_contract_validation_attributes():
    """Structured domain exceptions expose typed attributes and details."""
    egress_err = EgressDenied("evil.example", 443, "not listed")
    assert egress_err.code == "DLE-E1101"
    assert egress_err.host == "evil.example"
    assert egress_err.port == 443
    assert "evil.example:443" in str(egress_err)

    contract_err = ContractValidationError(
        "invalid schema",
        file_path="contracts/openapi.yaml",
        pointer="/paths/~1v1/get",
    )
    assert contract_err.code == "DLE-E1003"
    assert contract_err.file_path == "contracts/openapi.yaml"
    assert contract_err.pointer == "/paths/~1v1/get"
    assert contract_err.details["pointer"] == "/paths/~1v1/get"
