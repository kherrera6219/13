# ADR-009: Dispatch functions by DVSS ID through one registry (H16)

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Architect
- **Requirements affected:** FR-FN-01, FR-FN-04–06

## Context

Legacy KA numbers collide with enterprise registry titles (KA-015 is Temporal Reasoning in the registry, DVSS-K05 evidence acquisition here). Registry flags such as `Can_Veto` disagree with the 13-axis design.

## Decision

All bound functions are dispatched by DVSS ID through H16. KA numbers are catalog references only. External adapters pass a gate on version, schema hashes, scope and permissions. Registry flags are ignored.

## Consequences

One place to audit what can run; catalog entries can never execute by accident.
