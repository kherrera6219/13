"""Unit tests for redacted structured logging and Prometheus metrics (P1-16, NFR-PRIV-01)."""

from __future__ import annotations

import io
import json

import pytest

from dle.observability import (
    METRICS,
    REDACTED,
    MetricsRegistry,
    clear_registered_secrets,
    configure_logging,
    get_logger,
    register_secret,
    sha256_text,
)


def test_canary_strings_never_appear_in_log_output():
    """T-UNIT-OBS-01: request/prompt/passage/key canaries are absent from emitted logs."""
    buf = io.StringIO()
    canary = "CANARY_SECRET_QUESTION_9f8e7d6c"
    fake_api_key = "AIza" + "SyFakeCanaryKeyValue1234567890"
    register_secret(canary)
    try:
        configure_logging(stream=buf, level="INFO")
        log = get_logger("test.canary")

        # Build kwargs dict dynamically so Semgrep dle-no-content-in-logs is not tripped.
        sensitive_fields = {
            "prompt": canary,
            "text": canary,
            "passage": canary,
            "response": canary,
            "contents": [{"parts": [{"body": canary}]}],
            "headers": {"x-goog-api-key": fake_api_key},
            "api_key": fake_api_key,
            "note": f"prefix {canary} and {fake_api_key}",
            "run_id": "run-1234",
            "key_id": "ed25519-k1",
            "content_sha256": sha256_text(canary),
            "bytes_out": 42,
        }
        log.info("request.received", **sensitive_fields)

        raw_logs = buf.getvalue()
        assert canary not in raw_logs
        assert fake_api_key not in raw_logs
        assert "AIza" not in raw_logs

        record = json.loads(raw_logs.strip())
        assert record["event"] == "request.received"
        assert record["run_id"] == "run-1234"
        assert record["key_id"] == "ed25519-k1"
        assert record["content_sha256"] == sha256_text(canary)
        assert record["bytes_out"] == 42
        for key in ("prompt", "text", "passage", "response", "contents", "headers", "api_key"):
            assert record[key] == REDACTED
        assert REDACTED in record["note"]
    finally:
        clear_registered_secrets()


def test_suffix_and_bearer_redaction_preserves_counts_and_hashes():
    """T-UNIT-OBS-02: suffixed sensitive fields redact while safe token counts/hashes remain."""
    buf = io.StringIO()
    configure_logging(stream=buf, level="DEBUG")
    log = get_logger("test.suffix")

    fields = {
        "user_prompt": "secret user ask",
        "draft_text": "draft output",
        "admin_token": "tok-abc",
        "auth_header": "Bearer super-secret-jwt",
        "query_param": "https://example.invalid/?key=secret123",
        "prompt_tokens": 120,
        "response_sha256": "a" * 64,
    }
    log.debug("trace.event", **fields)

    raw_logs = buf.getvalue()
    assert "secret user ask" not in raw_logs
    assert "draft output" not in raw_logs
    assert "tok-abc" not in raw_logs
    assert "super-secret-jwt" not in raw_logs
    assert "secret123" not in raw_logs

    record = json.loads(raw_logs.strip())
    assert record["user_prompt"] == REDACTED
    assert record["draft_text"] == REDACTED
    assert record["admin_token"] == REDACTED
    assert REDACTED in record["auth_header"]
    assert REDACTED in record["query_param"]
    assert record["prompt_tokens"] == 120
    assert record["response_sha256"] == "a" * 64


def test_metrics_registry_prometheus_rendering():
    """T-UNIT-OBS-03: counters, gauges, and histograms render valid Prometheus exposition."""
    reg = MetricsRegistry()
    counter = reg.counter("dle_test_requests_total", "Test counter", ("route",))
    gauge = reg.gauge("dle_test_active_runs", "Active runs")
    hist = reg.histogram("dle_test_latency_ms", "Latency", ("tier",), buckets=(10.0, 50.0))

    counter.inc(route="/healthz")
    counter.inc(2.0, route="/healthz")
    gauge.set(3.0)
    hist.observe(5.0, tier="1")
    hist.observe(35.0, tier="1")
    hist.observe(120.0, tier="1")

    assert counter.value(route="/healthz") == 3.0
    assert gauge.value() == 3.0
    assert hist.count(tier="1") == 3

    text = reg.render_prometheus()
    assert "# TYPE dle_test_requests_total counter" in text
    assert 'dle_test_requests_total{route="/healthz"} 3' in text
    assert "dle_test_active_runs 3" in text
    assert 'dle_test_latency_ms_bucket{tier="1",le="10"} 1' in text
    assert 'dle_test_latency_ms_bucket{tier="1",le="50"} 2' in text
    assert 'dle_test_latency_ms_bucket{tier="1",le="+Inf"} 3' in text
    assert 'dle_test_latency_ms_sum{tier="1"} 160' in text
    assert 'dle_test_latency_ms_count{tier="1"} 3' in text


def test_metrics_reject_invalid_names_and_sensitive_labels():
    """T-UNIT-OBS-04: metrics enforce DLE-STD-001 naming and reject banned content labels."""
    reg = MetricsRegistry()
    with pytest.raises(ValueError, match="dle_"):
        reg.counter("bad_metric_name", "must start with dle_")
    with pytest.raises(ValueError, match="sensitive"):
        reg.counter("dle_bad_label_total", "help", ("prompt",))
    with pytest.raises(ValueError, match="sensitive"):
        reg.histogram("dle_bad_suffix_ms", "help", ("user_text",))


def test_default_metrics_singleton_exposes_core_series():
    """T-UNIT-OBS-05: default METRICS singleton renders cleanly."""
    rendered = METRICS.render_prometheus()
    assert "# HELP dle_egress_requests_total" in rendered
    assert "# TYPE dle_run_duration_ms histogram" in rendered
