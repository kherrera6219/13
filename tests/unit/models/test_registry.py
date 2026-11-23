"""Unit tests for ModelRegistry dated pricing and modelVersion drift (P1-06, NFR-COST-01)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from dle.config import load_config
from dle.errors import ConfigError
from dle.models.registry import ModelRegistry, ModelVersionDriftEvent

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_dated_pricing_switches_gemini_4_carbon_on_2026_12_01():
    """T-UNIT-MODEL-04: gemini-4-carbon doubles from $2/$10 to $4/$20 on 2026-12-01."""
    cfg = load_config(REPO_ROOT / "config")
    registry = ModelRegistry(cfg.model_pins)

    assert registry.pin_for_job("intake") == "gemini-4-neon"
    assert registry.pin_for_job("writer") == "gemini-4-carbon"
    assert registry.pin_for_job("embeddings") == "gemini-embedding-001"

    nov_cost = registry.compute_cost(
        "gemini-4-carbon",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        on_date=date(2026, 11, 30),
    )
    assert nov_cost.cost_usd == pytest.approx(12.0)

    dec_cost = registry.compute_cost(
        "models/gemini-4-carbon",
        input_tokens=1_000_000,
        cached_input_tokens=500_000,
        output_tokens=750_000,
        thought_tokens=250_000,
        on_date=date(2026, 12, 1),
    )
    # 500k uncached * $4/1M ($2) + 500k cached * $0.20/1M ($0.10) + 1M output/thought * $20/1M ($20)
    assert dec_cost.cost_usd == pytest.approx(22.10)


def test_neon_and_embedding_pricing_and_unknown_date_errors():
    """T-UNIT-MODEL-05: Neon and embedding pins compute accurately and reject unknown dates."""
    cfg = load_config(REPO_ROOT / "config")
    registry = ModelRegistry(cfg.model_pins)

    neon_cost = registry.compute_cost(
        "gemini-4-neon",
        input_tokens=200_000,
        output_tokens=100_000,
        on_date=date(2026, 12, 15),
    )
    # 0.2 * $3 + 0.1 * $15 = $0.60 + $1.50 = $2.10
    assert neon_cost.cost_usd == pytest.approx(2.10)

    embed_cost = registry.compute_cost(
        "gemini-embedding-001",
        input_tokens=1_000_000,
        on_date=date(2026, 12, 15),
    )
    assert embed_cost.cost_usd == pytest.approx(0.15)

    with pytest.raises(ConfigError, match="unknown model job"):
        registry.pin_for_job("nonexistent")
    with pytest.raises(ConfigError, match="price window"):
        registry.price_for("gemini-4-carbon", on_date=date(2025, 1, 1))


def test_model_version_change_trips_drift_latch_and_emits_event():
    """T-UNIT-MODEL-06: observed modelVersion mismatch against calibration trips drift latch."""
    cfg = load_config(REPO_ROOT / "config")
    events: list[ModelVersionDriftEvent] = []
    registry = ModelRegistry(
        cfg.model_pins,
        calibrated_versions={"gemini-4-carbon": "gemini-4-carbon-001"},
        on_drift=events.append,
    )

    assert (
        registry.record_model_version(
            job="writer", model_id="gemini-4-carbon", model_version="gemini-4-carbon-001"
        )
        is None
    )
    assert registry.drift_latched is False

    drift = registry.record_model_version(
        job="writer", model_id="models/gemini-4-carbon", model_version="gemini-4-carbon-002"
    )
    assert drift is not None
    assert drift.expected_version == "gemini-4-carbon-001"
    assert drift.observed_version == "gemini-4-carbon-002"
    assert registry.drift_latched is True
    assert len(events) == 1
    assert registry.observed_versions["gemini-4-carbon"] == "gemini-4-carbon-002"

    registry.reset_drift_latch()
    assert registry.drift_latched is False
