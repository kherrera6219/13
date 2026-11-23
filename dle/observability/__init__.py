"""Structured logging with strict content redaction and metrics (`NFR-PRIV-01`, `NFR-OBS-01`)."""

from dle.observability.logging import (
    BANNED_LOG_KEYS,
    REDACTED,
    clear_registered_secrets,
    configure_logging,
    get_logger,
    redact_event_dict,
    register_secret,
    sha256_text,
)
from dle.observability.metrics import (
    DEFAULT_BUCKETS_MS,
    METRICS,
    CounterMetric,
    GaugeMetric,
    HistogramMetric,
    MetricsRegistry,
)

__all__ = [
    "BANNED_LOG_KEYS",
    "DEFAULT_BUCKETS_MS",
    "METRICS",
    "REDACTED",
    "CounterMetric",
    "GaugeMetric",
    "HistogramMetric",
    "MetricsRegistry",
    "clear_registered_secrets",
    "configure_logging",
    "get_logger",
    "redact_event_dict",
    "register_secret",
    "sha256_text",
]
