# ADR-005: SQLite for all stores

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Architect
- **Requirements affected:** NFR-PORT-01, NFR-MAINT-01

## Context

The middleware installs on a single workstation, server or VM, often in regulated or air-gapped environments.

## Options considered

1. **SQLite with FTS5 and sqlite-vec** — no server to run; one file per store; WAL for concurrency.
2. **PostgreSQL** — scales out; adds an operated service.

## Decision

Five SQLite databases split by write pattern (registry, evidence, sessions, receipts, ops), WAL mode.

## Consequences

Single-host only (multi-node is out of scope for v1). The store layer sits behind interfaces so a server database can be added later by ADR.
