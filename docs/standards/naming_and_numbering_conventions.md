# Naming and numbering conventions

**Document ID:** DLE-STD-001 · **Version:** 1.0.0 · **Status:** Accepted · **Owner:** Tech lead · **Applies to:** every document, code file, config file, test, ticket and artifact in the 13-axis middleware.

One rule underlies everything below: **an identifier is assigned once, never reused, and never changes meaning.** A retired item keeps its ID with status `Retired`. Where this file and another document disagree, this file wins and the other document is corrected.

## 1. Identifier registry

| Thing | Format | Example | Assigned by | Where it lives |
| --- | --- | --- | --- | --- |
| Document | `DLE-<CODE>` or `DLE-<CODE>-<nnn>` | `DLE-SRS`, `DLE-STD-001` | Tech lead | §1 of the documentation set |
| Functional requirement | `FR-<AREA>-<nn>` | `FR-SES-01` | SRS owner | DLE-SRS |
| Non-functional requirement | `NFR-<ATTR>-<nn>` | `NFR-SEC-03` | SRS owner | DLE-SRS |
| Interface requirement | `IR-<nn>` | `IR-05` | ICD owner | DLE-ICD, `openapi.yaml` |
| User story | `US-<nn>` | `US-09` | Product owner | DLE-USR |
| Epic | `E<n>` (stories) | `E3` | Product owner | DLE-USR |
| Persona (user) | `P<n>` | `P3` | Product owner | DLE-USR |
| User journey | `J<n>` | `J2` | Product owner | DLE-UXJ |
| Architecture decision | `ADR-<nnn>` | `ADR-009` | Architect | `docs/adr/` |
| Component | `E<n>` edge, `H<n>` host, `M<n>` model, `O<n>` offline, `C<n>` client | `H16` | Architect | Blueprint component map |
| Bound function | `DVSS-K<nn>` kernel (01–12), `DVSS-P<nn>` policy (01–14) | `DVSS-K05` | White paper | `config/functions.yaml` |
| Axis 1 pillar | `PL<nnn>`, never reused; aliases keep their ID | `PL051` | Registry owner | `config/registry/axis1_pillars.csv` |
| Axis 2 sector | `SC<nn>` (01–20, NAICS order) | `SC08` | Registry owner | `config/registry/axis2_sectors.csv` |
| Axis 3 link | `[LINK:3.<n>]` ordinal, never reused | `[LINK:3.17]` | Registry owner | `config/registry/axis3_links.jsonl` |
| Axis 4 branch | `[BR:4.1.<pillar>.<i>…]` or `[BR:4.2.<sector>.<naics>…]`, depth ≤ 7 | `[BR:4.2.8.493]` | Registry owner | `config/registry/axis4_branches.jsonl` |
| Axis 5 node | `[NODE:5.<n>]`; session nodes `[TMP:5.TMP.<uuid>]` | `[NODE:5.42]` | Registry owner / runtime | `config/registry/axis5_nodes.jsonl` |
| Axis 6 hub / arm | `[HUB:6.<n>]`, arm `[HUB:6.<n>]#<kebab-id>` | `[HUB:6.7]#purchase-clause` | Registry owner | `config/registry/axis6_hubs.jsonl` |
| Axis 7 mesh | `[MESH:7.<n>]` | `[MESH:7.9]` | Registry owner | `config/registry/axis7_meshes.jsonl` |
| Role profile (Axes 8–11) | `[ROLE:<axis>.<n>]`, assigned when the winning profile is persisted | `[ROLE:10.3]` | Runtime / profile store | profile store; fixtures `tests/fixtures/registry/personas.jsonl` |
| Axis 12 jurisdiction | `[JUR:12.<n>]`; place as ISO 3166 (`US`, `US-CA`) | `[JUR:12.1]` | Registry owner | `config/registry/axis12_jurisdictions.jsonl` |
| Axis 13 interval version | `[TIME:13.<n>]` for stored versions; coordinate atoms carry dates only | `[TIME:13.2]` | Registry owner | `config/registry/axis13_intervals.jsonl` |
| Legacy KA number | `KA-<nnn>` | `KA-015` | Enterprise registry | `config/catalog/`; **reference only, never a dispatch key** |
| Workflow step | `s<nn>` in code, "Step n" in prose | `s04_retrieve`, Step 4 | White paper §12 | `dle/host/workflow/steps/` |
| FROST layer | `l<nn>` in code, "L<n>" in prose | `l07_scope`, L7 | White paper §11 | `dle/host/frost/` |
| Persona role | Axis number and name | Axis 10 Regulator | White paper §08 | `dle/host/quad/roles.py` |
| Tier | `1`, `2`, `3` | Tier 2 | White paper §07 | `config/tiers.yaml` |
| Release profile | `snake_case` | `kernel_plus_policy` | AI risk owner | `config/profiles/` |
| Test case | `T-<LEVEL>-<AREA>-<nn>` | `T-ENG-FN-07` | Test lead | test docstring + RTM |
| Gemini compat case | `GC-<nn>` | `GC-14` | Test lead | compat test plan |
| Ticket | `P<phase>-<nn>` | `P1-08` | Tech lead | `docs/backlog/` |
| Gap item | `G<nn>` | `G7` | Tech lead | Gap analysis |
| Open decision | `D<n>` | `D3` | Tech lead | Gap analysis |
| Inconsistency | `C<n>` | `C4` | Tech lead | Gap analysis |
| Risk | `R-<nn>` | `R-04` | Risk owner | Risk register |
| Defect | `BUG-<nnnn>` | `BUG-0042` | Issue tracker | GitHub issues |
| Incident | `INC-<yyyy>-<nnn>` | `INC-2027-003` | Operations | Incident log |
| Formula / algorithm | `F-<NAME>-<nn>` / `A-<NAME>-<nn>` | `F-SCORE-01` | Architect | Function specs |
| Notice template | `NOTICE-<CLASS>-<nn>` | `NOTICE-HOLD-03` | UI lead | `config/notices.yaml` |
| Error code | `DLE-E<nnnn>` | `DLE-E1203` | Module owner | `dle/errors.py` |
| Runtime IDs | UUIDv4 lowercase (`run_id`, `receipt_id`); SHA-256 lowercase hex (`session_id`, digests) | `4f0c…` | System | Receipts |

**Requirement area codes:** API, SES (sessions), TOOL, WF (workflow), FL (FROST layers), QP (Quad Persona), TIER, FN (functions), VER, REL, RCPT, UI. **NFR attribute codes:** PERF, REL, SEC, PRIV, MAINT, PORT, OBS, COST, ACC. **Test levels:** UNIT, CONTRACT, ENG (engine), COMPAT, FIX (fixture), SEC, PERF, EVAL, UI. New codes are added here first.

**Number width.** Zero-pad to the width shown (`nn` = 2 digits, `nnn` = 3, `nnnn` = 4). If a series outgrows its width, widen new IDs only; never renumber.

## 2. Versions and dates

| Thing | Rule | Example |
| --- | --- | --- |
| Software, documents, schemas, functions | Semantic Versioning 2.0 `MAJOR.MINOR.PATCH` | `1.4.0` |
| API contract | `dle-api <MAJOR>.<MINOR>`, reported in `X-DLE-API-Version` | `1.0` |
| Receipt schema | SemVer; bumps on schema change (independent of white paper prose editions) | `3.8.0` |
| Git release tags | `v<semver>` | `v0.3.0` |
| Dates | ISO 8601 `YYYY-MM-DD` | `2026-11-20` |
| Timestamps | ISO 8601 UTC with `Z` | `2026-11-20T21:45:00Z` |
| Validity intervals | Half-open `[start, end)`; open end is `null` | |
| Units | SI or stated in the name: `_ms`, `_bytes`, `_tokens`, `_usd` | `duration_ms` |

## 3. Files and folders

| Kind | Convention | Example |
| --- | --- | --- |
| Folders | `snake_case`, short nouns | `dle/host/functions/` |
| Python modules | `snake_case.py`; ordered modules carry a 2-digit prefix | `s04_retrieve.py`, `l07_scope.py`, `k05_evidence.py`, `p12_drift.py` |
| Python tests | `test_<module>.py`, mirroring the source path | `tests/unit/host/functions/test_registry.py` |
| TypeScript components | `PascalCase.tsx` with sibling `PascalCase.stories.tsx` and `PascalCase.test.tsx` | `ReleaseBadge.tsx` |
| TypeScript other | `camelCase.ts` | `releaseMode.ts` |
| JSON schemas | `<thing>.schema.json`; function I/O `k05.in.json`, `k05.out.json` | `receipt.schema.json` |
| Config | `snake_case.yaml` | `model_pins.yaml` |
| SQL migrations | `<nnnn>_<snake_description>.sql`, never edited after merge | `0002_add_function_records.sql` |
| ADRs | `docs/adr/<nnn>-<kebab-title>.md` | `009-dispatch-by-dvss-id.md` |
| Markdown docs | `snake_case.md`; root files in UPPER case | `function_specs.md`, `AGENTS.md` |
| Fixtures | `<case>_<variant>.json` | `warehouse_pass1.json` |
| Reports | `<subject>_<yyyy-mm-dd>.md` | `phase1_gate_2027-01-15.md` |

## 4. Code identifiers

| Language | Item | Convention | Example |
| --- | --- | --- | --- |
| Python | Classes, Pydantic models, exceptions | `PascalCase`; exceptions end in `Error` except domain verbs | `RunRequest`, `EgressDenied` |
| Python | Functions, methods, variables | `snake_case`, verbs for functions | `resolve_session()` |
| Python | Constants | `UPPER_SNAKE` | `MAX_RETRIES = 2` |
| Python | Private | leading `_` | `_hash_history()` |
| Python | Kernel/policy function classes | `K05EvidenceAcquisition`, `P12DriftMonitoring` | |
| TypeScript | Components, types | `PascalCase` | `MessageBubble`, `RunSummary` |
| TypeScript | Functions, variables | `camelCase` | `formatReceiptId()` |
| CSS tokens | `--dle-<role>` | `--dle-released` | |
| Env vars | `DLE_<UPPER_SNAKE>` | `DLE_BIND_ADDRESS` | |
| Config keys | `snake_case` | `session_expiry_hours` | |

## 5. Data, API and telemetry names

| Surface | Convention | Example |
| --- | --- | --- |
| Gemini-compatible JSON | `camelCase`, exactly as Google defines | `groundingMetadata`, `finishReason` |
| DLE-owned JSON (receipts, function I/O, role artifacts) | `snake_case` | `function_invocations`, `response_sha256` |
| DLE body extension | `dleMetadata` object, `camelCase` inside (it sits in a Gemini body) | `dleMetadata.releaseMode` |
| HTTP headers | `X-DLE-<Kebab-Case>` | `X-DLE-Release-Mode` |
| URL paths | Gemini paths verbatim; DLE paths lowercase plural nouns under `/v1/` | `/v1/receipts/{receiptId}` |
| Enum values | `snake_case` | `released_advisory`, `host_fallback` |
| SQL tables | `snake_case` plural | `function_records` |
| SQL columns | `snake_case`; timestamps `*_utc`, booleans `is_*`/`has_*`, foreign keys `<table_singular>_id` | `created_utc`, `run_id` |
| Metrics | `dle_<area>_<measure>_<unit>` | `dle_run_duration_ms`, `dle_holds_total` |
| Log events | `<area>.<event>` lowercase | `egress.denied`, `function.invoked` |
| Storybook titles | `DLE/<Area>/<Component>`; story names are states | `DLE/Chat/MessageBubble` → `Held` |

## 6. Git

| Item | Convention | Example |
| --- | --- | --- |
| Branches | `<type>/<ticket>-<kebab-slug>` | `feat/P1-08-session-resolver` |
| Commits | Conventional Commits; IDs in body | `feat(edge): session resolver` + `Implements: FR-SES-01` |
| PR titles | Same as the squash commit | |
| Labels | `phase-<n>`, `fixture-change`, `security`, `breaking` | |

## 7. Documents

- Each document starts with an ID, version, status (`Draft`, `Accepted`, `Retired`), owner and date.
- Sections are numbered `1`, `1.1`, `1.1.1`; tables and figures are numbered per document (`Table 3`, `Figure 2`).
- Refer to other documents by ID and section: "DLE-SDD §6".
- Cite the white paper as "paper §16a".
- Requirement statements use "shall"; guidance uses "should"; permission uses "may".
- Terms come from the glossary (documentation set §16). Use DVSS IDs for functions in all new text; mention the legacy KA number only in traceability columns.
