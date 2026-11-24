# dle-middleware (`v0.1.0`)

Gemini-compatible middleware that executes the **DataLogicEngine (DLE) 13-axis DVSS** architecture (`v3.13`) on every governed request. Applications point an unmodified Python (`google-genai`) or JavaScript (`@google/genai`) Gemini SDK — or use the built-in browser **Chat, Inspector & Ops/Audit UI** — at the gateway; it returns grounded answers with `groundingMetadata` and signed Ed25519 receipts, or structured hold notices when verification fails.

**Status:** **Phases 0–7 complete (`v0.1.0`)** · Containerized release image `dle-middleware:release` (`dle-middleware:0.1.0`) · See [HANDOFF.md](HANDOFF.md), [CHANGELOG.md](CHANGELOG.md), and [reports/phase7_gate.md](reports/phase7_gate.md).

## Quick Start (Docker + Browser UI on Windows / Linux)

1. Copy `.env.example` to `.env` (keep `GEMINI_API_KEY` out of git). Default `DLE_MODEL_BACKEND=fake` runs deterministically offline with zero API spend; set `DLE_MODEL_BACKEND=gemini` and `GEMINI_API_KEY` for Google Gemini cloud models (`gemini-4-neon`, `gemini-4-carbon`, `gemini-embedding-001` per `ADR-011`).
2. Build and run the release container (binds `127.0.0.1:8740` only):

```bash
docker build -t dle-middleware:release -t dle-middleware:0.1.0 .
docker run --rm -p 127.0.0.1:8740:8740 \
  -e DLE_MODEL_BACKEND=fake \
  -e DLE_CALIBRATION_PATH=/app/config/calibration/cal-phase6-v1.json \
  dle-middleware:release
```

3. Open the Browser Chat, Inspector & Ops UI at `http://127.0.0.1:8740/` or check `GET http://127.0.0.1:8740/healthz`.

## SDK Usage

```python
from google import genai

client = genai.Client(
    api_key="dev-client-key",
    http_options={"base_url": "http://127.0.0.1:8740"},
)
r = client.models.generate_content(
    model="dle-13axis-strict",
    contents="Can we substitute model B on bank 4?",
)
print(r.text)  # released answer, or hold notice with resolving evidence requirements
```

Response headers carry `X-DLE-Release-Mode` (`released` | `released_advisory` | `held`), `X-DLE-Receipt`, and `X-DLE-Tier`. Full guide: [docs/guides/developer_quickstart.md](docs/guides/developer_quickstart.md) and [docs/guides/admin_and_hardening_guide.md](docs/guides/admin_and_hardening_guide.md).

## What Is Implemented (Phases 0–7)

- **Gemini Façade & Session/Tool Bridge (`dle/edge/`):** Full OpenAPI surface (`contracts/openapi.yaml`), `generateContent` & `streamGenerateContent` (SSE keepalives, stream-after-gate `ADR-004`), pass-through Gemini models, JCS history-hash sessions (`ADR-003`), `functionCall`/`functionResponse` pass-through + parked runs, and loopback-guarded `/admin/*` endpoints.
- **5 SQLite Stores & Evidence/NLI (`dle/store/`, `dle/models/`):** Schema `0001_init.sql` across `registry`, `evidence`, `sessions`, `receipts`, and `ops`; FTS5 + `sqlite-vec` hybrid retrieval (`gemini-embedding-001`); independent non-LLM NLI (`DeterministicLexicalNliScorer` / pinned DeBERTa-v3 ONNX `ADR-006`); allowlisted `EgressClient` (`generativelanguage.googleapis.com:443` only, verified by AST gate `dle.tools.check_egress_imports`).
- **13-Axis Kernel, Quad Personas & 26 DVSS Functions (`dle/host/`):** All 26 bound DVSS functions (`DVSS-K01`–`K12`, `DVSS-P01`–`P14`) with 52 paired JSON I/O schemas (`contracts/functions/`), 12-step FROST orchestrator, bounded PPR graph traversal, dynamic MDKF Quad personas (`Advocate`, `Skeptic`, `Pragmatist`, `Archivist`) + blind packets, verifier-only ledger, `DVSS-P05` quarantined promotion, `DVSS-P09` advisory analogies, and Ed25519 + pluggable WORM/transparency-log receipt anchoring.
- **Calibration, Drift & Offline Tooling (`offline/`, `dle/tools/`):** `O1` (`offline/calibrate.py`) finite-sample CRC cutoff (`cal-phase6-v1`: `alpha=0.05`, `threshold=0.29`, `mu_0=0.275692`, `drift_lambda=3.3624`) + stationary-block-bootstrap CUSUM drift monitor + fail-closed reset; `O2` (`offline/registry_release.py`); `O3` (`offline/evaluate.py`) pre-registered §17 evaluation engine with 250 sealed held-out query hashes (`offline/registry/heldout_hashes.json`).
- **Browser Chat, Inspector & Admin UI (`ui/`):** React 18 + Vite + TypeScript + `@google/genai` client (`Chat`, `Inspector`, `Sources`, and `Ops & Audit` views with `DriftBanner`, `FunctionFlagsEditor`, `CostByTierChart`, `HealthPanel`, `ExportDialog`, `AddressGraphDrawer`, `PersonaDrawer`, `ClaimsTable`, `ReceiptViewer`), 68 Storybook stories with WCAG 2.2 AA `axe-core` checks.

## Verification & Release Artifacts

| Artifact / Check | Result |
| --- | --- |
| Python test suite (`pytest -q --cov=dle`) | `243 passed, 2 skipped` (`87.49%` coverage >= `85.0%` gate) |
| Static typing & lint (`mypy --strict`, `ruff`, contracts, egress AST) | `73` strict files clean, `52` function schemas valid, `0` forbidden egress imports |
| Gemini SDK compat (`test_python_sdk.py`, `js_sdk_compat.mjs`) | `26` Python SDK cases + `24` JS SDK cases passed |
| Browser UI (`eslint`, `tsc`, `vite build`, `test-storybook`) | `68/68` Storybook + WCAG 2.2 AA `axe-core` tests passed |
| SAST & SCA (`semgrep`, `pip-audit`) | `0` Semgrep findings (`191` rules / `153` files), `0` known CVEs |
| Release artifacts (`reports/`) | [phase7_gate.md](reports/phase7_gate.md), [evaluation_study_report.md](reports/evaluation_study_report.md), [system_card.md](reports/system_card.md), [sbom.cdx.json](reports/sbom.cdx.json) (CycloneDX `1.6`, `51` components), [egress_attestation.md](reports/egress_attestation.md) |

> **Note:** Offline `O3` evaluation used `FakeModel` + `DeterministicLexicalNliScorer`; live Gemini cloud `O3` evaluation, paid-tier data-governance review, FIPS 140-3 crypto validation, SLSA/Sigstore signing, native Windows host test execution, and third-party penetration testing remain tracked in [reports/phase7_gate.md](reports/phase7_gate.md) and [docs/security/product_security_package.md](docs/security/product_security_package.md) prior to external production deployment.

## Repository Layout

```text
contracts/          openapi.yaml, receipt.schema.json (3.8.0), calibration.schema.json,
                    functions/ (52 I/O schemas for 26 bindings), prompts/
config/             functions.yaml, profiles/, tiers.yaml, notices.yaml, model_pins.yaml,
                    calibration/cal-phase6-v1.json, egress_policy.yaml, pilots/
dle/                edge/, host/{workflow,frost,quad,functions,services}, models/, store/, tools/
offline/            calibrate (O1), registry_release (O2), evaluate (O3), pilot/, study/, registry/
reports/            phase1..7 gate reports, evaluation_study_report.md, system_card.md,
                    sbom.cdx.json, egress_attestation.md
tests/              unit/, contract/, engines/, gemini_compat/, security/, perf/, fixtures/
ui/                 Browser Chat, Inspector & Ops/Audit UI (React, Vite, Storybook, axe-core)
docs/               INDEX.md, adr/ (ADR-000..011), specs/, eval/, guides/, ops/, security/, plans/
```

See [docs/INDEX.md](docs/INDEX.md) for the complete document catalog, [SECURITY.md](SECURITY.md) for disclosure policy, and [CONTRIBUTING.md](CONTRIBUTING.md) for development conventions.
