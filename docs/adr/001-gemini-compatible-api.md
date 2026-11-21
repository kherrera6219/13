# ADR-001: Expose a Gemini-compatible API

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Tech lead, Architect
- **Requirements affected:** FR-API-01–08, IR-01–07

## Context

Applications already built on the Gemini SDK should gain governed answers without code changes.

## Options considered

1. **Gemini-compatible façade** — zero client changes; must track Gemini API changes.
2. **Custom DLE API** — full control; every client must be rewritten.

## Decision

Serve the Gemini v1beta routes and shapes, with DLE data in `X-DLE-*` headers, `groundingMetadata` and an optional `dleMetadata` object.

## Consequences

The translator absorbs Gemini API changes; the compatibility suite (GC-01–GC-26) runs every release against the official SDKs.
