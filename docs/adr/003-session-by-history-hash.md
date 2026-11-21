# ADR-003: Identify sessions by hashing canonical history

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Architect
- **Requirements affected:** FR-SES-01–03

## Context

The Gemini API is stateless; each request carries the whole history. The middleware needs a stable session key for overlays, parked tool runs and receipt chains.

## Options considered

1. **Hash of JCS-canonical history minus newest user turn, scoped by tenant, model, systemInstruction** — no client change.
2. **Client-supplied session header only** — requires client changes.
3. **Server-issued session token** — breaks Gemini compatibility.

## Decision

Option 1, with an optional `X-DLE-Session` override. The session ID doubles as the receipt chain ID.

## Consequences

Editing earlier turns starts a new session, which is the correct behavior for evidence integrity.
