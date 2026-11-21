# ADR-011: Docker delivery for browser runtime and Google Gemini cloud models

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Owner, Architect
- **Requirements affected:** NFR-PORT-01, NFR-SEC-01, NFR-SEC-03, NFR-COST-01, FR-UI-01–02

## Context

The middleware must run reliably on Windows during development, expose an interactive browser Chat & Inspector UI (`C1`), and use Google's cloud Gemini models rather than an air-gapped local LLM. Running directly on a Windows host Python 3.13 environment introduces version skew against `requires-python = ">=3.12,<3.13"` and POSIX-only tooling (`mutmut`). Two open decisions from the gap analysis (`D1` delivery format and `D3` embedding model) also need binding choices before Phase 1 starts.

## Options considered

1. **Native Windows Python + local ONNX embeddings** — avoids Docker; hits Python 3.13 vs. 3.12 mismatch and ships an unnecessary local embedding model when outbound Gemini API access is already configured.
2. **Docker container (Python 3.12 + built React UI) + Google Gemini cloud models** — pins exact Python 3.12 runtime on Windows, serves the browser UI from the same `127.0.0.1:8740` origin, and routes all LLM and embedding calls (`gemini-4-neon`, `gemini-4-carbon`, `gemini-embedding-001`) through `EgressClient` to the single allowlisted host `generativelanguage.googleapis.com:443`.

## Decision

1. **D1 (Delivery & browser runtime):** Package and run the middleware for Windows development via `Dockerfile` + `docker-compose.yml` on `python:3.12-slim` serving the built React/Vite UI at `http://127.0.0.1:8740/`. Inside the container, Uvicorn binds `0.0.0.0:8740` (`DLE_ALLOW_LAN=true`) while Docker Compose publishes ports strictly on Windows loopback (`127.0.0.1:8740:8740`), preserving `NFR-SEC-01`. `E1` configures `Access-Control-Expose-Headers` for `X-DLE-Release-Mode`, `X-DLE-Receipt`, `X-DLE-Tier`, and `X-DLE-API-Version` so browser SDK calls from `http://127.0.0.1:5173` (hot-reload `dev` profile) can read headers.
2. **D3 (Cloud Gemini models & embeddings):** Use Google's cloud Gemini models (`gemini-4-neon` and `gemini-4-carbon`, configured per job in `config/model_pins.yaml`) and `gemini-embedding-001` for text embeddings through `EgressClient`. Air-gapped local LLM operation remains out of scope for v1. Local ONNX execution stays limited to the independent DeBERTa-v3 NLI entailment scorer (`M3`, ADR-006).

## Consequences

- Windows developers run one command (`docker compose up`) to launch both the Python 3.12 middleware and the browser UI, with SQLite stores, keys, and calibration artifacts persisted on named Docker volumes.
- Every live model call and embedding call uses the single allowlisted `generativelanguage.googleapis.com:443` host and is metered by `M2` from dated prices in `config/model_pins.yaml`; `DLE_MODEL_BACKEND=fake` keeps CI and local development free of API charges.
- Any job model pin change (`gemini-4-neon` ↔ `gemini-4-carbon`) still latches calibration (`FR-REL-04`) once calibration artifacts are loaded.
