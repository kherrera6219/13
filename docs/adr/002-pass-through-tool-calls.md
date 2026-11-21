# ADR-002: Pass all tool and function calls through unblocked

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Tech lead
- **Requirements affected:** FR-TOOL-01–05

## Context

End users of client applications may need any Gemini tool or function. Blocking them would break applications.

## Options considered

1. **Pass through, govern the evidence** — tools work; tool results are weighted evidence; consequential functions add Regulator review.
2. **Allowlist tools** — tighter control; breaks unknown applications.

## Decision

Forward tool declarations and `functionCall` parts unchanged; ingest `functionResponse` as `app_tool` evidence; flagged consequential functions trigger Regulator review, never a block.

## Consequences

The middleware never executes tools, so excessive-agency risk stays with the client. Tool results can be wrong; their lower authority class limits their weight in u.
