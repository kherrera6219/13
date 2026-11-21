# Phase 1 backlog · Gemini pass-through (G3)

**Phase goal.** Official Gemini SDKs work against the middleware exactly as against Google, for pass-through models, with the governed path stubbed. Components: E1–E5, M1, M2, C1, plus the H16 skeleton.

**Ticket format.** Each ticket is independent, small enough for one PR, and testable (INVEST). Acceptance criteria use Given/When/Then. "Done" also means the Definition of Done in the SDP (§2): tests on Linux and Windows, lint and type checks, RTM row, docs touched, independent review.

Estimates are story points (1 = a few hours, 3 = about a day, 5 = two to three days).

| ID | Title | Requirements | Depends on | Points |
| --- | --- | --- | --- | --- |
| P1-01 | Repository bootstrap and CI | NFR-PORT-01, NFR-MAINT-01 | — | 3 |
| P1-02 | Contract validation tool | IR-01–07 | P1-01 | 2 |
| P1-03 | Configuration loader and policy digest | FR-FN-03 | P1-01 | 3 |
| P1-04 | Egress client with allowlist | NFR-SEC-03 | P1-01 | 3 |
| P1-05 | Model port, Gemini adapter, fake model | FR-API-03, NFR-REL-02 | P1-04 | 5 |
| P1-06 | Model registry and price table | NFR-COST-01, FR-REL-04 | P1-05 | 2 |
| P1-07 | Gateway: routes, auth, loopback bind | FR-API-01, NFR-SEC-01–02 | P1-02 | 5 |
| P1-08 | Session resolver (history hash) | FR-SES-01–03 | P1-07 | 3 |
| P1-09 | Request translator to RunRequest | FR-API-01, K01 | P1-07 | 3 |
| P1-10 | Pass-through path for non-DLE models | FR-API-02 | P1-05, P1-09 | 3 |
| P1-11 | Tool bridge (pass-through, parked runs) | FR-TOOL-01–03 | P1-10 | 5 |
| P1-12 | Response composer and DLE headers | FR-API-05–06 | P1-10 | 3 |
| P1-13 | SSE streaming with keepalives | FR-API-07, NFR-PERF-02 | P1-12 | 3 |
| P1-14 | H16 function registry skeleton | FR-FN-01–02, FR-FN-04 | P1-03 | 5 |
| P1-15 | Governed-path stub | FR-WF-01 (stub) | P1-12, P1-14 | 3 |
| P1-16 | Structured logging and metrics without content | NFR-PRIV-01, NFR-OBS-01 | P1-07 | 2 |
| P1-17 | Gemini compatibility suite GC-01–GC-26 (P cases) | FR-API-01–03 | P1-13, P1-11 | 5 |
| P1-18 | Chat test UI shell | FR-UI-01 | P1-13 | 5 |
| P1-19 | Phase 1 exit-gate report | Phase gate | P1-17, P1-18 | 1 |
| P1-20 | Migrate the DVSS pilot to 3.8.0 and DVSS IDs | FR-FN-01, FR-RCPT-03 | P1-14 | 3 |

Total: 67 points. P1-20 follows `docs/plans/pilot_migration.md`.

## Tickets

### P1-01 · Repository bootstrap and CI
Create the layout in `README.md`, `pyproject.toml` (uv, ruff, mypy strict, pytest), pre-commit hooks, and the CI workflow (`.github/workflows/ci.yml`) running on Ubuntu and Windows.
- Given a fresh clone, when `uv sync && uv run pytest` runs, then it exits 0 on both OSes.
- Given a PR, when CI runs, then lint, types, tests, Semgrep, pip-audit, gitleaks and SBOM generation all run and any failure blocks merge.

### P1-02 · Contract validation tool
`dle.tools.validate_contracts` validates `contracts/openapi.yaml`, every JSON schema and `config/functions.yaml` against its schema.
- Given a malformed schema, when the tool runs, then it exits non-zero naming the file and pointer.

### P1-03 · Configuration loader and policy digest
Load `config/` into typed models; compute the policy digest as SHA-256 of the JCS-canonical loaded config.
- Given identical config files in different key order, then the digest is identical.
- Given a profile that disables a kernel function, then loading fails with `KernelNotOptional`.

### P1-04 · Egress client with allowlist
Single `EgressClient` over httpx; deny by default; allowlist from config; every call logged with host, bytes and duration, never body.
- Given a call to a host not on the allowlist, then it raises `EgressDenied` and logs the attempt.
- Given the codebase, when the CI rule runs, then any import of httpx, requests, urllib or socket outside `dle/models/egress.py` fails.

### P1-05 · Model port, Gemini adapter, fake model
`ModelPort.generate()` with a Gemini adapter (google-genai SDK through EgressClient) and a deterministic fake for tests. Retries with backoff, at most 3 (NFR-REL-02).
- Given a 503 from upstream twice then 200, then the call succeeds and records 3 attempts.
- Given every attempt fails, then `ModelUnavailable` is raised.

### P1-06 · Model registry and price table
`config/model_pins.yaml` maps job to model ID and holds dated prices. Records `modelVersion` per call.
- Given a request on 2026-12-01 or later, then cost uses $4 / $20 per million tokens for `gemini-4-carbon`.
- Given a changed `modelVersion` versus the calibration artifact, then the drift latch trips (stubbed in phase 1, asserted as an event).

### P1-07 · Gateway: routes, auth, loopback bind
FastAPI app serving every path in `openapi.yaml`; key check on every request; default bind 127.0.0.1:8740.
- Given no key, then 401 with Gemini error body.
- Given `bind: 0.0.0.0` without `allow_lan: true`, then startup fails.

### P1-08 · Session resolver
Session ID = SHA-256 over JCS of {tenant, model, systemInstruction, contents minus the newest user turn}; `X-DLE-Session` overrides.
- Given turn 2 of a chat, then its session ID equals the ID computed after turn 1's response is appended.
- Given a different system instruction, then the session ID differs.

### P1-09 · Request translator
Gemini request to `RunRequest`, validated (K01). Unknown fields kept for pass-through.
- Given a request with an unmodelled field, then the field survives a round trip unchanged.

### P1-10 · Pass-through path
Non-DLE model names go straight to Gemini through the model port.
- Given model `gemini-4-carbon`, then the response equals the upstream response plus DLE headers with mode `passthrough`.

### P1-11 · Tool bridge
Forward tools unchanged; return `functionCall` parts unchanged; park the run keyed by session; on `functionResponse`, resume (phase 1: forward to Gemini).
- Given parallel function calls, then order and IDs are preserved.
- Given a parked run older than the session expiry, then it is purged.

### P1-12 · Response composer
Builds Gemini responses; sets `X-DLE-Release-Mode`, `X-DLE-Receipt`, `X-DLE-Tier`, `X-DLE-API-Version`; holds return STOP with notice text from `config/notices.yaml`.
- Given a stubbed hold, then status 200, `finishReason` STOP and the hold header are present.

### P1-13 · SSE streaming
`alt=sse` streaming; keepalive comments every ≤10 s while the governed path runs; chunked release afterwards.
- Given a 45 s stubbed gate, then the Python and JS SDK streams do not time out.

### P1-14 · H16 function registry skeleton
Load `config/functions.yaml`; register kernel and policy implementations; `invoke(dvss_id, ctx)`; reject KA numbers; startup self-check.
- Given a missing kernel registration, then startup exits naming the DVSS ID.
- Given `invoke("KA-015")`, then `UnboundFunction`.

### P1-15 · Governed-path stub
DLE models call the workflow orchestrator stub, which invokes K01 and K10 stubs, calls the writer through the model port and returns `released_advisory` with a placeholder receipt ID.
- Given `dle-13axis-strict`, then the response carries a tier header and a receipt ID.

### P1-16 · Logging and metrics
structlog JSON logs and Prometheus-style metrics; content redaction enforced by a test that scans logs for request text.
- Given a request containing a canary string, then the canary appears in no log line.

### P1-17 · Compatibility suite
Implement GC-01–GC-26 (P cases) per `docs/test/gemini_compat_test_plan.md` with recorded upstream.

### P1-18 · Chat test UI shell
React + Vite + `@google/genai` chat against the middleware; release badge and receipt chip from response headers; Storybook stories for `ChatComposer`, `MessageBubble`, `ReleaseBadge`.
- Given a held response, then the bubble shows "Held for review" text, not colour alone.

### P1-19 · Exit-gate report
Report in `reports/phase1_gate.md`: compatibility results per SDK and OS, coverage, latency overhead p50/p95 (feeds NFR-PERF-01), open defects.

### P1-20 · Migrate the DVSS pilot to 3.8.0 and DVSS IDs
Follow `docs/plans/pilot_migration.md` (G16): import the legacy 21-test DVSS pilot (`core/pipeline.py`, `core/coordinates.py`, `core/audit.py`, `tests/test_acceptance.py`), replace legacy `KA-0*` identifiers with DVSS IDs, bump receipt outputs to schema 3.8.0 (`profile` and `function_invocations`), and route `route`, `merge_objections`, and `returned_text` through H16 (`DVSS-K10`, `DVSS-K12`, `DVSS-K11`). Note: the legacy pilot source files are external to this scaffold and must be imported before starting Step 1 (or rebuilt from the paper §18 acceptance fixtures if not imported).
- Given the migrated pilot under `tests/engines/legacy_pilot/`, when `pytest` runs, then all 21 acceptance assertions pass.
- Given receipts emitted by the migrated pilot, when validated against `contracts/receipt.schema.json` (3.8.0), then validation succeeds with `function_invocations` recorded for K10, K11, and K12.
- Given `grep` for `KA-0` across `dle/`, then zero matches appear outside `config/catalog/`.
