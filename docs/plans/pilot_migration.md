# Pilot migration plan: contracts 3.7.1 → 3.8.0 and DVSS IDs (G16)

**Document ID:** DLE-PLN-001 · **Version:** 0.1.0 · **Status:** Draft · **Owner:** Tech lead · **Date:** 2026-11-20

The DVSS pilot (21 passing tests) proves routing, ledger merge, coordinates and receipts, but uses contracts 3.7.1 and legacy KA naming. Migrating it keeps its tests as regression coverage for the middleware's host core.

| Step | Change | Check |
| --- | --- | --- |
| 1 | Copy `core/pipeline.py`, `core/coordinates.py`, `core/audit.py` and `tests/test_acceptance.py` into `dle/host/services/` and `tests/engines/legacy_pilot/` unchanged | 21 tests pass in the new layout |
| 2 | Replace any KA-number identifiers and comments with DVSS IDs per the binding table | grep for `KA-0` in code returns only `config/catalog/` |
| 3 | Bump receipt payload to schema 3.8.0: add `profile` and `function_invocations` | Receipt tests validate against `contracts/receipt.schema.json` |
| 4 | Route `route`, `merge_objections`, `returned_text` through H16 as K10, K12 and K11 implementations | Engine tests show FunctionRecords for each call |
| 5 | Replace the pilot's `closure_verifier` hook with the verifier service interface | Ledger tests unchanged and passing |
| 6 | Delete the copied legacy modules once their logic lives in `dle/host/functions/kernel/` | Mutation score on K09, K11, K12 ≥ 90% |

Exit: all 21 original assertions pass against the migrated code, plus the new function-record checks. Scheduled during phase 1 (ticket to be added as P1-20).
