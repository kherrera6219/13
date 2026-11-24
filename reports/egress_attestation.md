# Deny-All Egress Attestation Report (`DLE-SEC-002 §2`)

- **Date:** 2026-11-24
- **Release Tag:** `v0.1.0`
- **Scope:** Outbound network egress enforcement across `dle/` and governed Tier-2 workflow execution (`DLE-SEC-002 §2`, `NFR-SEC-03`, `NFR-PRIV-01`).

## 1. Enforcement Architecture

- **Single Egress Chokepoint (`dle/models/egress.py`):** All outbound HTTP(S) traffic flows through `EgressClient`, which validates scheme (`https` only), exact hostname allowlist (`generativelanguage.googleapis.com` from `config/egress_policy.yaml`), and exact port (`443`) fail-closed before opening a transport connection. Unlisted hosts, non-443 ports, and cleartext `http://` raise `EgressDenied` (`DLE-E1101`).
- **AST Import Gate (`dle/tools/check_egress_imports.py`):** Scans `dle/**/*.py` and verifies zero direct imports or dynamic uses of `httpx`, `requests`, `urllib`, `urllib3`, `aiohttp`, `http.client`, or `socket` outside `dle/models/egress.py`.
- **Metadata-Only Audit Log (`ops.db.egress_log`):** Records `host`, `bytes_out`, `bytes_in`, `is_allowed`, and `logged_utc` without persisting request bodies, prompts, retrieved passages, or credentials.

## 2. Attestation Verification

- **Security Test (`tests/security/test_deny_all_egress.py`):** Executes the full Tier-2 governed workflow (`run_governed_workflow` with `GeminiAdapter`, `EgressClient`, and `httpx.MockTransport`) and verifies:
  1. `check_egress_imports(REPO_ROOT)` returns `[]` (zero forbidden network imports).
  2. Every permitted transport request (`>= 5` multi-stage calls spanning embeddings, personas, writer, and claim extraction) targeted only `("https", "generativelanguage.googleapis.com", 443)`.
  3. Disallowed targets (`https://evil.example.com/exfil`, `http://generativelanguage.googleapis.com/v1beta/models`, `https://generativelanguage.googleapis.com:8443/v1beta/models`, and `http://169.254.169.254/latest/meta-data`) raised `EgressDenied` without reaching the transport layer.
  4. `ops.db.egress_log` recorded allowed and denied events with zero leakage of the API key canary or document text.
- **SBOM Baseline (`reports/sbom.cdx.json`):** CycloneDX `1.6` manifest covering `51` production runtime dependencies.
- **Verification Run:** `pytest -q tests/security/test_deny_all_egress.py tests/unit/offline/test_evaluation_study.py` -> `11 passed`.
