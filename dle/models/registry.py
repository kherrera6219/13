"""Model pin registry, dated cost metering, and modelVersion drift detection.

Implements NFR-COST-01, FR-REL-04, and ADR-011. Pricing is read from
``config/model_pins.yaml`` using half-open valid-time intervals from
``dle.temporal``. Any change in observed ``modelVersion`` relative to the
calibrated baseline latches drift and emits a telemetry event.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime

from dle.config.models import DatedPrice, ModelPinsConfig
from dle.errors import ConfigError
from dle.observability import get_logger
from dle.temporal import Interval, contains


@dataclass(frozen=True)
class UsageCost:
    """Metered token counts and USD cost computed from dated pin tables."""

    model_id: str
    model_version: str | None
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    thought_tokens: int
    cost_usd: float
    effective_date: date


@dataclass(frozen=True)
class ModelVersionDriftEvent:
    """Event emitted when a provider returns a ``modelVersion`` differing from calibration."""

    model_id: str
    expected_version: str
    observed_version: str
    job: str


def _strip_model_prefix(model_id: str) -> str:
    return model_id.removeprefix("models/")


class ModelRegistry:
    """Resolves job model pins, dated USD pricing, and ``modelVersion`` drift state."""

    def __init__(
        self,
        pins: ModelPinsConfig,
        *,
        calibrated_versions: Mapping[str, str] | None = None,
        on_drift: Callable[[ModelVersionDriftEvent], None] | None = None,
    ) -> None:
        """Initialize the registry from loaded ``model_pins.yaml`` and calibrated baselines."""
        self._pins = pins
        self._calibrated_versions: dict[str, str] = (
            {_strip_model_prefix(k): v for k, v in calibrated_versions.items()}
            if calibrated_versions is not None
            else {}
        )
        self._on_drift = on_drift
        self._log = get_logger("dle.models.registry")
        self.observed_versions: dict[str, str] = {}
        self.drift_latched: bool = False
        self.last_drift_event: ModelVersionDriftEvent | None = None

    def pin_for_job(self, job: str) -> str:
        """Return the pinned Gemini model ID for ``job`` (e.g. ``intake``, ``writer``)."""
        if job not in self._pins.jobs:
            raise ConfigError(f"unknown model job {job!r} in model_pins.yaml")
        return self._pins.jobs[job]

    def price_for(self, model_id: str, on_date: date | None = None) -> DatedPrice:
        """Return the dated USD-per-million-tokens price entry active on ``on_date``."""
        canonical_id = _strip_model_prefix(model_id)
        entries = self._pins.prices_usd_per_million_tokens.get(canonical_id)
        if not entries:
            raise ConfigError(f"no price schedule registered for model {canonical_id!r}")

        target_date = on_date if on_date is not None else datetime.now(UTC).date()
        for entry in entries:
            window = Interval(entry.from_date, entry.to_date, "date")
            if contains(window, target_date):
                return entry
        raise ConfigError(
            f"no dated price window for model {canonical_id!r} on {target_date.isoformat()}"
        )

    def compute_cost(
        self,
        model_id: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
        thought_tokens: int = 0,
        model_version: str | None = None,
        on_date: date | None = None,
    ) -> UsageCost:
        """Compute metered USD cost for a call using half-open dated pricing rules."""
        canonical_id = _strip_model_prefix(model_id)
        target_date = on_date if on_date is not None else datetime.now(UTC).date()
        price = self.price_for(canonical_id, target_date)
        billable_input = max(0, input_tokens - max(0, cached_input_tokens))
        total_output = max(0, output_tokens) + max(0, thought_tokens)
        cost_usd = (
            billable_input * price.input
            + max(0, cached_input_tokens) * price.cached_input
            + total_output * price.output
        ) / 1_000_000.0
        return UsageCost(
            model_id=canonical_id,
            model_version=model_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            thought_tokens=thought_tokens,
            cost_usd=cost_usd,
            effective_date=target_date,
        )

    def record_model_version(
        self,
        *,
        job: str,
        model_id: str,
        model_version: str,
    ) -> ModelVersionDriftEvent | None:
        """Record observed ``modelVersion`` and trip the drift latch if baseline differs."""
        canonical_id = _strip_model_prefix(model_id)
        self.observed_versions[canonical_id] = model_version
        expected = self._calibrated_versions.get(canonical_id)
        if expected is not None and expected != model_version:
            event = ModelVersionDriftEvent(
                model_id=canonical_id,
                expected_version=expected,
                observed_version=model_version,
                job=job,
            )
            self.drift_latched = True
            self.last_drift_event = event
            self._log.warning(
                "model.version_drift",
                model_id=canonical_id,
                expected_version=expected,
                observed_version=model_version,
                job=job,
            )
            if self._on_drift is not None:
                self._on_drift(event)
            return event
        return None

    def set_calibrated_versions(self, calibrated_versions: Mapping[str, str]) -> None:
        """Update expected calibrated ``modelVersion`` baselines from an approved artifact."""
        self._calibrated_versions = {
            _strip_model_prefix(k): str(v) for k, v in calibrated_versions.items()
        }

    def reset_drift_latch(self) -> None:
        """Clear an active drift latch after calibration verification."""
        self.drift_latched = False
        self.last_drift_event = None


__all__ = ["ModelRegistry", "ModelVersionDriftEvent", "UsageCost"]
