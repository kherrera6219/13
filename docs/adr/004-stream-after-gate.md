# ADR-004: Pseudo-stream only after the gate passes

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Architect
- **Requirements affected:** FR-API-07, NFR-PERF-02

## Context

Streaming tokens as the writer produces them would show users text the release rule may later withhold.

## Options considered

1. **Stream after release, keepalives during the gate** — release rule intact; slower first token.
2. **Stream live, retract on hold** — fast; users see unverified text.

## Decision

Option 1. SSE comment keepalives at least every 10 s; released text then sent in chunks.

## Consequences

Tier 3 first-token latency equals full run time. Mitigated by keepalives and tier tuning (blueprint risk table).
