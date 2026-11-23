"""Single allowlisted outbound HTTP client (`EgressClient`).

Implements NFR-SEC-03, NFR-PRIV-01, and AGENTS.md rule 7. This is the only
module under ``dle/`` permitted to import ``httpx``. Outbound calls are denied
by default unless ``(host, port)`` appears in the allowlist. Headers, API
keys, URL query parameters, request bodies, and response bodies are never
logged.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Protocol

import httpx

from dle.config.models import EgressConfig
from dle.errors import EgressDenied
from dle.observability import METRICS, get_logger


class EgressResponse(Protocol):
    """Structural HTTP response interface so callers need not import ``httpx``."""

    @property
    def status_code(self) -> int:
        """HTTP status code returned by upstream."""
        ...

    @property
    def content(self) -> bytes:
        """Raw response body bytes."""
        ...

    def json(self) -> object:
        """Decode response body as JSON."""
        ...

    def aiter_lines(self) -> AsyncIterator[str]:
        """Iterate decoded text lines for streaming responses."""
        ...


def is_transport_error(exc: BaseException) -> bool:
    """Return True when ``exc`` is an ``httpx`` transport or protocol failure."""
    return isinstance(exc, httpx.HTTPError)


@dataclass(frozen=True)
class EgressEvent:
    """Non-sensitive telemetry record emitted for every outbound HTTP attempt."""

    host: str
    port: int
    bytes_out: int
    bytes_in: int
    duration_ms: float
    is_allowed: bool
    logged_utc: str


EgressSink = Callable[[EgressEvent], None]


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_allowlist(
    allowlist: EgressConfig | Sequence[tuple[str, int]],
) -> frozenset[tuple[str, int]]:
    if isinstance(allowlist, EgressConfig):
        return frozenset((rule.host.strip().lower(), int(rule.port)) for rule in allowlist.allow)
    return frozenset((host.strip().lower(), int(port)) for host, port in allowlist)


class EgressClient:
    """Deny-by-default async HTTP client enforcing ``config/egress.yaml`` allowlists."""

    def __init__(
        self,
        allowlist: EgressConfig | Sequence[tuple[str, int]] = (),
        *,
        timeout_s: float = 60.0,
        require_https: bool = True,
        sink: EgressSink | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Initialize the allowlisted HTTP transport wrapper."""
        self._allowed = _normalize_allowlist(allowlist)
        self._require_https = require_https
        self._sink = sink
        self._log = get_logger("dle.models.egress")
        self._client = httpx.AsyncClient(
            timeout=timeout_s,
            transport=transport,
            follow_redirects=False,
        )

    async def __aenter__(self) -> EgressClient:
        """Enter async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close underlying httpx connection pool on context exit."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying ``httpx.AsyncClient``."""
        await self._client.aclose()

    def is_allowed(self, url: str) -> bool:
        """Return whether ``url`` resolves to an allowed scheme, host, and port."""
        parsed = httpx.URL(url)
        scheme = parsed.scheme.lower()
        host = (parsed.host or "").lower()
        if not host:
            return False
        if self._require_https and scheme != "https":
            return False
        port = _resolve_port(parsed, scheme)
        return (host, port) in self._allowed

    def _emit_event(
        self,
        event: EgressEvent,
        *,
        status_code: int | None = None,
        reason: str | None = None,
        error_type: str | None = None,
    ) -> None:
        host_label = event.host or "<empty>"
        METRICS.counter(
            "dle_egress_requests_total",
            "Total outbound egress attempts partitioned by host and allowance",
            ("host", "allowed"),
        ).inc(host=host_label, allowed=str(event.is_allowed).lower())

        if event.is_allowed:
            METRICS.counter(
                "dle_egress_bytes_out_total",
                "Total outbound request payload bytes sent through EgressClient",
                ("host",),
            ).inc(float(event.bytes_out), host=host_label)
            METRICS.counter(
                "dle_egress_bytes_in_total",
                "Total inbound response payload bytes received through EgressClient",
                ("host",),
            ).inc(float(event.bytes_in), host=host_label)
            METRICS.histogram(
                "dle_egress_duration_ms",
                "Outbound HTTP request duration in milliseconds",
                ("host",),
            ).observe(event.duration_ms, host=host_label)

            if error_type is not None:
                self._log.warning(
                    "egress.error",
                    host=host_label,
                    port=event.port,
                    bytes_out=event.bytes_out,
                    bytes_in=event.bytes_in,
                    duration_ms=round(event.duration_ms, 3),
                    error_type=error_type,
                )
            else:
                self._log.info(
                    "egress.completed",
                    host=host_label,
                    port=event.port,
                    bytes_out=event.bytes_out,
                    bytes_in=event.bytes_in,
                    duration_ms=round(event.duration_ms, 3),
                    status_code=status_code,
                )
        else:
            self._log.warning(
                "egress.denied",
                host=host_label,
                port=event.port,
                bytes_out=0,
                bytes_in=0,
                duration_ms=0.0,
                reason=reason or "denied",
            )

        if self._sink is not None:
            self._sink(event)

    def _enforce_allowlist(self, url: str) -> tuple[str, int]:
        parsed = httpx.URL(url)
        scheme = parsed.scheme.lower()
        host = (parsed.host or "").lower()
        port = _resolve_port(parsed, scheme)

        reason: str | None = None
        if not host:
            reason = "missing host"
        elif self._require_https and scheme != "https":
            reason = "https required"
        elif (host, port) not in self._allowed:
            reason = "host not on egress allowlist"

        if reason is not None:
            event = EgressEvent(
                host=host,
                port=port,
                bytes_out=0,
                bytes_in=0,
                duration_ms=0.0,
                is_allowed=False,
                logged_utc=_utc_now_iso(),
            )
            self._emit_event(event, reason=reason)
            raise EgressDenied(host, port, reason)

        return host, port

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        content: bytes | None = None,
        json: object = None,
    ) -> httpx.Response:
        """Send an allowlisted HTTP request and return the ``httpx.Response``."""
        host, port = self._enforce_allowlist(url)
        req = self._client.build_request(
            method,
            url,
            headers=headers,
            params=params,
            content=content,
            json=json,
        )
        bytes_out = len(req.content)
        start = time.perf_counter()
        try:
            response = await self._client.send(req)
        except httpx.HTTPError as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            self._emit_event(
                EgressEvent(
                    host=host,
                    port=port,
                    bytes_out=bytes_out,
                    bytes_in=0,
                    duration_ms=duration_ms,
                    is_allowed=True,
                    logged_utc=_utc_now_iso(),
                ),
                error_type=type(exc).__name__,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000.0
        self._emit_event(
            EgressEvent(
                host=host,
                port=port,
                bytes_out=bytes_out,
                bytes_in=len(response.content),
                duration_ms=duration_ms,
                is_allowed=True,
                logged_utc=_utc_now_iso(),
            ),
            status_code=response.status_code,
        )
        return response

    @asynccontextmanager
    async def stream(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        content: bytes | None = None,
        json: object = None,
    ) -> AsyncIterator[httpx.Response]:
        """Open an allowlisted streaming HTTP response and log transfer size on close."""
        host, port = self._enforce_allowlist(url)
        req = self._client.build_request(
            method,
            url,
            headers=headers,
            params=params,
            content=content,
            json=json,
        )
        bytes_out = len(req.content)
        start = time.perf_counter()
        error_type: str | None = None
        response: httpx.Response | None = None
        try:
            response = await self._client.send(req, stream=True)
            yield response
        except httpx.HTTPError as exc:
            error_type = type(exc).__name__
            raise
        finally:
            bytes_in = 0
            status_code = response.status_code if response is not None else None
            if response is not None:
                await response.aclose()
                raw_content = getattr(response, "_content", None)
                buffered_len = len(raw_content) if isinstance(raw_content, bytes | bytearray) else 0
                bytes_in = max(response.num_bytes_downloaded, buffered_len)
            duration_ms = (time.perf_counter() - start) * 1000.0
            self._emit_event(
                EgressEvent(
                    host=host,
                    port=port,
                    bytes_out=bytes_out,
                    bytes_in=bytes_in,
                    duration_ms=duration_ms,
                    is_allowed=True,
                    logged_utc=_utc_now_iso(),
                ),
                status_code=status_code,
                error_type=error_type,
            )


def _resolve_port(url: httpx.URL, scheme: str) -> int:
    if url.port is not None:
        return int(url.port)
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    return 0


__all__ = [
    "EgressClient",
    "EgressEvent",
    "EgressResponse",
    "EgressSink",
    "is_transport_error",
]
