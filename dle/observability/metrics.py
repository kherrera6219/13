"""In-process Prometheus-format metrics registry without content labels.

Implements NFR-OBS-01, NFR-PRIV-01, and DLE-STD-001 §5 metric naming
(``dle_<area>_<measure>_<unit>``).
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Sequence

from dle.observability.logging import BANNED_LOG_KEYS

_METRIC_NAME_RE = re.compile(r"^dle_[a-z][a-z0-9_]*$")
_LABEL_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_BANNED_LABEL_SUFFIXES: tuple[str, ...] = (
    "_text",
    "_prompt",
    "_passage",
    "_secret",
    "_token",
    "_password",
)

DEFAULT_BUCKETS_MS: tuple[float, ...] = (
    5.0,
    10.0,
    25.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1000.0,
    2500.0,
    5000.0,
    15000.0,
    60000.0,
)


def _validate_metric_name(name: str) -> None:
    if not _METRIC_NAME_RE.match(name):
        raise ValueError(
            f"metric name {name!r} must match DLE-STD-001 'dle_<area>_<measure>_<unit>'"
        )


def _validate_label_names(label_names: tuple[str, ...]) -> None:
    for label in label_names:
        norm = label.lower().replace("-", "_")
        if not _LABEL_NAME_RE.match(label):
            raise ValueError(f"invalid Prometheus label name {label!r}")
        if norm in BANNED_LOG_KEYS or norm.endswith(_BANNED_LABEL_SUFFIXES):
            raise ValueError(f"label name {label!r} may carry sensitive or textual content")


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(label_names: tuple[str, ...], values: tuple[str, ...]) -> str:
    if not label_names:
        return ""
    pairs = [f'{k}="{_escape_label_value(v)}"' for k, v in zip(label_names, values, strict=True)]
    return "{" + ",".join(pairs) + "}"


def _resolve_labels(label_names: tuple[str, ...], labels: dict[str, str]) -> tuple[str, ...]:
    extra = set(labels) - set(label_names)
    if extra:
        raise ValueError(f"unexpected label(s): {sorted(extra)}")
    missing = [name for name in label_names if name not in labels]
    if missing:
        raise ValueError(f"missing label(s): {missing}")
    return tuple(str(labels[name]) for name in label_names)


class CounterMetric:
    """Monotonically non-decreasing Prometheus counter."""

    def __init__(self, name: str, help_text: str, label_names: tuple[str, ...]) -> None:
        """Initialize counter metadata and label schema."""
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        self._lock = threading.Lock()
        self._values: dict[tuple[str, ...], float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        """Increment counter for the given label set by a non-negative amount."""
        if amount < 0:
            raise ValueError("counter increment must be non-negative")
        key = _resolve_labels(self.label_names, labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, **labels: str) -> float:
        """Return current counter value for a label set (0.0 if unseen)."""
        key = _resolve_labels(self.label_names, labels)
        with self._lock:
            return self._values.get(key, 0.0)

    def render(self) -> list[str]:
        """Render Prometheus exposition lines for this counter."""
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} counter"]
        with self._lock:
            items = sorted(self._values.items())
        for key, val in items:
            lbl = _format_labels(self.label_names, key)
            lines.append(f"{self.name}{lbl} {val:g}")
        return lines


class GaugeMetric:
    """Prometheus gauge tracking an instantaneous numeric measurement."""

    def __init__(self, name: str, help_text: str, label_names: tuple[str, ...]) -> None:
        """Initialize gauge metadata and label schema."""
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        self._lock = threading.Lock()
        self._values: dict[tuple[str, ...], float] = {}

    def set(self, value: float, **labels: str) -> None:
        """Set gauge value for the given label set."""
        key = _resolve_labels(self.label_names, labels)
        with self._lock:
            self._values[key] = value

    def value(self, **labels: str) -> float:
        """Return current gauge value for a label set (0.0 if unseen)."""
        key = _resolve_labels(self.label_names, labels)
        with self._lock:
            return self._values.get(key, 0.0)

    def render(self) -> list[str]:
        """Render Prometheus exposition lines for this gauge."""
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} gauge"]
        with self._lock:
            items = sorted(self._values.items())
        for key, val in items:
            lbl = _format_labels(self.label_names, key)
            lines.append(f"{self.name}{lbl} {val:g}")
        return lines


class HistogramMetric:
    """Prometheus cumulative histogram with configurable upper bounds."""

    def __init__(
        self,
        name: str,
        help_text: str,
        label_names: tuple[str, ...],
        buckets: Sequence[float] = DEFAULT_BUCKETS_MS,
    ) -> None:
        """Initialize histogram metadata, label schema, and sorted bucket bounds."""
        sorted_buckets = tuple(sorted(float(b) for b in buckets))
        if not sorted_buckets:
            raise ValueError("histogram requires at least one finite bucket boundary")
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        self.buckets = sorted_buckets
        self._lock = threading.Lock()
        self._bucket_counts: dict[tuple[str, ...], list[int]] = {}
        self._sums: dict[tuple[str, ...], float] = {}
        self._counts: dict[tuple[str, ...], int] = {}

    def observe(self, value: float, **labels: str) -> None:
        """Record an observation into matching cumulative buckets and totals."""
        if math.isnan(value):
            raise ValueError("cannot observe NaN in histogram")
        key = _resolve_labels(self.label_names, labels)
        with self._lock:
            counts = self._bucket_counts.setdefault(key, [0] * (len(self.buckets) + 1))
            for idx, bound in enumerate(self.buckets):
                if value <= bound:
                    counts[idx] += 1
            counts[-1] += 1
            self._sums[key] = self._sums.get(key, 0.0) + value
            self._counts[key] = self._counts.get(key, 0) + 1

    def count(self, **labels: str) -> int:
        """Return total observations recorded for the given label set."""
        key = _resolve_labels(self.label_names, labels)
        with self._lock:
            return self._counts.get(key, 0)

    def render(self) -> list[str]:
        """Render Prometheus exposition lines for this histogram."""
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} histogram"]
        with self._lock:
            keys = sorted(self._counts.keys())
            snapshot = [
                (k, list(self._bucket_counts[k]), self._sums[k], self._counts[k]) for k in keys
            ]
        for key, bucket_counts, total_sum, total_count in snapshot:
            base_pairs = [(name, val) for name, val in zip(self.label_names, key, strict=True)]
            for bound, b_count in zip([*self.buckets, math.inf], bucket_counts, strict=True):
                le_str = "+Inf" if math.isinf(bound) else f"{bound:g}"
                all_names = (*self.label_names, "le")
                all_vals = (*key, le_str)
                lines.append(f"{self.name}_bucket{_format_labels(all_names, all_vals)} {b_count}")
            lbl = _format_labels(tuple(k for k, _ in base_pairs), tuple(v for _, v in base_pairs))
            lines.append(f"{self.name}_sum{lbl} {total_sum:g}")
            lines.append(f"{self.name}_count{lbl} {total_count}")
        return lines


class MetricsRegistry:
    """Thread-safe container of Prometheus metrics enforcing DLE naming and privacy rules."""

    def __init__(self) -> None:
        """Create an empty metrics registry."""
        self._lock = threading.Lock()
        self._metrics: dict[str, CounterMetric | GaugeMetric | HistogramMetric] = {}

    def counter(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
    ) -> CounterMetric:
        """Register and return a named counter metric."""
        _validate_metric_name(name)
        labels_tuple = tuple(label_names)
        _validate_label_names(labels_tuple)
        with self._lock:
            if name in self._metrics:
                existing = self._metrics[name]
                if not isinstance(existing, CounterMetric) or existing.label_names != labels_tuple:
                    raise ValueError(f"metric {name!r} already registered with different schema")
                return existing
            metric = CounterMetric(name, help_text, labels_tuple)
            self._metrics[name] = metric
            return metric

    def gauge(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
    ) -> GaugeMetric:
        """Register and return a named gauge metric."""
        _validate_metric_name(name)
        labels_tuple = tuple(label_names)
        _validate_label_names(labels_tuple)
        with self._lock:
            if name in self._metrics:
                existing = self._metrics[name]
                if not isinstance(existing, GaugeMetric) or existing.label_names != labels_tuple:
                    raise ValueError(f"metric {name!r} already registered with different schema")
                return existing
            metric = GaugeMetric(name, help_text, labels_tuple)
            self._metrics[name] = metric
            return metric

    def histogram(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
        buckets: Sequence[float] = DEFAULT_BUCKETS_MS,
    ) -> HistogramMetric:
        """Register and return a named histogram metric."""
        _validate_metric_name(name)
        labels_tuple = tuple(label_names)
        _validate_label_names(labels_tuple)
        with self._lock:
            if name in self._metrics:
                existing = self._metrics[name]
                if (
                    not isinstance(existing, HistogramMetric)
                    or existing.label_names != labels_tuple
                ):
                    raise ValueError(f"metric {name!r} already registered with different schema")
                return existing
            metric = HistogramMetric(name, help_text, labels_tuple, buckets=buckets)
            self._metrics[name] = metric
            return metric

    def render_prometheus(self) -> str:
        """Render all registered metrics in Prometheus text exposition format."""
        with self._lock:
            ordered = [self._metrics[name] for name in sorted(self._metrics)]
        lines: list[str] = []
        for metric in ordered:
            lines.extend(metric.render())
        return "\n".join(lines) + ("\n" if lines else "")


METRICS = MetricsRegistry()
METRICS.counter(
    "dle_egress_requests_total",
    "Total outbound egress attempts partitioned by host and allowance",
    label_names=("host", "allowed"),
)
METRICS.counter(
    "dle_egress_bytes_out_total",
    "Total outbound request payload bytes sent through EgressClient",
    label_names=("host",),
)
METRICS.counter(
    "dle_egress_bytes_in_total",
    "Total inbound response payload bytes received through EgressClient",
    label_names=("host",),
)
METRICS.histogram(
    "dle_egress_duration_ms",
    "Outbound HTTP request duration in milliseconds",
    label_names=("host",),
)
METRICS.counter(
    "dle_http_requests_total",
    "Total inbound HTTP requests by route and status",
    label_names=("route", "status"),
)
METRICS.histogram(
    "dle_run_duration_ms",
    "Middleware run latency in milliseconds by profile and tier",
    label_names=("profile", "tier"),
)
METRICS.counter(
    "dle_holds_total",
    "Total held responses by profile and normalized reason",
    label_names=("profile", "reason"),
)

__all__ = [
    "DEFAULT_BUCKETS_MS",
    "METRICS",
    "CounterMetric",
    "GaugeMetric",
    "HistogramMetric",
    "MetricsRegistry",
]
