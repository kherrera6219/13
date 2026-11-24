# Phase 6 Exit-Gate Report (`O1`, `H14`, `DVSS-P14`, Calibration Pilot & Strict Release Mode)

- **Decision:** **PASS** — Phase 6 (`O1` / `DVSS-P14` offline CRC + CUSUM calibration, `offline/registry/heldout_hashes.json` 250-item held-out sealing & `ContaminationError` guard, `n = 100` domain-stratified graded pilot dataset with blind dual-grader Cohen's $\kappa \ge 0.6$, signed `cal-phase6-v1.json` strict release artifact, fail-closed `GatewayRuntime` calibration verification, `POST /admin/drift/reset` approved-artifact enforcement, and signed receipt bundle export verification) is complete and cleared for Phase 7.
- **Date:** 2026-11-23
- **Container & Runtime:** Docker `node:22-alpine` UI build + `python:3.12-slim` runtime (`dle-middleware:phase6`, version `0.1.0`)
- **Cloud Model Pins (`ADR-011`):** `gemini-4-neon` (`gemini-4-neon-001`), `gemini-4-carbon` (`gemini-4-carbon-001`), `gemini-embedding-001` (`gemini-embedding-001-001`)

---

## 1. Held-Out Sealing & Pilot Dataset (`DLE-EVL-001`, `DLE-EVL-002`)

- **Sealed Held-Out Registry (`offline/registry/heldout_hashes.json`):**
  - Stores **250** SHA-256 hashes over RFC 8785 JCS of `(question, as_of_date, source_set)` with zero raw evaluation prose (`heldout_test`: 150, `heldout_challenge`: 100; registry file SHA-256 `d4fb38bf1cb359f6b7396316148030b665f2ea6c8e71a2a54087d64b7c1b09a5`).
  - `offline/calibrate.py` (`dle.host.services.calibration.assert_no_heldout_contamination`) refuses calibration with `ContaminationError` (`DLE-E1502`, exit code `2`) if any input hash matches the sealed registry.
- **100-Query Graded Pilot (`offline/pilot/pilot_graded_100.jsonl`):**
  - Executed **100** fresh pilot trajectories (`40` Tier 1, `35` Tier 2, `25` Tier 3; `82` passing the hard gate, `18` blocked by hard vetoes) through frozen `run_governed_workflow`, verified at `0` overlap against `offline/registry/heldout_hashes.json`.
  - Graded on the three-level scale $\ell \in \{0, 0.5, 1\}$ by two blind graders with adjudication (`exact_agreement = 0.94`, `adjudication_rate = 0.06`, unweighted **Cohen's $\kappa = 0.878247$**, clearing the `>= 0.6` gate).

---

## 2. Calibrated Production Artifact (`config/calibration/cal-phase6-v1.json`)

Generated and verified via `offline/calibrate.py` (`DVSS-P14` / `O1`, validated against `contracts/calibration.schema.json` and `contracts/functions/p14.{in,out}.json`):

| Parameter | Observed Value | Gate / Spec |
| --- | --- | --- |
| `artifact_id` | `cal-phase6-v1` | Approved runtime artifact (`status = "approved"`) |
| `artifact_sha256` | `42b559706eee54a442b6d8314972a75de66f80f184af64541a72028928c849e5` | RFC 8785 JCS verified on startup & `--verify-only` |
| `policy_sha256` | `ac5795382c582655346083f88168a4be4cdfd63b01963d7e9aa67fec5d887692` | Bound to active config policy |
| `n_cal` / `alpha` | `100` / `0.05` | Paper §16b pilot calibration target |
| CRC `threshold` ($\hat{t}$) | `0.29` (grid step `0.005`, strict `<`) | Accepted `52/100` (`empirical_coverage = 0.52`) |
| `accepted_loss_sum` / `corrected_risk` | `0.0` / `0.009901` | `(0 + 1)/(100 + 1) <= 0.05` (`conditional_accepted_loss = 0.0`) |
| CUSUM baseline `mu_0` | `0.275692` (all 100 runs incl. holds) | Paper §16c fixed baseline |
| CUSUM `drift_delta` / `drift_lambda` | `0.02` / `3.3624` | Stationary block bootstrap (`seed = 20261123`) |
| `estimated_in_control_arl` | `1000.92` | Target `>= 1000` |
| `cohen_kappa` | `0.878247` | Required `>= 0.60` |
| `recommended_decay_rates` (`DVSS-P14`) | `stable: 0.0`, `technical: 0.0175`, `amended: 0.0528` | Staged offline diagnostic only |

---

## 3. Fail-Closed Runtime Wiring & Strict Drift Recovery (`H14`)

- `GatewaySettings.calibration_path` (`DLE_CALIBRATION_PATH`, defaulting to `config/calibration/cal-phase6-v1.json`) loads and JCS-verifies the calibration artifact at startup, failing closed (`drift_latched = True`, `/healthz` `"status": "degraded"`, `evaluate_release_gate` block `unapproved_calibration_artifact`) if tampered, missing, unapproved, or below $\kappa = 0.6$.
- `POST /admin/drift/reset` enforces `"confirm": "RESET"` plus an approved on-disk (or active approved) calibration artifact via `find_approved_calibration_artifact`, rejects unknown/staged/tampered IDs with HTTP `400`, reloads calibrated `modelVersion` baselines onto `ModelRegistry`, clears the latch, and persists the audit entry.
- Added `CalibrationError` (`DLE-E1501`) and `ContaminationError` (`DLE-E1502`) to `dle/errors.py`.

---

## 4. Full Verification, Coverage, SDK Compat & Security Summary

Verified in Docker (`uv`, Python 3.12, Semgrep, Node 22):
- `uv run ruff format --check dle tests offline`: **PASS** (`107` files formatted)
- `uv run ruff check dle tests offline`: **PASS** (0 issues)
- `uv run mypy --strict dle offline`: **PASS** (`67` source files, 0 issues)
- `uv run python -m dle.tools.validate_contracts`: **PASS**
- `uv run python -m dle.tools.check_egress_imports`: **PASS**
- `uv run pytest -q --cov=dle --cov-report=term-missing`: **227 passed, 2 skipped** (`67.88s`), **90.44% coverage** (`8494` statements, `812` missed; >= 85% gate)
- `uv run pytest -q tests/gemini_compat/test_python_sdk.py`: **26 passed** (`6.47s`)
- `node tests/gemini_compat/js_sdk_compat.mjs`: **24 cases passed** (`ok: true`)
- `uv export --frozen --no-hashes --no-emit-project -o /tmp/req.txt && uv run pip-audit --strict --no-deps -r /tmp/req.txt`: **No known vulnerabilities found**
- `uvx semgrep scan --config p/python --config p/secrets --config .semgrep/dle.yml --error dle tests offline`: **191 rules on 139 files, 0 findings**

---

## 5. Production Container E2E Smoke Verification (`dle-middleware:phase6`)

Built multi-stage image `dle-middleware:phase6` (`node:22-alpine` 56 Vite modules + `python:3.12-slim`) and ran live loopback E2E on `127.0.0.1:8740`:
- `GET /healthz` -> `200 OK`: `"status": "ok"`, `"calibrationArtifactId": "cal-phase6-v1"`, `"calibrationThreshold": 0.29`, `"driftLatch": "clear"`, `"nliLoaded": true`, `"kernelFunctions": 12`.
- `GET /` -> `200 OK` serving the built Browser UI containing `"DataLogicEngine"`.
- Registered `primary_text` spec -> strict query `released` (`receiptId = "d265f316-5c4f-4c63-bd28-b23952dd8102"`).
- Executed unmatched queries cleanly tripping natural CUSUM (`C_t > 3.3624`) after **13** runs -> subsequent grounded strict query `held` with `NOTICE-HOLD-05` (`receiptId = "71225a8c-4596-4922-8d6c-8daf324eb6e7"`).
- Invalid `POST /admin/drift/reset` (`cal-invalid`) -> `400`; valid `POST /admin/drift/reset` (`cal-phase6-v1`, `confirm: "RESET"`) -> `204` -> grounded strict query `released` (`receiptId = "6e24803d-18e6-4798-81c9-c63a673f97f4"`).
- `POST /admin/receipts/export` -> `/app/.venv/bin/python -m dle.tools.verify_receipt /tmp/p6_bundle.zip` -> **`VERIFIED: /tmp/p6_bundle.zip`** (exit code `0`).
- Temporary containers (`dle-compat-srv`, `dle-smoke-p6`) removed cleanly.

---

## 6. Carried Forward to Phase 7

1. **Deferred Policy Functions (`DVSS-P05`, `DVSS-P09`) & Pluggable External Anchor Hook:** Implement quarantined offline policy promotion staging (`P05`) and non-evidence analogy hypothesis generation (`P09`) with paired `p05`/`p09` contracts, plus external transparency-log anchor interface alongside `local_worm_merkle`.
2. **Pre-Registered Evaluation Study (`O3`, `offline/evaluate.py`):** Evaluate the sealed 150 test + 100 challenge items matched against `offline/registry/heldout_hashes.json` and publish `reports/evaluation_study_report.md`, `reports/system_card.md`, `reports/sbom.cdx.json`, `reports/egress_attestation.md`, and final release gate `reports/phase7_gate.md`.
