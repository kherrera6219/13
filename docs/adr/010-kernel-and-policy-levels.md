# ADR-010: Kernel functions are host code and cannot be disabled; policy functions are profile-controlled with required host fallbacks

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Architect, AI risk owner
- **Requirements affected:** FR-FN-02, FR-FN-03, FR-FN-07, FR-FN-09

## Context

Safety behavior must not depend on configuration, and the §17 ablation needs a clean kernel-only arm.

## Decision

K01–K12 always run; the service refuses to start without them. P01–P14 are enabled per profile. P07 escalation, P08 role token allocation and P12 drift gating have host fallbacks that run whenever the behavior is declared and the module is disabled.

## Consequences

`kernel_only` and `kernel_plus_policy` profiles differ only in policy modules; outcome differences are attributable to them.
