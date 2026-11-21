# ADR-006: Local ONNX NLI for entailment

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Architect, AI risk owner
- **Requirements affected:** FR-VER-01, NFR-SEC-03

## Context

Verification must be independent of the model it checks and must not add a second egress path.

## Options considered

1. **Pinned local NLI model (DeBERTa-v3 class) in ONNX Runtime** — independent, reproducible, CPU-capable.
2. **Gemini as judge** — no extra model; not independent; adds calls and cost.

## Decision

Option 1, with model, tokenizer, segmentation and aggregation versioned and hash-checked at load.

## Consequences

Multi-hop reasoning errors may evade single-premise NLI; recorded as a known limit in the system card.
