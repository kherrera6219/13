# Phase 2 Exit-Gate Report (`H1`, `H5`, `H10`–`H15`, `E6`, `C1`)

- **Decision:** **PASS** — Phase 2 (persistent SQLite + `sqlite-vec` stores, hybrid evidence retrieval, independent NLI & claim extraction, CRC/CUSUM release gating, Ed25519/WORM Merkle 3.8.0 receipts, governed Gemini SDK compatibility `GC-12`/`13`/`25`, and Browser Inspector UI) is complete and cleared for Phase 3.
- **Date:** 2026-11-22
- **Container & Runtime:** Docker `node:22-alpine` UI build + `python:3.12-slim` runtime (`dle-middleware:phase2`, version `0.1.0`)
- **Cloud Model Pins (`ADR-011`):** `gemini-4-neon`, `gemini-4-carbon`, `gemini-embedding-001`
- **Independent NLI (`ADR-006`):** `DeterministicLexicalNliScorer` (`deterministic-lexical-nli-v1`) + SHA-256 verified `OnnxNliScorer` (`onnxruntime==1.32.0`)

---

## 1. Storage, Evidence & Verification Pipeline Summary (`H5`, `H10`–`H15`)

- **5-Database SQLite Architecture (`dle/store/`, `ADR-005`):** WAL mode + `busy_timeout=5000` + section-scoped `0001_init.sql` across `registry.db`, `evidence.db` (`FTS5` + `sqlite-vec v0.1.9` `vec0`), `sessions.db`, `receipts.db`, and `ops.db`. Append-only update/delete triggers verified on `evidence_passages`, `ledger_entries`, `receipts`, `function_records`, and `merkle_checkpoints`.
- **Claim Extractor Benchmark (`ADR-008`, `dle/host/services/claim_extractor.py`):** Offline 30-case frozen golden corpus benchmark (`tests/contract/prompts/test_claim_extractor.py`) validates structured `ClaimExtraction_1_0_0` output and `DVSS-K01` span verification cleanly. *(Live 200-draft macro recall benchmark against cloud `gemini-4-neon` remains scheduled when live Gemini credentials are exercised in evaluation gates.)*
- **Scoring & Release Controller (`dle/host/services/scorer.py`, `verifier.py`, `release.py`):** Verified exact `DVSS-K08` source-age decay and `F-SCORE-01` terminal `u` math against white paper §16c worked values, `DVSS-P04` contradiction objections, `DVSS-K12` veto merge, `DVSS-P12` CUSUM drift monitoring (`DEFAULT_PHASE2_CALIBRATION.drift_lambda=4.0`), `DVSS-K04` hard gate + CRC release table, and `DVSS-K11` notice disclosure.
- **Cryptographic Receipts & Offline CLI Verifier (`dle/host/services/receipts.py`, `dle/tools/verify_receipt.py`):** RFC 8785 JCS canonicalization + Ed25519 envelopes (`signature_b64`, `key_id`, `digest_sha256`, `inclusion_proof_ref`, `verified_checkpoint_sha256`), domain-separated SHA-256 Merkle proofs/checkpoints, ZIP bundle export via `POST /admin/receipts/export`, and tamper-detection CLI tests.
- **Fail-Closed Phase 2 Orchestrator (`dle/host/workflow/governed.py`):** Replaces the Phase 1 stub in `dle/edge/gateway.py` across both `generateContent` and `streamGenerateContent?alt=sse`, sealing valid 3.8.0 receipts on released, held, error (`ModelUnavailable`), and cancelled (`GC-25`) runs.

---

## 2. Governed Gemini SDK Compatibility Matrix (`GC-12`, `GC-13`, `GC-25`)

All 26 Python SDK tests (`google-genai==1.75.0` against live loopback `uvicorn` + `FakeUpstream`) and all 24 JS SDK checks (`@google/genai==3.6.1` in `node:22-alpine`) pass, adding governed `G`-mode verification on top of Phase 1 pass-through parity:

| Case | Feature | Python SDK | JS SDK | Verification Details |
| --- | --- | --- | --- | --- |
| `GC-01`–`GC-11`, `GC-14`–`GC-24`, `GC-26` | Pass-through & multi-turn feature parity | PASS | PASS | Preserves tools, search/code/url metadata, thinking, 500k context, unknown fields |
| `GC-12` | Governed `groundingMetadata` & 3.8.0 receipt | PASS | PASS | Registers `primary_text` clause via `/admin/sources`, receives `X-DLE-Release-Mode: released`, `groundingChunks`/`groundingSupports`, and verifies Ed25519 receipt offline |
| `GC-13` | Governed hold `STOP` & headers | PASS | PASS | Ungrounded query on `dle-13axis-strict` returns `200`, `finishReason: STOP`, `X-DLE-Release-Mode: held`, valid UUID `X-DLE-Receipt` (`abstained` / `hard_veto_block`) |
| `GC-25` | Governed stream cancellation (`alt=sse`) | PASS | N/A | Receives initial `\n\n` keepalive during `1.2s` writer delay, aborts stream early, confirms `release_mode='cancelled'` persisted in `receipts` table |

---

## 3. Browser Inspector UI & Storybook (`C1`, `FR-UI-01..02`)

Executed in `node:22-alpine`:
- `npm ci` + `npm run lint` (`eslint . && tsc --noEmit`): **0 errors**
- `npm run build` (`vite build`): **PASS** (46 modules -> `dist/`)
- `npm run build-storybook`: **PASS** (125 modules -> `storybook-static/`)
- `npm run test-storybook`: **30 passed (30)** — WCAG 2.2 AA `>= 4.5:1` light/dark contrast token suite plus CSF3 `play` interactions and `axe-core` zero-violation checks across `ReleaseBadge`, `ReceiptChip`, `ChatComposer`, `MessageBubble`, `CitationList` (`US-04`), `ClaimsTable` (`US-07`), `ReceiptViewer` (`US-09`/`US-10`), and `SourceRegistryTable` (`US-12`).
- App wiring (`ui/src/App.tsx`): Accessible `Chat & Inspector` | `Sources Admin` workspace tabs, Settings `X-DLE-Admin-Key` session input, auto-fetched receipt claim/envelope inspection, and live source registration UI.

---

## 4. Full Verification, Coverage & Security Summary

Verified in Docker (`uv`, Python 3.12, Semgrep, Node 22) after final Wave 2C edits:
- `uv lock --check`: **PASS**
- `uv run ruff format --check dle tests` (80 files) & `uv run ruff check dle tests`: **PASS** (0 issues)
- `uv run mypy --strict dle` (48 source files): **PASS** (0 issues)
- `uv run python -m dle.tools.validate_contracts`: **PASS**
- `uv run python -m dle.tools.check_egress_imports`: **PASS**
- `uv run pytest -q --cov=dle`: **181 passed, 1 skipped** (`test_js_sdk.py` runs in Node container), **89.68% coverage** (>= 85% gate)
- `uv run pytest -q tests/gemini_compat/test_python_sdk.py`: **26 passed**
- `node tests/gemini_compat/js_sdk_compat.mjs`: **24 cases passed** (`ok: true`)
- `uv run pip-audit --strict`: **No known vulnerabilities found**
- `uvx semgrep scan --config p/python --config p/secrets --config .semgrep/dle.yml --error dle tests`: **191 rules on 100 files, 0 findings**

---

## 5. Production Container E2E Smoke Verification (`dle-middleware:phase2`)

Built multi-stage image `dle-middleware:phase2` (`node:22-alpine` + `python:3.12-slim`) and verified end-to-end loopback workflow on `127.0.0.1:8740`:
- `GET /healthz` -> `200 OK` (`"status":"ok"`, `"nliLoaded":true`, `"kernelFunctions":12`, `"driftLatch":"clear"`)
- `GET /` -> `200 OK` (serves Vite-built Browser Inspector UI)
- `POST /admin/sources` -> `201 Created` (`authorityClass: primary_text`)
- `POST /v1beta/models/dle-13axis-strict:generateContent` (grounded clause) -> `200 OK`, `X-DLE-Release-Mode: released`, `groundingMetadata` populated
- `GET /v1/receipts/{receiptId}` -> `200 OK`, `schema_version: "3.8.0"`, `release_mode: "gate_passed"`
- `POST /v1beta/models/dle-13axis-strict:generateContent` (ungrounded clause) -> `200 OK`, `X-DLE-Release-Mode: held`

---

## 6. Carried Forward to Phase 3
1. Implement full 13-axis coordinate builder/validator (`H3`) and Axis-13 valid-time matcher (`H4` `tle`).
2. Implement bounded graph neighborhood expansion (`H6`, `DVSS-K07`/`K03`, <= 10% expansion overhead) over registered source relations.
3. Implement and validate the Phase 3 Warehouse Substitution domain pilot (`D4`).
