# Multi-phase build plan

**Document ID:** DLE-PLN-002 · **Version:** 1.0.0 · **Status:** Implemented (Phases 0–7 complete, v0.1.0) · **Owner:** Tech lead · **Date:** 2026-11-24

This plan organizes implementation of `dle-middleware` across Phases 0–7 for **Docker on Windows**, a **browser-first Chat & Inspector UI (`C1`)**, and **Google Gemini cloud models** (`gemini-4-neon`, `gemini-4-carbon`, `gemini-embedding-001`) per **ADR-011**.

---

## 1. Runtime & Delivery Architecture

| Layer / Concern | Choice | Notes |
| --- | --- | --- |
| **Container runtime (D1)** | `Dockerfile` (`node:22-alpine` UI build + `python:3.12-slim` + `uv`) + `docker-compose.yml` | Container binds `0.0.0.0:8740` (`DLE_ALLOW_LAN=true`); host port published strictly on `127.0.0.1:8740:8740` (`NFR-SEC-01`). |
| **Browser UI (`C1`)** | React + Vite + TypeScript + `@google/genai` | Served from `ui/dist` at `http://127.0.0.1:8740/` (and Vite hot reload on `127.0.0.1:5173` under `dev` profile). `E1` exposes `X-DLE-*` headers via CORS `Access-Control-Expose-Headers`. |
| **Cloud Gemini models (D3)** | `gemini-4-neon` (`$3/$15`), `gemini-4-carbon` (`$4/$20` from 2026-12-01), `gemini-embedding-001` (`$0.15/1M`) | All calls route through `EgressClient` to `generativelanguage.googleapis.com:443` and are metered from `config/model_pins.yaml`. |
| **Independent NLI scorer** | Local DeBERTa-v3 ONNX (`M3`, ADR-006) | Not a generative LLM; guarantees entailment verification is independent of the generator. |
| **Zero-spend dev toggle** | `DLE_MODEL_BACKEND=fake` (default) vs. `gemini` | `GEMINI_API_KEY` stays in gitignored `.env`; CI and unit/engine tests run offline against deterministic fakes. |

---

## 2. Phase Overview

### Phase 0 · Pre-Flight & Containerized Dev Environment
- Lock in **ADR-011** (D1 Docker + browser UI; D3 cloud Gemini models & `gemini-embedding-001`).
- Update `config/model_pins.yaml` and `docs/vendor/gemini_4_carbon_verification.md` with verified `gemini-4-neon` and `gemini-embedding-001` pricing.
- Add `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, and scope Ruff in `.github/workflows/ci.yml` to `dle tests`.
- **Exit gate:** `pytest` passes (55 tests), Ruff passes on `dle tests`, configs parse cleanly.

### Phase 1 · Gemini Pass-Through, Browser Chat UI & H16 Skeleton (`P1-01`–`P1-20`)
Ref: `docs/backlog/phase1_backlog.md` · Components: `E1`–`E5`, `M1`, `M2`, `H16`, `C1`.

| Wave | Tickets | Deliverables |
| --- | --- | --- |
| **1A · Foundation** | `P1-01`, `P1-02`, `P1-03`, `P1-04`, `P1-16` | `dle/errors.py`, `dle.tools.validate_contracts`, `dle.tools.check_egress_imports`, typed `dle/config/` + JCS policy digest (`KernelNotOptional`), `dle/models/egress.py` allowlisted `httpx` client, structlog JSON logging + content-redaction test. |
| **1B · Model & Edge** | `P1-05`, `P1-06`, `P1-07`, `P1-08`, `P1-09` | `ModelPort` + `GeminiAdapter` (≤ 3 retries) + `FakeModel`; `M2` registry & cost meter; `E1` FastAPI app (`openapi.yaml` routes, key auth, CORS headers, `/healthz`, static UI); `E2` JCS history-hash session resolver; `E3` translator (`DVSS-K01`). |
| **1C · Tools, SSE & H16** | `P1-10`, `P1-11`, `P1-12`, `P1-13`, `P1-14`, `P1-15`, `P1-20` | Pass-through path; `E4` tool bridge (`functionCall` pass-through + parked runs); `E5` response composer (`X-DLE-*` + `STOP` holds); SSE streaming with ≤ 10 s keepalives; `H16` dispatcher (`invoke("DVSS-...")`, rejects `KA-*`, startup self-check); governed-path stub; `P1-20` §18 pilot migration onto `H16` + 3.8.0 receipts. |
| **1D · Browser UI & Compat** | `P1-18`, `P1-17`, `P1-19` | `ui/` React + Vite + `@google/genai` + `tokens.css` (`ChatComposer`, `MessageBubble`, `ReleaseBadge`, `ReceiptChip`, Storybook); `tests/gemini_compat/` (`GC-01`–`GC-26` P cases, Python + JS SDKs); `reports/phase1_gate.md`. |

- **Exit gate:** `docker compose up` serves browser chat at `http://127.0.0.1:8740`; unmodified Python and JS Gemini SDKs pass all P cases; CI green on Linux and Windows.

### Phase 2 · Verify, Gate, Receipts & Browser Inspector
Components: `H5`, `H10`, `H12`–`H15`, `M3`, `M4`, `E6`, `dle/store/` · Functions: `K04`, `K05`, `K08`, `K11`, `K12`, `P04`, `P12`, `P13`.
- **Stores:** Migration runner for `0001_init.sql` across all 5 SQLite DBs (`registry`, `evidence`, `sessions`, `receipts`, `ops`) + append-only trigger tests.
- **Evidence & Scoring:** `H5` evidence service (FTS5 + `sqlite-vec` using `M4` `gemini-embedding-001`, `DVSS-K05` idempotency); `M3` pinned DeBERTa-v3 ONNX NLI; `H10` claim extractor + 200-draft recall benchmark deciding **ADR-008** (`gemini-4-neon` vs `gemini-4-carbon`); `H12` verifier, `H13` scorer (`DVSS-K08` + terminal $u$), `H14` release controller (`DVSS-K04`, `K11`, `K12`, `P04`, `P12` fallback, `P13`).
- **Receipts & Admin:** `H15` JCS + Ed25519 + local WORM Merkle checkpoints + `GET /v1/receipts/{id}` + offline CLI verifier; `E6` `/admin/sources`, `/v1/sources`, `/admin/keys/rotate`.
- **Browser UI:** `CitationList`, `ClaimsTable` (weakest $z$ first), `ReceiptViewer`, **Sources** upload/admin view.
- **Integrity:** Function I/O schemas under `contracts/functions/`; Level 4 components (`H11`–`H16`, `M3`) achieve 100% branch coverage and ≥ 90% mutation score.
- **Exit gate:** Browser registers documents, cites grounded passages, holds unsupported claims with notices, and verifies receipts; `GC-12`/`GC-13` pass.

### Phase 3 · 13-Axis Address, Spine & Bounded Graph Retrieval
Components: `H3`, `H4`, `H6`, `H7`, `O2` · Functions: `K02`, `K06`, `K07`, `P01`, `P03`, `P06` · FROST `l01`, `l02`, `l06`, `l07`.
- `H3`/`O2`: Load Axis 1–2 CSVs + Axis 3–7, 12–13 JSONLs, rewrite Axis 1 aliases, reject `status: fixture` outside tests, compute manifest SHA-256, build `offline/registry_release.py`.
- `H4`/`K02`/`K06`/`P01`: Nuremberg parsing, mandatory slot states, Axis 12 resolution, `dle.temporal` half-open intervals, jurisdiction precedence.
- `H6`/`H7`/`K07`/`P03`/`P06`: Deterministic PPR ($\alpha=0.85$, ≤ 80 iterations, ≤ 250 vertices, ≤ 4 hops, `distance_weights` `w3`/`w67`, post-hydration re-budgeting); per-session `USKD` overlay (depth ≤ 7 branches, `[TMP:5.TMP.<uuid>]`).
- **Browser UI:** 13-Axis Address & Evidence Graph drawer.
- **Exit gate:** Coordinate and PPR fixtures pass; PPR runs behind a switch alongside dense retrieval.

### Phase 4 · Quad Persona Engine, Ledger, Retries & Escalation *(Minimum Conforming Profile §18b)*
Components: `H1`, `H8`, `H9`, `H11` · Functions: `K03`, `K09`, `P02`, `P07`, `P08`, `P10`, `P11` · Steps `s01`–`s12` & Layers `l01`–`l10`.
- `H8`: Build-time reference fetcher (`config/reference/manifest.yaml`: CIP 2020, CIP-SOC, O*NET); dynamic 7-field MDKF profile builder + `M = 0.25E + 0.45C + 0.30X` (`K03`, `P10`); sealed packets with `config/personas/conduct.yaml`, PPR-mass token allocation (`P08` + fallback), blinded mode, Tier 3 falsification prompts (`P11`).
- `H1`/`H9`/`H11`: Verifier-only append-only ledger (`K12`), writer (`writer-1.0.0`), Pareto options (`P02`), 12-step orchestrator with cutoff-blind retries (`K09`, ≤ 2 retries), one-time Regulator escalation (`P07`), tool park/resume at Step 4, consequential function flags (`config/function_flags.yaml`).
- **Browser UI:** `RunSummaryCard`, `PersonaChips`, `StepTimeline`, `PersonaDrawer`.
- **Exit gate:** All paper §18 conformance fixtures pass against both fake and live Gemini calls.

### Phase 5 · Hybrid Intake Router, Tiers & Full Admin/Accessibility Polish
Components: `H2`, `C1` · Function: `K10` complete.
- `H2`/`K10`: Implement `docs/specs/intake_scoring.md` ($D$, rule-floor + model $R$, rubric $M$, deontic + model $B$, `gemini-embedding-001` failure-centroid $Z$, $S_{\text{eff}} = \max(S, 3B, 6Z)$) and enforce tier call budgets (`9/21`, `18/22`, `18`).
- `C1`: Complete `DriftBanner`, `FunctionFlagsEditor`, `CostByTierChart`, `HealthPanel`, `ExportDialog`, and full WCAG 2.2 AA Storybook catalog; measure p50/p95 overhead (`NFR-PERF-01`).
- **Exit gate:** Router fixtures pass; ≥ 95% recall on the 50-item development challenge set; Storybook & axe CI green.

### Phase 6 · Calibration Pilot & Strict Release Mode
Components: `O1`, `H14` · Function: `P14`.
- Build `offline/calibrate.py` (`O1`): finite-sample CRC cutoff $\hat{t}$ ($\alpha = 0.05$) and fixed-baseline CUSUM ($\mu_0, \delta=0.02, \lambda$), enforcing `offline/registry/heldout_hashes.json` exclusion.
- Grade ~100 pilot queries (2 blind graders + adjudication, $\kappa \ge 0.6$); enable `POST /admin/drift/reset` and `POST /admin/receipts/export`.
- **Exit gate:** Production `strict` profile calibrated and active; drift latch recovery verified.

### Phase 7 · Pre-Registered Evaluation Study & Release Hardening
Components: `O3`, `P05`, `P09`.
- Build `offline/evaluate.py` (`O3`) running frozen `docs/eval/study_protocol.md` (`H1`–`H4`, `M1`, `M2` `kernel_only` vs `kernel_plus_policy`, verify-and-gate baseline) on 300 calibration + 150 held-out test + 100 held-out challenge queries.
- Optional deferred features: `DVSS-P05`, `DVSS-P09`, customer/external transparency-log anchoring.
- Generate populated System Card (`docs/templates/system_card_template.md`), deny-all egress attestation, CycloneDX SBOM, and signed release container image.
- **Exit gate:** Study report published, System Card populated, `DLE-CMR §10` release checklist complete.

---

## 3. Open Items Deferred to Later Phases

| Item | Timing | Default / Options |
| --- | --- | --- |
| **D4 · Pilot domain corpus** | Phase 3 | Seed Warehouse Substitution first (fixtures exist), then add a regulated domain corpus. |
| **P1-20 · Legacy 21-test DVSS pilot** | Phase 1 Wave 1C | Import external pilot source files if provided, or construct the 21 §18 acceptance tests directly from white paper §18 and Appendix G. |
