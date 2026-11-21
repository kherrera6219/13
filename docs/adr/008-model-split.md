# ADR-008: Gemini 4 Carbon for personas and writer, a cheaper model for intake and extraction

- **Status:** Proposed
- **Date:** 2026-11-20
- **Deciders:** AI risk owner
- **Requirements affected:** NFR-COST-01, FR-VER-01

## Context

Gemini 4 Carbon costs $4 / $20 per million input / output tokens from 2026-12-01. Intake and extraction are high-volume, structured jobs.

## Options considered

1. **Carbon everywhere** — simplest; highest cost.
2. **Cheaper Gemini model for intake and extraction** — lower cost; extractor recall may drop.

## Decision

Pending the G7 measurement: adopt option 2 only if extractor recall on the labeled set is within 2 points of Carbon.

## Consequences

Each job has its own pin in `config/model_pins.yaml`; a pin change latches calibration.
