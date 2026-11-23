# Master document index

**Document ID:** DLE-IDX-001 · **Version:** 1.0.0 · **Status:** Accepted · **Owner:** Tech lead · **Date:** 2026-11-20

Every document, specification, contract and plan for the DataLogicEngine 13-axis middleware, in one list. IDs follow DLE-STD-001. Paths are relative to the repository root. "Live" means the editable Claude doc is the master copy and the repository holds an exported snapshot in `docs/dle-dev-docs/`. The `.pdf` and `.docx` files under `docs/dle-dev-docs/` are archival v3.8 exports, while the `.md` files and this index are synced to v3.13.

## 1. Design and governing documents

| ID | Title | Where | Version | Status | Owner |
| --- | --- | --- | --- | --- | --- |
| DLE-WP-313 | DataLogicEngine white paper v3.13 (13-axis DVSS reference design) | `docs/whitepaper/DataLogicEngine_White_Paper_v3_13.pdf`; `docs/whitepaper/editable_source/DataLogicEngine_White_Paper_v3_13.md` | 3.13 | Accepted | Architect |
| DLE-BPR | Application Blueprint | [Live](https://claude.ai/artifact/6Q6zGoHyFYZTnJH8udgejn); `docs/dle-dev-docs/DLE_Application_Blueprint.*` | 0.3 | Draft | Architect |
| DLE-DEV | Software Development Documentation Set (contains the documents in §2) | [Live](https://claude.ai/artifact/YT8VtNLVjq3qxXBndnetLY); `docs/dle-dev-docs/DLE_Software_Development_Documentation_Set.*` | 0.1 | Draft | Tech lead |
| DLE-GAP | Documentation and Planning Gap Analysis | [Live](https://claude.ai/artifact/E7MkUQ4jPocdoahDNHR1HF); `docs/dle-dev-docs/DLE_Documentation_and_Planning_Gap_Analysis.pdf` | 0.2 | Draft | Tech lead |
| DLE-IDX-001 | Master document index (this file) | `docs/INDEX.md` | 1.0.0 | Accepted | Tech lead |
| DLE-STD-001 | Naming and numbering conventions | `docs/standards/naming_and_numbering_conventions.md` | 1.0.0 | Accepted | Tech lead |

## 2. Inside the Software Development Documentation Set (DLE-DEV)

| ID | Title | Section | Standard basis |
| --- | --- | --- | --- |
| DLE-SDP | Software Development Plan | §2 | ISO/IEC/IEEE 12207 |
| DLE-SRS | Software Requirements Specification | §3 | ISO/IEC/IEEE 29148 |
| DLE-SAD | Software Architecture Description | §4 | ISO/IEC/IEEE 42010 |
| DLE-ICD | Interface Control Document | §5 | ISO/IEC/IEEE 15289 |
| DLE-SDD | Software Design Description, incl. H16 function registry and binding tables | §6 | IEEE 1016 |
| DLE-STP | Test and V&V Plan | §7 | ISO/IEC/IEEE 29119-3, IEEE 1012 |
| DLE-SEC | Secure Development and Threat Model | §8 | NIST SSDF, OWASP ASVS, OWASP LLM Top 10 |
| DLE-AIM | AI Management and Risk | §9 | ISO/IEC 42001, 23894, NIST AI RMF |
| DLE-CMR | Configuration, Release and Operations | §10 | IEEE 828, SLSA, CycloneDX |
| DLE-RTM | Requirements Traceability Matrix | §11 (and `docs/traceability/rtm.csv`) | ISO/IEC/IEEE 29148 |
| DLE-USR | User Personas and Stories | §12 | — |
| DLE-UXJ | User Journeys | §13 | — |
| DLE-STY | Style Guide (UI and code) | §14 | WCAG 2.2 AA |
| DLE-SB | Storybook Component Catalog | §15 | — |
| — | Glossary | §16 | — |

## 3. Repository: rules and process

| ID | Title | Path | Gap |
| --- | --- | --- | --- |
| — | Repository overview | `README.md` | — |
| DLE-AGT | Rules for coding agents | `AGENTS.md` | G2 |
| DLE-HND | Handoff log | `HANDOFF.md` | G2 |
| DLE-CON | Contributing guide | `CONTRIBUTING.md` | — |
| DLE-CHG | Changelog | `CHANGELOG.md` | — |
| DLE-SECP | Security and disclosure policy | `SECURITY.md` | G26 |
| — | PR template, code owners, Dependabot | `.github/` | — |
| — | CI pipeline (tests, SAST, SCA, secrets, SBOM) | `.github/workflows/ci.yml` | — |
| — | Custom static-analysis rules | `.semgrep/dle.yml` | — |
| — | Build, lint, type and test configuration | `pyproject.toml`, `.pre-commit-config.yaml`, `.editorconfig` | — |

## 4. Architecture decisions

| ID | Decision | Path | Status |
| --- | --- | --- | --- |
| ADR-000 | Template (MADR) | `docs/adr/000-template.md` | — |
| ADR-001 | Gemini-compatible API | `docs/adr/001-gemini-compatible-api.md` | Accepted |
| ADR-002 | Pass tool calls through unblocked | `docs/adr/002-pass-through-tool-calls.md` | Accepted |
| ADR-003 | Sessions by history hash | `docs/adr/003-session-by-history-hash.md` | Accepted |
| ADR-004 | Stream only after the gate | `docs/adr/004-stream-after-gate.md` | Accepted |
| ADR-005 | SQLite for all stores | `docs/adr/005-sqlite-stores.md` | Accepted |
| ADR-006 | Local ONNX NLI | `docs/adr/006-local-nli.md` | Accepted |
| ADR-007 | Holds return STOP | `docs/adr/007-hold-returns-stop.md` | Accepted |
| ADR-008 | Model split by job | `docs/adr/008-model-split.md` | Proposed |
| ADR-009 | Dispatch by DVSS ID | `docs/adr/009-dispatch-by-dvss-id.md` | Accepted |
| ADR-010 | Kernel vs policy levels | `docs/adr/010-kernel-and-policy-levels.md` | Accepted |
| ADR-011 | Docker delivery for browser runtime and Google Gemini cloud models | `docs/adr/011-docker-browser-and-gemini-cloud.md` | Accepted |

## 5. Contracts (machine-readable)

| ID | Title | Path | Version |
| --- | --- | --- | --- |
| IR-01–07 | OpenAPI for the Gemini façade and DLE endpoints | `contracts/openapi.yaml` | 1.0.0 |
| — | Receipt schema | `contracts/receipt.schema.json` | 3.8.0 |
| — | Coordinate schema | `contracts/coordinate.schema.json` | 3.7.1 (migrate in P1-20) |
| — | Role artifact schema | `contracts/role_artifact.schema.json` | 1.0.0 |
| — | Claim extraction output schema | `contracts/prompts/claim_extraction.schema.json` | 1.0.0 |
| FR-FN-01 | Bound function catalog schema | `contracts/functions.schema.json` | 1.0.0 |
| — | Function I/O schemas (written per phase) | `contracts/functions/` | — |

## 6. Specifications

| ID | Title | Path | Gap |
| --- | --- | --- | --- |
| DLE-FNS-001 | Function specification catalog (DVSS-K01–K12, P01–P14) | `docs/specs/function_specs.md` | G6 |
| DLE-PRM-001 | Claim extractor prompt and contract | `docs/specs/prompts/claim_extractor.md` | G7 |
| DLE-PRM-002 | Persona and writer prompt contracts | `docs/specs/prompts/personas_and_writer.md` | G11 |
| DLE-SPC-002 | Intake scoring method (S, R, B, Z) | `docs/specs/intake_scoring.md` | G12 |
| DLE-SPC-003 | Axes 3–7: records, generation and traversal | `docs/specs/axes_3_to_7.md` | G13 |
| DLE-SPC-004 | Axes 8–12: role profiles and jurisdiction | `docs/specs/axes_8_to_12.md` | G13, G14 |
| DLE-SPC-005 | Axis 13: valid time | `docs/specs/axis_13_valid_time.md` | G13 |
| — | Database schema (five SQLite stores) | `dle/store/migrations/0001_init.sql` | G8 |
| — | Notice catalog | `config/notices.yaml` | G10 |

## 7. Configuration

| Title | Path |
| --- | --- |
| Function bindings (26) | `config/functions.yaml` |
| Tier table | `config/tiers.yaml` |
| Release profiles: strict, advisory, kernel_only, kernel_plus_policy | `config/profiles/` |
| Model pins and dated prices | `config/model_pins.yaml` |
| Egress allowlist | `config/egress.yaml` |
| Receipt settings | `config/receipts.yaml` |
| Consequential function flags | `config/function_flags.yaml` |
| KA catalog (inventory only) | `config/catalog/ka100.csv`, `config/catalog/enterprise_ka114.json` |

## 8. Plans, tests and evaluation

| ID | Title | Path | Gap |
| --- | --- | --- | --- |
| DLE-BKL-P1 | Phase 1 backlog (20 tickets) | `docs/backlog/phase1_backlog.md` | G3 |
| DLE-TST-GC | Gemini compatibility test plan | `docs/test/gemini_compat_test_plan.md` | G4 |
| DLE-PLN-001 | Pilot migration plan | `docs/plans/pilot_migration.md` | G16 |
| DLE-PLN-002 | Multi-phase build plan | `docs/plans/multi_phase_build_plan.md` | — |
| DLE-EVL-001 | Evaluation data plan and budget | `docs/eval/evaluation_data_plan.md` | G17, G20 |
| DLE-EVL-002 | Grading rubric and grader guide | `docs/eval/grading_rubric.md` | G18 |
| DLE-EVL-003 | Pre-registered study protocol | `docs/eval/study_protocol.md` | G19 |
| DLE-RTM | Traceability matrix (CSV) | `docs/traceability/rtm.csv` | — |
| — | Coordinate fixtures (warehouse and storage procurement cases) | `tests/fixtures/coordinate_warehouse.json`, `tests/fixtures/coordinate_storage_procurement.json` | — |

## 9. Product, operations, security and legal

| ID | Title | Path | Gap |
| --- | --- | --- | --- |
| DLE-VND-001 | Gemini 4 Carbon verification note | `docs/vendor/gemini_4_carbon_verification.md` | G5 |
| DLE-GDE-001 | Developer quick start | `docs/guides/developer_quickstart.md` | G21 |
| DLE-GDE-002 | Administrator and hardening guide | `docs/guides/admin_and_hardening_guide.md` | G22 |
| DLE-SCT | System card template | `docs/templates/system_card_template.md` | G23 |
| DLE-SEC-002 | Product security package | `docs/security/product_security_package.md` | G24 |
| DLE-OPS-001 | Runbook and AI incident response | `docs/ops/runbook_and_incident_response.md` | G25 |
| DLE-LGL-001 | Third-party license inventory | `docs/legal/third_party_licenses.md` | G26 |

## 10. Related project documents (outside this repository)

| Title | Note |
| --- | --- |
| Standards and Compliance Blueprint (2026-08-17) | Written for the 17-axis desktop product; middleware parts superseded by DLE-SEC-002 |
| DVSS pilot (21 tests) | Migrates into this repository under P1-20 |

## 10a. Registries

| ID | Title | Path | Status |
| --- | --- | --- | --- |
| DLE-REG-001 | Axis 1 pillar register (PL001–PL118; 114 active pillars, 4 aliases) | config/registry/axis1_pillars.csv (+ .xlsx) | Approved 2026-11-20; all ISCED-F codes verified (PL109: 0413; 0417, PL114: 0314) |
| DLE-REG-002 | Axis 2 sector register (SC01–SC20, NAICS 2022) and reviewed crosswalk (336 rows) | config/registry/axis2_sectors.csv, axis2_crosswalk.csv (+ .xlsx) | Approved 2026-11-20 |
| DLE-REG-003 | Axes 3–7 registries (links, branches, nodes, hubs, meshes) and schemas | config/registry/axis{3..7}_*.jsonl, contracts/registry/*.schema.json | Format approved 2026-11-20; production files empty until D4; warehouse fixtures in tests/fixtures/registry/ |
| DLE-REG-004 | Role profile and Axis 12 jurisdiction formats, role conduct, reference-list manifest | contracts/registry/persona_profile.schema.json, axis12_jurisdiction.schema.json, config/personas/conduct.yaml, config/reference/manifest.yaml | Approved 2026-11-20; reference files fetched at build |
| DLE-REG-005 | Axis 13 interval record format and interval library | contracts/registry/axis13_interval.schema.json, dle/temporal/, config/registry/axis13_intervals.jsonl | Approved 2026-11-20 |

## 11. Not yet written

| Gap | Item | Waiting on |
| --- | --- | --- |
| G13 | Registry seed content for Axes 3–7, 12 and 13 (all 13 axis formats done: DLE-REG-001..005, DLE-SPC-003..005) | Decision D4 (pilot domain) |
| G14 | Persona profile store content | D4 |
| G15 | Pilot domain and source corpus plan | D4 |
| G23 | Filled system card | Study results (phase 7) |
| — | P01–P14 full one-page specs | Written in the phase that builds each function |
| — | Function I/O schema pairs | Same |
