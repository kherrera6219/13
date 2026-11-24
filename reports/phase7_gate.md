# Phase 7 Exit Gate Report (`v0.1.0` Release Readiness)

- **Date:** 2026-11-24
- **Target Version:** `0.1.0` (`dle-middleware:release`, `dle-middleware:0.1.0`)
- **Protocol Baseline Commit:** `f09d6eb` (Phase 6 exit) + `0e3697f` (Wave 7A)
- **Status:** **PASS (Local / Containerized CI & Offline Study Gate Cleared; External Production Ops Items Explicitly Open Below)**

## 1. Wave 7A Summary (`0e3697f`)

- **Complete 26-Function Catalog (`52` Schemas):** Added `contracts/functions/{k01,p05,p09}.{in,out}.json`, completing paired input/output schemas for all 26 bound DVSS functions.
- **Policy Functions & Anchoring:** Implemented `DVSS-P05` quarantined TMP node staging (`dle/host/services/promotion.py`), `DVSS-P09` non-citable `[TMP:ANALOGY:...]` cross-domain hypotheses (`dle/host/services/analogy.py`), and pluggable `AnchorProvider` backends (`LocalWormMerkleAnchor`, `CustomerHostedLogAnchor`, `ExternalTransparencyLogAnchor` in `dle/host/services/anchoring.py` with `AnchorPendingError` `DLE-E1405`).

## 2. Pre-Registered Evaluation Study (`O3`, `DLE-EVL-003`)

Executed `offline/evaluate.py` against the sealed held-out registry (`offline/registry/heldout_hashes.json`, SHA-256 `d4fb38bf1cb359f6b7396316148030b665f2ea6c8e71a2a54087d64b7c1b09a5`, `150` eval + `100` challenge items verified) and the `200`-draft labeled extractor set (`offline/dev_sets/extractor_labeled_200.jsonl`) using `FakeModel` + `DeterministicLexicalNliScorer` and approved calibration `cal-phase6-v1` (`alpha=0.05`, `threshold=0.29`).

| Endpoint | Observed Result | 95% Bound / CI | Status |
| --- | --- | --- | --- |
| `H1 · Addressing` (`strict` vs `unaddressed`, n=150) | loss diff `0.0`, cov diff `0.0` | loss CI `[0.0, 0.0]` | `no_directional_difference` |
| `H2 · Roles` (`strict` vs `single_reviewer`, n=150) | loss diff `0.0`, cost diff `+0.001676` USD | loss CI `[0.0, 0.0]` | `no_directional_difference` |
| `H3 · Gate` (`strict`, n=150) | accepted loss `0.0` (`0` err), cov `0.42`, over-abstention `0.461538` | 1-sided 95% upper `0.019773` | `supported` |
| `H4 · Routing` (challenge, n=100) | `40/100` Tier-3 hits (`recall=0.4`, `60` misses) | 1-sided 95% lower `0.317526` | `below_threshold` |
| `M1 · Extractor` (`200` drafts, `266` claims / `133` binding) | claim recall `1.0`, binding recall `1.0` | 1-sided 95% lower `0.988801` | `supported` |
| `M2 · Catalog` (`kernel_plus_policy` vs `kernel_only`, n=150) | loss diff `0.0`, cov diff `0.0` | loss CI `[0.0, 0.0]` | `no_directional_difference` |

- `verify_and_gate_baseline` (n=150): `63/150` (`coverage=0.42`, `accepted_loss_sum=0.0`, `accepted_loss_upper_95=0.019773`).
- Seeded blind dual-grader agreement (`strict` arm): Cohen's kappa = `0.930284`.
- Full artifacts: [evaluation_study_report.md](file:///C:/software/13/dle-middleware/reports/evaluation_study_report.md), [evaluation_study_results.json](file:///C:/software/13/dle-middleware/reports/evaluation_study_results.json), and populated [system_card.md](file:///C:/software/13/dle-middleware/reports/system_card.md) (zero unresolved `{{...}}` placeholders).

## 3. Verification Matrix & Live Release Container E2E

- **Formatting, Lint & Types:** `ruff format --check dle tests offline` (`116` files), `ruff check dle tests offline` (`All checks passed!`), `mypy --strict dle offline` (`Success: no issues found in 73 source files`).
- **Contracts & Egress AST Gate:** `python -m dle.tools.validate_contracts` PASS (`52` function schemas); `python -m dle.tools.check_egress_imports` PASS.
- **Python Test Suite:** `pytest -q --cov=dle` -> `243 passed, 2 skipped` (`87.49%` coverage >= `85.0%` gate).
- **SDK Compatibility:** `tests/gemini_compat/test_python_sdk.py` -> `26 passed`; `tests/gemini_compat/js_sdk_compat.mjs` -> `24 passed` (`{"ok": true}`).
- **Browser UI (`ui/`):** `npm run lint` (`eslint . && tsc --noEmit`) PASS, `npm run build` (`vite build`) PASS, `npm run test-storybook` -> `68/68` stories + WCAG 2.2 AA `axe-core` PASS.
- **Security & SBOM:**
  - `pip-audit --strict --no-deps`: `No known vulnerabilities found`.
  - `semgrep scan --config p/python --config p/secrets --config .semgrep/dle.yml --error dle tests offline`: `Ran 191 rules on 153 files: 0 findings`.
  - `reports/sbom.cdx.json`: CycloneDX `1.6` manifest covering `51` production runtime dependencies.
  - `reports/egress_attestation.md` (`tests/security/test_deny_all_egress.py`): Full Tier-2 workflow egress attestation verified (`11 passed` with `test_evaluation_study.py`).
- **Release Image (`dle-middleware:release`, `dle-middleware:0.1.0`):**
  - `GET /healthz`: `status="ok"`, `version="0.1.0"`, `calibrationArtifactId="cal-phase6-v1"`, `calibrationThreshold=0.29`, `kernelFunctions=12`.
  - `GET /`: HTTP `200` (`427` bytes UI index).
  - Strict + advisory `generateContent` requests, `POST /admin/receipts/export` (`9302`-byte ZIP), and `/app/.venv/bin/python -m dle.tools.verify_receipt /tmp/release_bundle.zip` -> `VERIFIED` (`LIVE_E2E_RELEASE_OK`).

## 4. `DLE-CMR §10` Release Checklist

| Item | Status | Evidence / Scope |
| --- | --- | --- |
| Full `DLE-STP` unit/contract/property/security suite (Linux container CI) | **Verified** | `243 passed, 2 skipped` (`87.49%` cov), `26` Python SDK, `24` JS SDK, `68/68` UI + `axe-core` |
| Native Windows host test execution (outside Docker Linux container) | **Open (Env)** | Executed in Linux Python 3.12 + Node 22 Docker containers on Windows host |
| SAST, SCA & secret scan | **Verified** | Semgrep `0` findings (`191` rules / `153` files), `pip-audit` `0` CVEs, `check_egress_imports` PASS |
| CycloneDX 1.6 SBOM | **Verified** | `reports/sbom.cdx.json` (`specVersion=1.6`, `51` components) |
| Deny-all egress attestation (`DLE-SEC-002 §2`) | **Verified** | `reports/egress_attestation.md` + `tests/security/test_deny_all_egress.py` |
| System Card & calibration currency (`DLE-AIM`) | **Verified** | `reports/system_card.md` populated from `cal-phase6-v1` + `O3` output |
| Live Gemini cloud evaluation & paid-tier data-governance review | **Open (Ops)** | Offline `O3` used `FakeModel`; live Gemini cloud run required before clinical/regulatory prod |
| SLSA Level 3 provenance, Sigstore/Authenticode signing, FIPS 140-3 & 3rd-party pentest | **Open (Ops)** | Release-pipeline / external operational milestones (`product_security_package.md`) |
