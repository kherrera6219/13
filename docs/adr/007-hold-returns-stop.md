# ADR-007: Holds return STOP plus headers, not HTTP errors

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Architect
- **Requirements affected:** FR-API-06

## Context

An HTTP error on a hold would make SDK clients raise exceptions and lose the hold reason.

## Decision

A hold is a 200 response with `finishReason: STOP`, the hold notice as text, `X-DLE-Release-Mode: held` and a receipt.

## Consequences

Clients that ignore headers show the notice text as the answer, which is safe. Developer guide shows how to branch on the header.
