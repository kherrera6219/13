# Phase 5 Exit-Gate Report (`H2`, `DVSS-K10` Complete, Tier Budgets, Cost Metering & Full Admin/Accessibility UI `C1`)

- **Decision:** **PASS** — Phase 5 (`H2` complete `DVSS-K10` Hybrid Intake Router, curated development failure centroids + >= 95% recall on the 50-item dev challenge set, `ModelCallBudget` tier limits `9/21` / `18/22` / `18`, dated USD cost metering, `/admin/function-flags` & `/admin/metrics/cost-by-tier`, Browser Admin/Audit UI `DriftBanner`, `FunctionFlagsEditor`, `CostByTierChart`, `HealthPanel`, `ExportDialog`, full `US-03..17` WCAG 2.2 AA Storybook catalog, and `NFR-PERF-01` overhead benchmark) is complete and cleared for Phase 6.
- **Date:** 2026-11-23
- **Container & Runtime:** Docker `node:22-alpine` UI build + `python:3.12-slim` runtime (`dle-middleware:phase5`, version `0.1.0`)
- **Cloud Model Pins (`ADR-011`):** `gemini-4-neon`, `gemini-4-carbon`, `gemini-embedding-001`

---

## 1. Hybrid Intake Router, Call Budgets & Admin Endpoints (`H2`, `DVSS-K10`, Wave 5A)

- **Development Failure Centroids & Challenge Set (`config/intake/dev_failure_centroids.yaml`, `offline/dev_sets/intake_challenge_dev_50.jsonl`):**
  - Defined 7 failure-mode clusters (`threshold: 0.55`, development data only) and a 50-item dev challenge set without touching held-out data or `tests/fixtures/`.
  - `test_dev_challenge_set_50_tier3_recall_and_benign_specificity` verifies `>= 95%` Tier-3 recall across all 50 challenge items while keeping benign lookup/comparison control queries below Tier 3 (`Z = 0`).
- **`IntakeRouter`, `DVSS-K10` & `ModelCallBudget` (`dle/host/services/intake.py`, `dle/host/functions/stubs.py`, `contracts/functions/k10.{in,out}.json`):**
  - Combines deterministic `K02` pillar band `D` (`0..3`), auditable `score_r_rules` floor + temperature-`0` `job="intake"` model score (`R_final = max(R_rules, R_model)`), rubric ambiguity `M` (`0..3`), deontic/authority/binding flag `B`, and pinned embedding failure-centroid hit `Z` into `S_eff = max(S, 3*B, 6*Z)`.
  - Stores `IntakeDecision.rationale` internally while strictly omitting `rationale` from `to_public_metadata()` and API responses.
  - Enforces per-tier model call ceilings from `config/tiers.yaml` (`9/21` Tier 1, `18/22` Tier 2, `18` Tier 3) in `dle/host/workflow/governed.py`.
- **Metered Cost & Loopback Admin Routes (`dle/store/repositories.py`, `dle/edge/gateway.py`, `dle/config/models.py`, `contracts/openapi.yaml`):**
  - Meters real per-call USD spend from `config/model_pins.yaml` dated pricing across `intake`, `personas`, and `writer` calls into `ops.db` (`run_metrics` / `model_calls`), surfaced via `GET /admin/metrics/cost-by-tier`.
  - Adds authenticated loopback routes `GET /admin/function-flags` and `PUT /admin/function-flags` with `^[A-Za-z_][A-Za-z0-9_.]*$` identifier validation on `ConsequentialFunctionFlag.name`.

---

## 2. Browser Admin/Audit UI & Complete Storybook Catalog (`C1`, `US-03`..`US-17`, `NFR-ACC-01`, Wave 5B)

Executed in `node:22-alpine`:
- `npm run lint` (`eslint . && tsc --noEmit`): **0 errors**
- `npm run build` (`tsc --noEmit && vite build`): **PASS** (`56` modules transformed -> `dist/`)
- `npm run build-storybook`: **PASS** (`148` modules transformed -> `storybook-static/`)
- `npm run test-storybook`: **68 passed (68)** (`src/stories.test.tsx`, `1836 ms`) — verifies WCAG 2.2 AA `>= 4.5:1` light/dark contrast tokens, CSF3 `play` interactions, `axe-core` zero violations across all 18 UI components, and 100% catalog coverage across `US-03` through `US-17`:
  - `DriftBanner` (`HealthyHidden`, `Tripped`, `ResetConfirmationStep1`, `ResetConfirmationStep2` — `US-13`)
  - `FunctionFlagsEditor` (`NoFlags`, `ConsequentialFlagSet`, `SaveError` — `US-14`)
  - `CostByTierChart` (`OneWeek`, `NoData`, `Tier3Spike` — `US-15`)
  - `HealthPanel` (`AllGreen`, `ModelUnreachable`, `NliNotLoaded`, `DriftLatchOn` — `US-13`)
  - `ExportDialog` (`DateRangePicker`, `BuildingBundle`, `Done`, `Failure` — `US-11`)
  - Plus extended `RunSummaryCard` (`S_eff`, `Model Calls`, `Metered Cost`) and live `Ops & Audit` + top `DriftBanner` wiring in `ui/src/App.tsx` / `ui/src/lib/dleClient.ts`.
- Hardcoded hex token compliance check in `ui/src`: **0 findings** outside `ui/src/tokens.css` and `ui/src/stories.test.tsx`.

---

## 3. Performance Benchmark (`NFR-PERF-01`)

Measured in Python 3.12 container over ASGI loopback against in-process `FakeModel` (zero synthetic network wait = pure middleware overhead outside LLM inference):

| Workload | Requests (`n`, post-warmup) | `p50` (ms) | `p95` (ms) | `p99` (ms) | Gate (`< 400 ms` p95) |
| --- | --- | --- | --- | --- | --- |
| Pass-through (`gemini-4-carbon`) | 100 (`+10` warmup) | 0.450 | 0.586 | 0.806 | **PASS** |
| Governed Tier-1 (`dle-13axis-strict`) | 50 (`+5` warmup) | 31.802 | 39.639 | 81.026 | **PASS** |

---

## 4. Full Verification, Coverage, SDK Compat & Security Summary

Verified in Docker (`uv`, Python 3.12, Semgrep, Node 22):
- `uv lock --check`: **PASS** (117 packages resolved)
- `uv run ruff format --check dle tests` (102 files) & `uv run ruff check dle tests`: **PASS** (0 issues)
- `uv run mypy --strict dle` (63 source files): **PASS** (0 issues)
- `uv run python -m dle.tools.validate_contracts`: **PASS**
- `uv run python -m dle.tools.check_egress_imports`: **PASS**
- `uv run pytest -q --cov=dle`: **219 passed, 2 skipped** (`test_js_sdk.py` runs in Node container; opt-in `DLE_LIVE_GEMINI_API_KEY` test skips cleanly), **90.81% coverage** (7976 statements, 733 missed; >= 85% gate)
- `uv run pytest -q tests/gemini_compat/test_python_sdk.py`: **26 passed**
- `node tests/gemini_compat/js_sdk_compat.mjs`: **24 cases passed** (`ok: true`)
- `uv export --frozen --no-hashes --no-emit-project -o /tmp/req.txt && uv run pip-audit --strict --no-deps -r /tmp/req.txt`: **No known vulnerabilities found**
- `uvx semgrep scan --config p/python --config p/secrets --config .semgrep/dle.yml --error dle tests offline`: **191 rules on 132 files, 0 findings**

---

## 5. Production Container E2E Smoke Verification (`dle-middleware:phase5`)

Built multi-stage image `dle-middleware:phase5` (`node:22-alpine` + `python:3.12-slim`) and executed live loopback probe against `127.0.0.1:8740`:
- `GET /healthz` -> `200 OK` (`"nliLoaded": true`, `"kernelFunctions": 12`)
- `GET /` -> `200 OK` (HTML contains `"DataLogicEngine"`)
- `GET /admin/function-flags` -> `200 OK` (`[]`) -> `PUT /admin/function-flags` (`submit_purchase_order`) -> `200 OK` -> persisted on subsequent `GET`
- `POST /admin/sources` -> `201 Created` (`Phase 5 RF Pilot Clause`)
- `POST /v1beta/models/dle-13axis-strict:generateContent` -> `200 OK`, `X-DLE-Release-Mode: released`, `dleMetadata.intake` (`sEff: 1`, `tier: 1`, `rationale` omitted), `runSummary` (`modelCallsUsed: 4`, `modelCallBudget: 9`, `costUsd: 0.001397`), `receiptId = "99c6b538-dbfa-45c3-b6b6-96384b6fcb89"`
- `GET /admin/metrics/cost-by-tier?days=7` -> `200 OK` (`1` day entry, `totalUsd > 0.0`)
- `POST /admin/receipts/export` -> `200 OK`, `application/zip`, valid ZIP archive with `5` entries
- Temporary containers (`dle-compat-srv`, `dle-smoke-p5`) removed cleanly after verification.

---

## 6. Carried Forward to Phase 6

1. **O1 Calibration & Drift Recovery (`offline/calibrate.py`, `DVSS-P14`):** Implement finite-sample Conformal Risk Control cutoff $\hat{t}$ ($\alpha = 0.05$) and fixed-baseline CUSUM parameters ($\mu_0, \delta = 0.02, \lambda$) with `offline/registry/heldout_hashes.json` exclusion enforcement.
2. **Pilot Grading & Strict Mode Production Artifact (`H14`):** Grade ~100 pilot queries with two blind graders + adjudication ($\kappa \ge 0.6$), emit the active `strict` calibration artifact, and verify end-to-end drift latch trigger + `POST /admin/drift/reset` + signed bundle export recovery.
