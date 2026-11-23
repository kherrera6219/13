# Phase 1 Exit-Gate Report (`P1-19` · Gates G3 & G4)

- **Decision:** **PASS** — Phase 1 (Gemini pass-through, governed stub, UI shell, H16 registry skeleton, §18 pilot migration) is complete and cleared for Phase 2.
- **Date:** 2026-11-22
- **Container & Runtime:** Docker `python:3.12-slim` + `node:22-alpine` (`dle-middleware:phase1`, version `0.1.0`)
- **Cloud Model Pins (`ADR-011`):** `gemini-4-neon`, `gemini-4-carbon`, `gemini-embedding-001`

---

## 1. Gemini SDK Compatibility Matrix (`P1-17`, Gate G4)

All Phase 1 pass-through (`P`) cases from [`docs/test/gemini_compat_test_plan.md`](../docs/test/gemini_compat_test_plan.md) ran against a live loopback DLE middleware instance backed by recorded-replay `FakeUpstream` (`tests/gemini_compat/fake_upstream.py`). Phase 2 governed-only cases (`G`-only: `GC-12`, `GC-13`, `GC-25`) remain scheduled for Phase 2 gate entry.

| Case | Feature | Python (`google-genai==1.75.0`) | JS (`@google/genai==3.6.1`) | Notes |
| --- | --- | --- | --- | --- |
| `GC-01` | List models & pagination | PASS | PASS | Prepends `models/dle-13axis-strict` & `advisory` on initial page |
| `GC-02` | Get model | PASS | PASS | Resolves virtual and upstream Gemini models |
| `GC-03` | Single-turn text | PASS | PASS | Both pass-through and `dle-13axis-strict` stub (`STOP`) |
| `GC-04` | System instruction | PASS | PASS | Forwarded; alters deterministic JCS session hash |
| `GC-05` | Multi-turn chat | PASS | PASS | Full history preserved; continuous post-response session ID |
| `GC-06` | Generation config & JSON schema | PASS | PASS | `temperature`, `maxOutputTokens`, `responseMimeType`, `responseSchema` |
| `GC-07` | Streaming & keepalives | PASS | PASS | Blank-line SSE heartbeats compatible with both SDKs (`ADR-004` note) |
| `GC-08` | Count tokens | PASS | PASS | Exact upstream token counts returned |
| `GC-09` | Auth header & `?key=` / 401 | PASS | PASS | Both accepted; invalid key returns 401 `UNAUTHENTICATED` |
| `GC-10` | Invalid request | PASS | PASS | 400 `INVALID_ARGUMENT` maps to SDK `ClientError` / `ApiError` |
| `GC-11` | Rate limit retry | PASS | PASS | 429 `RESOURCE_EXHAUSTED` preserves SDK retry behavior |
| `GC-12` | Grounding metadata parse (G) | — | — | Scheduled for Phase 2 (`G`-only gate) |
| `GC-13` | Held answer STOP / headers (G) | — | — | Scheduled for Phase 2 (`G`-only gate; unit-verified via `test_gateway.py`) |
| `GC-14` | Function calling, single | PASS | PASS | `functionCall` and `functionResponse` round-trip |
| `GC-15` | Function calling, parallel | PASS | PASS | Preserves order and IDs of parallel calls |
| `GC-16` | Automatic function calling | PASS | N/A | Python SDK executes callable loop cleanly through middleware |
| `GC-17` | Tool config modes | PASS | PASS | `AUTO`, `ANY`, `NONE` honored |
| `GC-18` | Function call with ID | PASS | PASS | `id` preserved across call/response |
| `GC-19` | Inline image input | PASS | PASS | `inlineData` image payload forwarded |
| `GC-20` | Google Search tool | PASS | PASS | `groundingChunks` and `groundingSupports` preserved |
| `GC-21` | URL context tool | PASS | PASS | `urlContextMetadata` preserved |
| `GC-22` | Code execution tool | PASS | PASS | `executableCode` and `codeExecutionResult` preserved |
| `GC-23` | Thinking config | PASS | PASS | `thinkingConfig` & thought parts pass through |
| `GC-24` | Large context (~500k tokens) | PASS | PASS | Passes within middleware limits |
| `GC-25` | Cancellation (G) | — | — | Scheduled for Phase 2 (`G`-only gate; cancellation callback tested in unit suite) |
| `GC-26` | Unknown future fields | PASS | PASS | Extra request & response fields deep-copied untouched |

### Implementation Finding During G4 Verification
- `google-genai==1.75.0` (`HttpResponse._iter_response_stream`) parses only blank lines and `data: ` lines and raises `UnknownApiResponseError` on SSE `:` comments (`: keepalive\n\n`). Emitting blank-line SSE keepalive frames (`\n\n`, exported as `KEEPALIVE_FRAME`) keeps long-running governed connections alive within `<= 10 s` across both Python (`google-genai`) and JS (`@google/genai`) SDKs cleanly. Recorded in [`docs/adr/004-stream-after-gate.md`](../docs/adr/004-stream-after-gate.md).

---

## 2. Pass-Through Latency Overhead (`NFR-PERF-01`)

Measured over 200 sequential loopback HTTP `POST /v1beta/models/gemini-4-carbon:generateContent` requests against live `uvicorn` (`dle.edge.gateway`) backed by in-process `FakeModel` (20 warmup requests excluded):

| Metric | Value | Notes |
| --- | --- | --- |
| Requests (`n`) | 200 | Loopback HTTP JSON round-trip after warmup |
| **p50 latency** | **0.816 ms** | Full HTTP + auth + JCS session hash + translator + composer |
| **p95 latency** | **1.786 ms** | Well inside `NFR-PERF-01` pass-through overhead budget |
| **p99 latency** | **3.528 ms** | Observed tail over local container loopback |

---

## 3. UI & Storybook Verification (`P1-18`, `FR-UI-01`)

Executed in `node:22-alpine`:
- `npm ci` + `npm run lint` (`eslint . && tsc --noEmit`): **0 errors**
- `npm run build` (`vite build`): **PASS** (`dist/index.html`, `dist/assets/index-DAb5AKsY.js`)
- `npm run build-storybook`: **PASS** (`storybook-static/` built cleanly with `@storybook/react-vite`)
- `npm run test-storybook`: **20 passed (20)** — verifies WCAG 2.2 AA `>= 4.5:1` token contrast across light & dark themes (`ui/src/tokens.css`), plus CSF3 `play` interactions and `axe-core` checks across `ReleaseBadge`, `ReceiptChip`, `ChatComposer`, and `MessageBubble` stories.

---

## 4. Python Test Suite, Static Analysis & Security Summary

Executed in Python 3.12 Docker (`uv.lock` pinned with 117 packages):
- `uv lock --check`: **PASS**
- `uv run ruff format --check dle tests` (61 files) & `uv run ruff check dle tests`: **PASS** (0 issues)
- `uv run mypy --strict dle` (35 source files): **PASS** (0 issues)
- `uv run python -m dle.tools.validate_contracts`: **PASS**
- `uv run python -m dle.tools.check_egress_imports`: **PASS**
- `uv run pytest -q --cov=dle`: **161 passed, 1 skipped** (JS test runs in Node container), **89.49% coverage** (>= 85% gate)
- `uv run pytest -q tests/gemini_compat`: **23 passed, 1 skipped**
- `uv run pip-audit --strict --no-deps`: **No known vulnerabilities found**
- `uvx semgrep scan --config p/python --config p/secrets --config .semgrep/dle.yml --error`: **197 rules across 320 files, 0 findings**

---

## 5. Production Container & Browser UI Smoke Verification (`ADR-011`)

Built multi-stage image `dle-middleware:phase1` (`node:22-alpine` UI build + `python:3.12-slim` runtime) and verified loopback container on `127.0.0.1:8740`:
- `GET /healthz` -> `200 OK` (`"status":"ok"`, `"kernelFunctions":12`, `"driftLatch":"clear"`)
- `GET /` -> `200 OK` (serves Vite-built React Chat UI)
- `GET /assets/index-DAb5AKsY.js` -> `200 OK` (`630984` bytes)
- `POST /v1beta/models/dle-13axis-strict:generateContent` -> `200 OK` with `X-DLE-Release-Mode: released_advisory`, `X-DLE-Tier: 1`, `X-DLE-API-Version: 1.0`, UUID `X-DLE-Receipt`.

---

## 6. Open Items Carried to Phase 2

1. Persistent SQLite stores (`0001_init.sql` across all 5 DBs) & append-only triggers (`H15`).
2. Real verification & release pipeline (`H5` FTS5 + `sqlite-vec` + `gemini-embedding-001`, `M3` ONNX NLI, `H10`–`H14`, `H15` JCS + Ed25519 + WORM Merkle receipts) replacing Phase 1 `run_governed_stub`.
3. Enable governed (`G`-mode) cases `GC-12`, `GC-13`, `GC-25` in `tests/gemini_compat/` at Phase 2 exit gate.
4. Expand browser UI from chat/header shell (`P1-18`) to full citations, claims table, receipt viewer, and admin sources views (`P2+`).
