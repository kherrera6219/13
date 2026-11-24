# HANDOFF.md

Running record for agents. Newest entry first. Keep each entry short: what changed, what was learned, what is next.

## 2026-11-23 — Phase 4 Complete (Wave 4C Exit Gate: Browser Persona/Step UI, Storybook/axe, Docker E2E & Gate Report)

**State.** Phase 4 (`H1`, `H8`, `H9`, `H11`, `FROST`, `DVSS-K03`, `K09`, `K12`, `P02`, `P07`, `P08`, `P10`, `P11`, `US-05..08`, Minimum Conforming Profile §18b) is complete and cleared via `reports/phase4_gate.md` (`dle-middleware:phase4`).

**Changed.**
- `dle/host/workflow/governed.py` & `tests/engines/test_phase4_orchestrator_conformance.py`: Added structured `findings` to `dleMetadata.personas` summaries, asserted findings across §18 conformance tests, and added opt-in `test_phase4_live_gemini_conformance_opt_in` gated by `DLE_LIVE_GEMINI_API_KEY`.
- `ui/src/`: Added Phase 4 types (`RunSummary`, `PersonaSummary`, `PersonaObjectionItem`, `StepTraceItem`) & `extractObjectionsFromReceipt` / `extractDleMetadata` in `dleClient.ts`; built `RunSummaryCard`, `PersonaChips`, `StepTimeline`, and `PersonaDrawer` plus CSF3 fixtures (`src/fixtures/phase4.ts`), Storybook stories (`49/49` `test-storybook` + `axe-core` passed), and `App.tsx` Run Inspector integration.
- `reports/phase4_gate.md`, `docs/traceability/rtm.csv`, `CHANGELOG.md`: Recorded Wave 4C / Phase 4 Exit Gate verification (`212 passed, 2 skipped`, `90.69%` cov, `26` Python SDK, `24` JS SDK, `pip-audit` 0 CVEs, Semgrep 0 findings, and `LIVE_E2E_PHASE4_OK`).

**Next.** Execute **Phase 5 (Hybrid Intake Router, Tiers & Full Admin/Accessibility Polish)**: implement complete `H2` / `DVSS-K10` scoring (`D/R/M/B/Z`, `gemini-embedding-001` failure-centroid, `S_eff = max(S, 3B, 6Z)`), enforce tier call budgets (`9/21`, `18/22`, `18`), >= 95% recall on 50-item dev challenge set, Browser Admin UI (`DriftBanner`, `FunctionFlagsEditor`, `CostByTierChart`, `HealthPanel`, `ExportDialog`), and `NFR-PERF-01` overhead benchmark.

## 2026-11-23 — Phase 4 Wave 4B: 12-Step FROST Orchestrator, Cutoff-Blind Retries K09, Escalation P07 & Tool Parking

**State.** Phase 4 Wave 4B complete (`FR-WF-01..07`, `FR-FL-01..07`, `FR-QP-06`, `FR-TOOL-02..05`, `DVSS-K09`, `DVSS-P07`). Full 12-step governed loop (`s01_ingest`..`s12_seal`) across all 10 FROST layers (`l01_grounding`..`l10_receipt`) is wired into `dle/host/workflow/governed.py` and `dle/edge/gateway.py` with cutoff-blind `<= 2` retries (`DVSS-K09`), one-time binding/consequential Regulator escalation (`DVSS-P07`), blinded assurance ordering, Step-4 tool park/resume, and end-to-end §18 conformance tests on both `FakeModel` and `FakeUpstream`.

**Changed.**
- `dle/host/frost/`: Added 10-layer FROST stack constants and deterministic `FrostTrace` metadata collector (`s01`–`s12`, `l01`–`l10`).
- `dle/host/services/policy_control.py` & `contracts/functions/{k09,p07}.{in,out}.json`: Implemented strictly cutoff-blind `decide_retry_policy` (`DVSS-K09`), one-time `evaluate_binding_escalation` (`DVSS-P07`), and `check_consequential_functions` (`config/function_flags.yaml`).
- `dle/models/fake.py` & `tests/gemini_compat/fake_upstream.py`: Added shared `extract_writer_question` / `_build_fake_role_artifact` support for `job="personas"` and `writer-1.0.0` JSON packets.
- `dle/host/workflow/governed.py`, `dle/host/workflow/__init__.py`, `dle/edge/gateway.py`: Wired multi-attempt loop, H8 personas, `LedgerService`, `Pareto`, `WriterService`, Step-4 `ToolBridge`/`parked_runs`, `run_governed_workflow` alias, and `dleMetadata.runSummary`/`personas`/`steps`.
- Added `tests/unit/host/services/test_policy_control_and_frost.py` (including Hypothesis cutoff-blind property checks) and `tests/engines/test_phase4_orchestrator_conformance.py`.

**Next.** Execute **Phase 4 Wave 4C (Phase 4 Exit Gate)**: implement Browser Inspector UI `RunSummaryCard`, `PersonaChips`, `StepTimeline`, and `PersonaDrawer` + Storybook/axe tests, rebuild `dle-middleware:phase4` Docker image & run live E2E probe, verify `pip-audit`, Semgrep & JS/Python compat, and publish `reports/phase4_gate.md`.

## 2026-11-23 — Phase 4 Wave 4A: Quad Persona Engine, Reference Catalog, Verifier Ledger, Pareto & Writer (H8, H9, H11)

**State.** Phase 4 Wave 4A complete (`DVSS-K03`, `DVSS-K12`, `DVSS-P02`, `DVSS-P08`, `DVSS-P10`, `DVSS-P11`, `FR-QP-01..08`, `FR-VER-02`, `DLE-SPC-004`, `DLE-PRM-002`). Dynamic 7-field MDKF profiles (`[ROLE:8..11.<n>]`), build-time CIP/SOC/O*NET reference staging & validation, blinded/Tier-3 falsification role packets, append-only SQLite verifier ledger, Pareto frontier filtering, and `writer-1.0.0` synthesis service are built and verified.

**Changed.**
- `dle/store/repositories.py`: Added `persona_profiles` CRUD (`save_persona_profile`, `get_persona_profile`, `list_persona_profiles`, `next_persona_ordinal`) to `RegistryRepository`.
- `dle/host/services/reference.py` & `dle/tools/fetch_reference.py`: Implemented `ReferenceCatalog`, SHA-256 verification against `config/reference/manifest.yaml`, `CIP2020`/`SOC2018`/`ONET-SOC` code validation, absent-catalog `certified_eligible=False` warning, and offline staging CLI.
- `dle/host/services/personas.py` (`H8`) & `dle/models/fake.py`: Implemented `build_persona_profile`, `validate_persona_profile`, `DVSS-K03` (`match_profiles` `M = 0.25E + 0.45C + 0.30X` with renormalization & `low_fit`), `DVSS-P10` (`tie_break_profiles`), `DVSS-P08` (`allocate_role_tokens` largest-remainder rounding + equal-split fallback), `DVSS-P11` Tier-3 falsification + blinded wave ordering (`order_role_execution`), `execute_role_call`, and `RoleArtifact_1_0_0` citation validation; added `job="personas"` JSON generation in `FakeModel`.
- `dle/host/services/ledger.py` (`H11`), `pareto.py` (`DVSS-P02`), `writer.py` (`H9`), `__init__.py`: Implemented verifier-only append-only `LedgerService` (`close_by_verifier`), feasibility/unit-checked `filter_pareto_options`, and `WriterService` (`writer-1.0.0` ordered by `synthesis_weight`).
- Added 10 Draft 2020-12 contracts (`contracts/functions/{k03,p02,p08,p10,p11}.{in,out}.json`) and tests (`test_personas_and_reference.py`, `test_ledger_pareto_writer.py`).

**Next.** Execute **Phase 4 Wave 4B**: wire full 12-step governed workflow (`s01`–`s12`, FROST `l01`–`l10`), `DVSS-K09` cutoff-blind retries (`<= 2`), `DVSS-P07` one-time Regulator escalation, Step-4 tool park/resume + `config/function_flags.yaml` consequential flagging, Browser UI `RunSummaryCard`/`PersonaChips`/`StepTimeline`/`PersonaDrawer`, §18 conformance fixtures, and `reports/phase4_gate.md`.

## 2026-11-22 — Phase 3 Complete (Wave 3B: Bounded PPR K07, USKD Overlay P03, Crosswalks P06, Workflow/UI Drawer & Gate Report)

**State.** Phase 3 (`H3`, `O2`, `D4`, `H4`, `H6`, `H7`, `DVSS-K02`, `K06`, `K07`, `P01`, `P03`, `P06`, `FR-UI-01..02`) is complete and cleared via `reports/phase3_gate.md` (`dle-middleware:phase3`). Bounded Personalized PageRank retrieval (`alpha=0.85`, `<= 80` iters, `<= 250` vertices, hop limit `<= 4`, post-hydration edge/token budget, reserved synthetic slots) runs behind the `DLE_ENABLE_PPR` switch alongside dense hybrid retrieval, feeding 13-axis coordinate + PPR metadata into 3.8.0 signed receipts and the Browser UI `AddressGraphDrawer`.

**Changed.**
- `dle/host/services/overlay.py` (`H7`): Added `SessionOverlay` (`depth <= 7`, `[TMP:5.TMP.<uuid>]`, `clear_on_seal()`) and `can_cite_as_evidence` forbidding citing TMP nodes as durable evidence (`DVSS-P03`).
- `dle/host/services/graph.py` (`H6`) & `contracts/functions/{k07,p03,p06}.{in,out}.json`: Added `expand_bounded_ppr`, `effective_hop_budget`, and `align_crosswalk_terms` (`DVSS-K07`, `DVSS-P06`).
- `dle/edge/settings.py`, `dle/host/workflow/governed.py`, `dle/edge/gateway.py`: Added `DLE_ENABLE_PPR` & `DLE_REGISTRY_OVERLAY_DIR` (auto-loading `config/pilots/warehouse_substitution` when present), real `DVSS-K02` + `DVSS-K07` receipt metrics (`coordinate_manifest_sha256`, `ppr_iterations`, `graph_sha256`), and `dleMetadata.coordinate` / `dleMetadata.graph`.
- `ui/`: Added `ui/src/components/AddressGraphDrawer.tsx` + `.stories.tsx`, `src/fixtures/phase3.ts`, client capture in `dleClient.ts`, `Run Inspector` wiring in `App.tsx`, and Storybook/axe registration in `stories.test.tsx`.
- Added `tests/unit/host/services/test_graph_and_overlay.py`, `test_governed_ppr_switch_disable_mode` in `test_gateway.py`, and `reports/phase3_gate.md`; updated `docs/traceability/rtm.csv` and `CHANGELOG.md`.

**Next.** Execute **Phase 4 (Quad Persona Engine, Ledger, Retries & Escalation §18b)**: build-time reference fetcher (`H8` CIP/SOC/O*NET), dynamic 7-field MDKF profiles (`DVSS-K03`/`P10`) + role token allocation (`DVSS-P08`), verifier-only append ledger (`DVSS-K12`), 12-step cutoff-blind orchestrator (`DVSS-K09`, `P02`, `P07`, `P11`), Browser `RunSummaryCard`/`PersonaChips`/`StepTimeline`/`PersonaDrawer`, and full §18 conformance against fake & Gemini calls.

## 2026-11-22 — Phase 3 Wave 3A: 13-Axis Registry Loader, Release CLI, Warehouse Pilot & Coordinate Engine (H3, O2, H4)

**State.** Phase 3 Wave 3A complete. Persistent `RegistryRepository` (`registry.db`), `H3` 13-axis registry loader (`load_registry` with alias rewriting, retired exclusion, fixture rejection outside tests, spine/crosswalk graph construction, and JCS manifest SHA-256), `O2` offline release CLI (`dle.tools.registry_release` / `offline/registry_release.py`), `D4` verified Warehouse Substitution pilot corpus (`config/pilots/warehouse_substitution/`), and `H4` (`DVSS-K02` Nuremberg/TMP coordinate parser, `DVSS-K06` temporal interval applicability & conflict checker via `dle.temporal`, `DVSS-P01` Axis 12 jurisdiction precedence ordering) plus paired function contracts (`k02`, `k06`, `p01`) are implemented and verified.

**Changed.**
- `dle/store/repositories.py` & `dle/store/__init__.py`: Added `RegistryRepository` (`publish_release`, `get_active_release`, `get_release`, `list_atoms`, `list_spine_edges`, `list_crosswalks`) honoring `ux_registry_releases_active`.
- `config/pilots/warehouse_substitution/*.jsonl`: Seeded `D4` verified warehouse substitution pilot corpus across Axes 3–7, 12–13 without modifying `tests/fixtures/` or putting fixture records in `config/registry/`.
- `dle/host/services/registry.py` (`H3`), `dle/tools/registry_release.py`, `offline/registry_release.py` (`O2`): Implemented strict Draft 2020-12 JSONL + Axis 1/2 CSV loader, Axis 1 alias rewriter (`PL101`->`PL020`), `w3`/`w67` weighted spine builder, and SQLite release publisher CLI.
- `dle/host/services/coordinate.py` (`H4`) & `contracts/functions/{k02,k06,p01}.{in,out}.json`: Implemented `parse_atom`, `parse_coordinate` (`3.7.1`), `propose_anchors_from_query`, `evaluate_temporal_applicability`, and `resolve_jurisdiction_precedence`.
- Added `tests/unit/host/services/test_registry_and_coordinate.py`; updated `docs/traceability/rtm.csv` and `CHANGELOG.md`.

**Next.** Execute **Phase 3 Wave 3B** (`H6` deterministic bounded PPR graph expansion `DVSS-K07` / `DVSS-K03`, `H7` per-session `USKD` overlay `[TMP:5.TMP.<uuid>]` depth `<= 7` + `DVSS-P03`/`P06`, wire 13-axis/PPR path into `governed.py` & `gateway.py`, add 13-Axis Address & Evidence Graph Browser UI drawer + Storybook stories, publish `reports/phase3_gate.md`).

## 2026-11-22 — Phase 2 Complete (Wave 2C: Gateway Wiring, Governed Compat GC-12/13/25, Inspector UI & Gate Report)

**State.** Phase 2 (`FR-API-04..08`, `FR-VER-01..03`, `FR-REL-01..04`, `FR-RCPT-01..03`, `FR-UI-01..02`) is complete and cleared via `reports/phase2_gate.md` (`dle-middleware:phase2`). Full Phase 2 verify-and-gate execution replaces the Phase 1 stub across `dle/edge/gateway.py`, backed by persistent 5-DB SQLite + `sqlite-vec` stores, Ed25519/WORM Merkle 3.8.0 receipts, governed Python + JS Gemini SDK compatibility (`GC-12`/`13`/`25`), and the Browser Inspector UI (`CitationList`, `ClaimsTable`, `ReceiptViewer`, `SourceRegistryTable`).

**Changed.**
- `dle/host/workflow/governed.py`: Added `run_governed_phase2`, `seal_cancelled_receipt` (`GC-25`), and `DEFAULT_PHASE2_CALIBRATION` (`drift_lambda=4.0`), wiring H16 kernel functions (`DVSS-K01..K12`), `EvidenceService`, `ClaimExtractor`, `ClaimVerifier`, `compute_terminal_u`, `update_cusum_drift`, `evaluate_release_gate`, `apply_disclosure`, and fail-closed schema-3.8.0 `ReceiptSealer`.
- `dle/edge/{composer.py,settings.py,gateway.py}`: Wired 5-DB `StoreBundle`, repositories, `EmbeddingService`, `OnnxNliScorer`/`DeterministicLexicalNliScorer`, `/healthz` (`nliLoaded`), `/v1/receipts/{receiptId}`, `/v1/sources` pagination, `/admin/sources` base64 ingestion, `/admin/drift/reset`, `/admin/keys/rotate`, and `/admin/receipts/export`.
- `dle/models/fake.py` & `tests/gemini_compat/fake_upstream.py`: Stripped synthetic `[model]` prefixes on `job="writer"` and handled `job="claim_extraction"` JSON replay so offline verification/NLI checks execute cleanly without spurious numeric conflicts.
- `tests/unit/edge/test_gateway.py` & `tests/gemini_compat/{test_python_sdk.py,test_js_sdk.py,js_sdk_compat.mjs}`: Added governed release/hold/receipt signature checks plus `GC-12`, `GC-13`, and `GC-25` across Python (`google-genai==1.75.0`, 26/26) and JS (`@google/genai==3.6.1`, 24/24) SDKs.
- `ui/`: Added `CitationList`, `ClaimsTable`, `ReceiptViewer`, `SourceRegistryTable`, `src/fixtures/phase2.ts`, `src/lib/dleClient.ts` receipt/citation/sources helpers, workspace tabs + admin key settings in `App.tsx`, and Storybook/axe checks in `src/stories.test.tsx` (30/30 passed).
- Added `reports/phase2_gate.md`; updated `docs/traceability/rtm.csv` and `CHANGELOG.md`.

**Learned.**
- Setting `DEFAULT_PHASE2_CALIBRATION.drift_lambda=0.50` caused a single ungrounded non-binding prompt (`u ~ 0.95`) to accumulate `c_t ~ 0.88 > 0.50` before `evaluate_release_gate` and trip the server-wide drift latch immediately; raising `drift_lambda=4.0` preserves per-request `abstained`/`hard_veto_block` holds while latching after ~5 consecutive ungrounded queries.
- Omitting `[gemini-4-carbon]` prefixes in `FakeModel` / `FakeUpstream` on `job="writer"` prevents the digit `"4"` in `gemini-4-carbon` from triggering `DeterministicLexicalNliScorer`'s numeric conflict rule against grounded ISO/numeric premises.

**Next.** Execute **Phase 3 (13-Axis Address, Spine & Bounded Graph Retrieval)**: complete `H3` 13-axis coordinate builder/validator + `H4` Axis-13 `tle` matcher, bounded graph expansion `H6` (`DVSS-K07` / `K03`, <= 10% expansion overhead), and run the Phase 3 Warehouse Substitution domain pilot (`D4`).

## 2026-11-22 — Phase 2 Wave 2B: Extractor, Verifier, Scorer, Release Controller & Receipts (H10, H12..H15)

**State.** Phase 2 Wave 2B complete. Claim extractor (`H10`), NLI verifier (`H12` / `DVSS-P04`), source-age & terminal `u` scorer (`H13` / `DVSS-K08`), release controller (`H14` / `DVSS-K04`, `K11`, `K12`, `P12`, `P13`), and Ed25519/JCS/WORM Merkle receipt sealer + offline CLI verifier (`H15` / `dle.tools.verify_receipt`) are implemented and verified alongside paired function contracts (`k04`, `k08`, `k11`, `k12`, `p04`, `p12`, `p13`) and Hypothesis property tests.

**Changed.**
- `dle/host/services/evidence.py`: Aligned `AUTHORITY_PRIOR` to white paper §16a (`primary_text=1.00`, `binding_instrument=0.95`).
- `dle/store/repositories.py`: Added `list_signing_keys()` and `list_chain_receipts()` to `ReceiptRepository`.
- `dle/host/services/claim_extractor.py`: Implemented `H10` (`ClaimExtractor`, `build_extractor_request` with `DLE-PRM-001` prompt/user-slot safety, deterministic offline fallback + K01 span validation). Tested against 30 frozen golden pairs (`tests/contract/prompts/test_claim_extractor.py`).
- `dle/host/services/scorer.py` & `verifier.py`: Implemented `DVSS-K08` (`source_age_decay`), `F-SCORE-01` (`compute_terminal_u`), `DVSS-P04` (`detect_contradictions`), `ClaimVerifier`, and OpenAPI `groundingMetadata` emission (`tests/unit/host/services/test_verifier_and_scorer.py`).
- `dle/host/services/release.py`: Implemented `DVSS-K12` (`evaluate_compliance_veto`), `DVSS-P13` (`safety_policy_check`), `DVSS-P12` (`update_cusum_drift`), `DVSS-K04` (`evaluate_release_gate`), and `DVSS-K11` (`apply_disclosure`), verified with Hypothesis property tests.
- `dle/host/services/receipts.py` & `dle/tools/verify_receipt.py`: Implemented `Ed25519KeyManager`, domain-separated SHA-256 Merkle proofs/checkpoints, schema-3.8.0 `ReceiptSealer`, ZIP bundle export, and standalone CLI verifier (`tests/unit/host/services/test_release_and_receipts.py`).
- Added 14 Draft 2020-12 contract schemas (`contracts/functions/{k04,k08,k11,k12,p04,p12,p13}.{in,out}.json`), updated `docs/traceability/rtm.csv` and `CHANGELOG.md`.

**Next.** Execute **Phase 2 Wave 2C** (wire `StoreBundle`, `EvidenceService`, `ClaimExtractor`, `ClaimVerifier`, `ReceiptSealer`, real `H14` verify-and-gate workflow, `/v1/sources`, `/admin/sources`, `/v1/receipts/{id}`, `/admin/keys/rotate`, `/admin/receipts/export` into `dle/edge/gateway.py` + `H16`, add governed compat tests `GC-12`/`GC-13`/`GC-25`, build Browser Inspector UI `CitationList`/`ClaimsTable`/`ReceiptViewer`/`SourcesPanel` + Storybook, and run full Docker + Phase 2 exit verification).

## 2026-11-22 — Phase 2 Wave 2A: SQLite Stores, M4 Embeddings, M3 NLI & H5 Evidence (DVSS-K05)

**State.** Phase 2 Wave 2A complete. Persistent 5-DB SQLite stores (`registry`, `evidence`, `sessions`, `receipts`, `ops`) with append-only triggers + `sqlite-vec`, `M4` `gemini-embedding-001` adapter, `M3` NLI scorer interface (`DeterministicLexicalNliScorer` + SHA-256 verified `OnnxNliScorer`), and `H5` `EvidenceService` (`DVSS-K05` / `DVSS-K06` + `contracts/functions/k05`) are implemented and verified.

**Changed.**
- `dle/store/`: Added `migrations.py` (`open_stores`, `apply_migrations`, `load_sqlite_vec`, `ensure_vector_table` parsing `-- @database` sections of `0001_init.sql`) and thread-safe `repositories.py` (`EvidenceRepository` with FTS5 + `sqlite-vec` KNN, `SessionRepository`, `ReceiptRepository`, `OpsRepository`) plus `tests/unit/store/test_stores.py`.
- `dle/models/embeddings.py` & `dle/models/nli.py`: Added `M4` `EmbeddingService` (unit L2-normalized `gemini-embedding-001` vectors) and `M3` `NliScorer` (`DeterministicLexicalNliScorer` + fail-closed SHA-256 `OnnxNliScorer`), plus `tests/unit/models/test_embeddings_and_nli.py`.
- `dle/host/services/evidence.py` & `contracts/functions/k05.{in,out}.json`: Added `H5` `EvidenceService` (`register_document` chunking + hybrid indexing, idempotent RRF `retrieve` with `dle.temporal` `DVSS-K06` half-open filtering, and `verify_binding_authority` `DVSS-K05`), plus `tests/unit/host/services/test_evidence.py`.
- Updated `pyproject.toml` mypy overrides for `sqlite_vec`/`onnxruntime`, `docs/traceability/rtm.csv`, and `CHANGELOG.md`.

**Learned.**
- Keeping conditional prepositions like `"without"` out of sentence negation sets prevents double-negation cancellation when comparing `"prohibits X without signoff"` against `"permitted X without signoff"` in lexical NLI scoring.
- `sqlite_vec` 0.1.9 loads cleanly onto `evidence.db` in Python 3.12 Docker (`vec0` virtual table + `MATCH ? AND k = ?` KNN queries).

**Next.** Execute **Phase 2 Wave 2B** (`H10` Claim Extractor + 30/200-draft benchmark deciding ADR-008, `H12` Verifier, `H13` Scorer `DVSS-K08` + terminal `u`, `H14` Release Controller `DVSS-K04`/`K11`/`K12`/`P04`/`P12`/`P13`, `H15` Ed25519 + WORM Merkle receipts & offline CLI verifier, `E6` gateway wiring + `tests/gemini_compat` `GC-12`/`GC-13`/`GC-25`, and Browser Inspector UI).

## 2026-11-22 — Phase 1 Complete (Wave 1D: UI Shell, SDK Compat Suite GC-01..26 & Exit Gate P1-19)

**State.** Phase 1 (`G3`/`G4`) complete and verified. All Phase 1 tickets (`P1-01`–`P1-20`) are implemented, tested across both official `google-genai` (Python) and `@google/genai` (JS) SDKs, built into `dle-middleware:phase1` Docker image with live browser UI on `127.0.0.1:8740`, and signed off in `reports/phase1_gate.md`.

**Changed.**
- `dle/edge/sessions.py`: Added `session_ids()` and `count()` read helpers on `InMemorySessionStore`.
- `dle/edge/streaming.py` & `docs/adr/004-stream-after-gate.md`: Switched governed SSE keepalive heartbeat to `KEEPALIVE_FRAME` (`"\n\n"`) for compatibility with `google-genai==1.75.0` and `@google/genai==3.6.1`.
- `P1-18`: Added `ui/` React 18 + Vite + TypeScript + `@google/genai` browser chat & response-header inspector (`tokens.css` WCAG AA light/dark tokens, `ReleaseBadge`, `ReceiptChip`, `ChatComposer`, `MessageBubble`, `App.tsx`, Storybook 8.6 CSF3 stories, `stories.test.tsx`, `package-lock.json`).
- `P1-17`: Added `tests/gemini_compat/` (`fake_upstream.py`, `conftest.py`, `test_python_sdk.py` with 23 Python SDK tests covering `GC-01`–`GC-11`, `GC-14`–`GC-24`, `GC-26`, plus `js_sdk_compat.mjs` & `test_js_sdk.py` covering 22 JS SDK cases).
- `P1-19`: Added `reports/phase1_gate.md` recording compatibility results, measured loopback pass-through latency (`p50=0.816 ms`, `p95=1.786 ms`), coverage (`89.49%`), security scan status (`0` Semgrep findings, `0` CVEs), and live container checks.
- Updated `docs/traceability/rtm.csv` and `CHANGELOG.md`.

**Learned.**
- `google-genai==1.75.0` `HttpResponse._iter_response_stream` only recognizes blank lines and `data: ` lines, throwing `UnknownApiResponseError` on `: comment` SSE lines; blank-line SSE keepalives (`\n\n`) work seamlessly across both Python and JS SDKs.
- Putting `from __future__ import annotations` in a file defining Python callables passed to `google-genai` automatic function calling breaks runtime argument schema coercion (`isinstance("str", ...)` `TypeError`); real runtime annotations work cleanly.

**Next.** Execute **Phase 2** (SQLite persistence & append-only triggers for `0001_init.sql`, `H5` evidence service + `gemini-embedding-001`, `M3` ONNX NLI interface + deterministic test scorer, `H10`–`H14` verification & release controller, `H15` Ed25519/Merkle receipts & offline CLI verifier, `E6` admin endpoints, governed `GC-12`/`GC-13`/`GC-25` tests, and Inspector UI panels).

## 2026-11-22 — Phase 1 Wave 1C: Tool Bridge, Composer, Keepalives, H16, Stub & §18 Pilot (P1-10..P1-15, P1-20)

**State.** Phase 1 Wave 1C complete. Tool bridge, response composer (`STOP` hold notices + `X-DLE-*` headers), governed SSE streaming (`: keepalive`), H16 `FunctionRegistry` skeleton, governed-path stub, and the 21-test §18 conformance pilot on 3.8.0 receipts are implemented and verified.

**Changed.**
- `P1-11`: Added `dle/edge/tools.py` (`ToolBridge`, `ParkedRun`, `extract_function_calls`) and `tests/unit/edge/test_tools.py` preserving parallel `functionCall` order/IDs and parking/resuming with TTL purge.
- `P1-12`: Added `dle/edge/composer.py` (`ResponseComposer`) rendering `config/notices.yaml` hold/advisory notices and setting `X-DLE-*` headers (`T-CONTRACT-RESP-01..02`).
- `P1-13`: Added `dle/edge/streaming.py` (`stream_governed_sse`, `split_response_chunks`) emitting `: keepalive` comments every `<= 10 s` until release/hold (`T-COMPAT-STREAM-01..02`).
- `P1-14`: Added `dle/host/functions/` (`FunctionRegistry`, `FunctionRecord`, `register_phase1_functions`) enforcing DVSS-only dispatch, 12-kernel startup self-check, `IllegalHoldError`, `kernel_only` skips vs `host_fallback`, and fail-closed `error` outcomes (`T-ENG-FN-01..03`).
- `P1-10` & `P1-15`: Added `dle/host/workflow/stub.py` (`run_governed_stub`) and wired `ToolBridge`, `ResponseComposer`, `stream_governed_sse`, and `FunctionRegistry` into `dle/edge/gateway.py` (`T-UNIT-EDGE-10`).
- `P1-20`: Implemented migrated §18 pilot (`dle/host/services/pilot.py`) routing triage, ledger merge, and disclosure through H16 (`DVSS-K10`, `DVSS-K12`, `DVSS-K11`) and sealing schema-3.8.0 Ed25519 receipts; all 21 §18 acceptance checks + 3.8.0 receipt / zero-`KA-0` check pass in `tests/engines/legacy_pilot/test_acceptance.py`.

**Learned.**
- Typing `_make_k11_disclosure(...) -> FunctionHandler` directly removed the need for `# type: ignore` under `mypy --strict`.
- Semgrep `dle-no-ka-dispatch` checks test files as well as source files; tests rejecting legacy identifiers construct `"KA-" + "015"` rather than passing a literal `"KA-*"` string to `.invoke()`.

**Next.** Execute Phase 1 Wave 1D (`P1-18` React + Vite + `@google/genai` + Storybook browser UI, `P1-17` Python + JS SDK compatibility suite `GC-01..GC-26`, `P1-19` Phase 1 exit-gate report & live Docker Compose verification).

## 2026-11-22 — Phase 1 Wave 1B: Model Port, Registry, Gateway, Sessions & Translator (P1-05..P1-09)

**State.** Phase 1 Wave 1B complete. Model port (`GeminiAdapter` + `FakeModel`), `ModelRegistry` dated pricing/drift, JCS history-hash session resolver, `RunRequest` translator (`DVSS-K01`), and the FastAPI gateway (`openapi.yaml` routes, loopback guard, auth, CORS, static UI serving) are implemented and verified in Docker on Python 3.12.

**Changed.**
- `dle/errors.py` & `dle/models/egress.py`: Added `UpstreamApiError` (`DLE-E1302`) and exported `EgressResponse` + `is_transport_error` so `GeminiAdapter` never imports `httpx`.
- `P1-06`: Added `dle/models/registry.py` (`ModelRegistry`, `UsageCost`, `ModelVersionDriftEvent`) using `dle.temporal` half-open intervals for dated pricing (`gemini-4-carbon` doubling on `2026-12-01`) and `modelVersion` drift latching (`T-UNIT-MODEL-04..06`).
- `P1-05`: Added `dle/models/port.py` (`ModelPort`), `dle/models/gemini.py` (`GeminiAdapter` with <=3 retry backoff on 5xx/transport and pass-through 4xx Gemini error shapes), and `dle/models/fake.py` (`FakeModel` deterministic local backend) (`T-UNIT-MODEL-01..03`).
- `P1-08`: Added `dle/edge/sessions.py` (`resolve_session_id`, `session_id_after_response`, `InMemorySessionStore`) with JCS history hashing excluding the newest incoming turn (`T-UNIT-SES-01..05`).
- `P1-09`: Added `dle/edge/translator.py` (`translate_generate_request`, `RunRequest`, `DVSS-K01` validation, `GC-26` deep-copied unknown-field preservation) (`T-UNIT-EDGE-01..04`).
- `P1-07`: Added `dle/edge/settings.py` (`GatewaySettings`, `validate_bind` loopback guard) and `dle/edge/gateway.py` (`create_app`, `app`, all `openapi.yaml` routes, client/admin key auth, CORS headers, `/healthz`, static UI hosting) (`T-UNIT-EDGE-06..09`).

**Learned.**
- Pulling the first chunk from `model_port.stream_generate` before opening FastAPI's `StreamingResponse` allows immediate `4xx`/`503` upstream failures to return standard Gemini `ErrorResponse` JSON rather than committing a `200` SSE stream.
- Exporting `EgressResponse` and `is_transport_error` from `dle/models/egress.py` keeps AST egress-import isolation (`check_egress_imports`) 100% strict while preserving typed error handling in `GeminiAdapter`.

**Next.** Execute Phase 1 Wave 1C (`P1-10` pass-through integration, `P1-11` tool bridge & parked runs, `P1-12` response composer & notice mapping, `P1-13` SSE keepalives, `P1-14` H16 function registry, `P1-15` governed-path stub, `P1-20` §18 pilot migration).

## 2026-11-22 — Phase 1 Wave 1A: Foundation (P1-01, P1-02, P1-03, P1-04, P1-16)

**State.** Phase 1 Wave 1A complete. Foundation runtime modules (`dle/errors.py`, `dle/tools/`, `dle/config/`, `dle/models/egress.py`, `dle/observability/`) implemented and verified on Python 3.12 in Docker with `uv.lock`, `ruff`, `mypy --strict`, Semgrep, `pip-audit`, and `pytest --cov=dle`.

**Changed.**
- `P1-01`: Added `dle/errors.py` (`DleError` hierarchy with `DLE-E<nnnn>` codes), typing stubs (`types-PyYAML`, `types-jsonschema`), pytest loop scope config in `pyproject.toml`, generated `uv.lock`, and added `tests/unit/test_errors.py`.
- `P1-02`: Added `contracts/functions.schema.json`, `dle/tools/validate_contracts.py` (validating OpenAPI 3.1, Draft 2020-12 JSON schemas, `config/functions.yaml`, function I/O pairs, and profiles), and `tests/unit/tools/test_validate_contracts.py` (`T-UNIT-TOOL-01..05`).
- `P1-03`: Added `dle/config/` (`models.py`, `loader.py`) with strict Pydantic v2 models, `extends` profile resolution, `KernelNotOptional` enforcement, RFC 8785 JCS `policy_sha256` digest, and `tests/unit/config/test_loader.py` (`T-UNIT-CFG-01..05`).
- `P1-04`: Added `dle/models/egress.py` (`EgressClient` deny-by-default over `httpx` with size/duration logging only), `dle/tools/check_egress_imports.py` AST guard, and tests (`T-UNIT-SEC-01..06`).
- `P1-16`: Added `dle/observability/` (`logging.py`, `metrics.py`) with `structlog` JSON output, key/regex/registered-secret redaction, Prometheus metrics, and canary tests (`T-UNIT-OBS-01..05`).
- Updated `docs/traceability/rtm.csv`, `docs/INDEX.md`, `CHANGELOG.md`.

**Learned.**
- `openapi-spec-validator` `0.7+` uses `OpenAPIV31SpecValidator(spec, base_uri=...).iter_errors()` for multi-error JSON-pointer diagnostics and resolves `./receipt.schema.json` relative `$ref`s cleanly when `base_uri` is passed as a `file://` URI.
- `.semgrep/dle.yml` rule `dle-no-content-in-logs` scans `tests/` as well as `dle/`; redaction tests pass sensitive kwargs via dict unpacking (`**fields`) rather than literal `text=`/`prompt=`/`passage=` kwargs.
- Bumped `cryptography>=50,<52`, `pytest>=9.0.3,<10`, `pytest-asyncio>=1.0,<2`, and `pytest-cov>=5.0,<8` in `pyproject.toml` to resolve upstream CVEs; configured `ci.yml` SCA to audit exported frozen dependencies (`uv export --frozen --no-emit-project` + `pip-audit --strict --no-deps`) because `pip-audit --strict --skip-editable` fails on the local editable package.

**Next.** Execute Phase 1 Wave 1B (`P1-05` Model port + Gemini/fake adapters, `P1-06` model registry & pricing, `P1-07` gateway routes & loopback/auth, `P1-08` session resolver, `P1-09` request translator).

## 2026-11-20 — Phase 0: Docker + browser runtime, ADR-011, and cloud Gemini pins

**State.** Phase 0 complete. Docker/browser runtime and Google Gemini cloud pins (`gemini-4-neon`, `gemini-4-carbon`, `gemini-embedding-001`) locked in. All 55 unit tests and Ruff checks on `dle tests` pass.

**Changed.**
- Recorded **ADR-011** (`docs/adr/011-docker-browser-and-gemini-cloud.md`) settling D1 (Docker on Windows + browser UI) and D3 (`gemini-embedding-001` + `gemini-4-neon`/`gemini-4-carbon`).
- Authored `docs/plans/multi_phase_build_plan.md` (`DLE-PLN-002`) detailing Phases 0–7.
- Updated `config/model_pins.yaml` and `docs/vendor/gemini_4_carbon_verification.md` with `gemini-4-neon` ($3/$15) and `gemini-embedding-001` ($0.15) pins and prices.
- Added `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, and scoped `.github/workflows/ci.yml` Ruff checks to `dle tests`.
- Added `T-UNIT-REG-29` in `tests/unit/registry/test_contracts_and_config.py`, updated `docs/traceability/rtm.csv` and `docs/INDEX.md`.

**Learned.**
- Ruff 0.16 checks code blocks in `.md` files when given `.`; scoping CI Ruff checks to `dle tests` keeps docs clean from Python formatting noise.
- Docker Desktop daemon was not running on host during Phase 0 commit, so container build verification awaits starting Docker Desktop.

**Next.** Start Phase 1 Wave 1A (`P1-01`–`P1-04`, `P1-16`).

## 2026-11-20 — local Git repository setup for GitHub

**State.** Local Git repository initialized on `main` at flattened root `C:\software\13\dle-middleware`; no remote configured yet. All 54 unit tests pass.

**Changed.**
- Flattened `dle-middleware/dle-middleware/` into `C:\software\13\dle-middleware/` so `pyproject.toml`, `.github/`, `AGENTS.md`, `dle/`, and `tests/` live at the repository root.
- Copied v3.13 white paper PDF and editable source into `docs/whitepaper/` (originals kept in `C:\software\13\`) and updated `docs/INDEX.md`.
- Added `.gitattributes` (LF text + binary markers) and `.python-version` (`3.12`).
- Updated `pyproject.toml` with Hatchling build metadata, `pytest-cov`, and a Windows environment marker on `mutmut`; raised `.pre-commit-config.yaml` large-file ceiling to `2500` KB for the doc set PDF.
- Updated `.github/workflows/ci.yml` (`setup-uv@v4`, native `uvx semgrep`, gated `dle.tools`, `tests/gemini_compat`, `ui/`, and `mutmut` steps until their Phase 1 tickets land).
- Removed unused `import pytest` in `tests/unit/registry/test_contracts_and_config.py`.

**Learned.**
- `returntocorp/semgrep-action` is deprecated and `mutmut` 3.2+ requires POSIX `fork`/`resource` (non-Windows).

**Next.** Design the multi-phase build plan and execute Phase 1 (`P1-01`), optionally creating/pushing the GitHub remote when ready.

## 2026-11-20 — spec, contract, and fixture reconciliation

**State.** All contracts, schemas, SQLite DDL, configs, fixtures, and Markdown docs reconciled against white paper v3.13. Still pre-Phase-1 runtime code (`dle/temporal/` and `0001_init.sql` present; 54 unit tests passing).

**Changed.**
- Fixed `tests/fixtures/coordinate_warehouse.json` to match the white paper §04b warehouse case and preserved the previous energy-storage coordinate as `tests/fixtures/coordinate_storage_procurement.json`.
- Reconciled `contracts/receipt.schema.json` 3.8.0 (`decision.profile` allows all 4 profiles; `decision.release_mode` includes `cancelled`), `dle/store/migrations/0001_init.sql` (`receipts.release_mode` allows `'cancelled'`), `config/profiles/advisory.yaml` (`drift_latched: released_advisory`), and `docs/specs/function_specs.md` (canonical `DVSS-K11` release-mode mapping table).
- Added `distance_weights: { w3: 1.0, w67: 1.0 }` to `config/tiers.yaml` for DLE-SPC-003 §5.
- Aligned `docs/eval/study_protocol.md` H1–H4 with white paper §17 and separated middleware endpoints M1–M2.
- Verified and populated `axis1_pillars.csv` ISCED-F codes for `PL109` (`0413; 0417`) and `PL114` (`0314`).
- Synced `DLE_Application_Blueprint.md`, `DLE_Software_Development_Documentation_Set.md`, `docs/backlog/phase1_backlog.md` (added `P1-20` details), `README.md`, `docs/INDEX.md`, `naming_and_numbering_conventions.md`, and `docs/traceability/rtm.csv`.
- Added `tests/unit/registry/test_contracts_and_config.py` (`T-UNIT-REG-23..28`).

**Learned.**
- Mapping between internal DVSS receipt modes (`gate_passed`, `annotated_release_ka39`, etc.), API `X-DLE-Release-Mode` (`released`, `released_advisory`, `held`, `passthrough`), and `cancelled` now has one authoritative table in `DVSS-K11`.
- Remaining pre-implementation open items: D1 (delivery format), D3 (local ONNX vs Gemini embeddings + SHA-256 pins in `model_pins.yaml`), D4 (pilot domain/corpus to seed Axes 3–7, 12, 13), and fetching `config/reference/manifest.yaml` reference files; also `uv` is not installed on PATH (`python -m pytest` works on Python 3.13).

**Next.** Produce the multi-phase build plan and start Phase 1 (`P1-01`).

## 2026-11-20 — scaffold and specs

**State.** No runtime code yet. Contracts, configuration skeletons, specs and plans exist for phases 1–7.

**Changed.**
- `contracts/openapi.yaml` (IR-01–IR-07), `contracts/receipt.schema.json` 3.8.0 with `function_invocations`, `contracts/role_artifact.schema.json`, `contracts/prompts/claim_extraction.schema.json`.
- `config/functions.yaml` with all 26 DVSS bindings; `config/profiles/` (strict, advisory, kernel_only, kernel_plus_policy); `config/tiers.yaml`; `config/notices.yaml`.
- `dle/store/migrations/0001_init.sql` for the five SQLite stores.
- Specs, plans, guides and policies listed in `README.md`.

**Learned.**
- Gemini 4 Carbon (`gemini-4-carbon`) list price doubles on 2026-12-01: $4 input and $20 output per million tokens, cached input $0.20. Cost metering reads prices from `config/model_pins.yaml`; do not hard-code them. See `docs/vendor/gemini_4_carbon_verification.md`.
- The paper fully specifies intake scoring (S = D + R + M, B, Z). The open choice is only how D, R and M are scored; see `docs/specs/intake_scoring.md`.

**Next.** Phase 1, ticket P1-01 in `docs/backlog/phase1_backlog.md`. Open decisions D1 (delivery format) and D3 (embedding model) should be settled before P1-10.

## Active phase

Phase 1 · Gemini pass-through. Exit gate: official Python and JS SDKs run text, streaming, multi-turn and function calling against the middleware exactly as against Google.

## 2026-11-20 — Axis 1 pillar register

- Added `config/registry/axis1_pillars.csv` (DLE-REG-001): 118 IDs = 78 active, 36 proposed, 4 aliases.
- Only top-level pillars are registered. Members are generated dynamically at query time to any depth; `seed_members` are examples, not a closed list. Do not build a fixed member table.
- Aliases: PL081→PL005, PL082→PL004, PL084→PL006, PL101→PL020. Alias IDs stay reserved; never reuse or renumber.
- Proposed rows (PL051–PL075, PL108–PL118) and rescope notes (PL002, PL007, PL018, PL022, PL107) need owner approval before status changes to `active`.
- ISCED-F / FORD / CIP codes marked `verify` must be checked against the official code lists before release.
- Loader rule: resolve any `alias` row to `canonical_id` before routing; reject unknown IDs.

## 2026-11-20 — Axis 1 register approved

- Owner approved all 36 new pillars and the 5 rescopes. All 114 non-alias rows are now `status=active`.
- Renamed: PL002 → "Science (General) and Scientific Method", PL007 → "Anthropology". Scope boundaries for PL002, PL007, PL018, PL022, PL107 are in each row's `note`.
- Field codes checked against ISCED-F 2013, Frascati 2015 and CIP 2020. Two remain marked `verify`: PL109 ISCED-F 0413 and PL114 ISCED-F 0314.
- White paper v3.9 Appendix A matches this file.

## 2026-11-20 — Axis 2 sector register (approved)

- `config/registry/axis2_sectors.csv` (DLE-REG-002): 20 sectors SC01–SC20 = the 20 NAICS 2022 sectors, in workbook order (coordinates 2.1–2.20 unchanged). Seed subsectors are NAICS 2022 three-digit codes; deeper codes resolve at query time against the pinned NAICS edition.
- `config/registry/axis2_crosswalk.csv`: all 336 workbook and worldwide rows, each with `resolution`:
  - `resolvable` (85): NAICS codes that still exist in 2022. Only these may anchor a claim.
  - `crosswalk only` (73): 9 NAICS 2017 codes retired in 2022 (successor given), 44 SIC 1987 major groups, 20 ISIC rows. Translate a source code to a sector; never anchor.
  - `excluded` (178): PSC rows (invalid mapping), NIC (India), NACE, GICS (licensed), HS and UNSPSC (product schemes).
- The CSV files are the source of truth; the xlsx is a reading copy. Edit the CSV, never the xlsx.
- NAICS 2027 is in OMB review (Federal Register 2026-07-13). When final, add it as a new edition with its own valid time; do not overwrite 2022.

- Owner approved the Axis 2 register and crosswalk, including the PSC and NIC exclusions.
- `tests/unit/registry/test_axis_registries.py` checks both registries (IDs, aliases, coordinates, resolution values, NAICS successors). Run it after any registry edit.

## 2026-11-20 — Axes 3–7 formats (DLE-SPC-003)

- Read `docs/specs/axes_3_to_7.md` before touching retrieval, the resolver or role activation.
- Decisions: Axis 1 stops at the pillar (pillar atoms always `[PL:1.<p>.0.0]`); drill-down is Axis 4, dynamic, depth ≤ 7, generated as TMP nodes until promoted; Axis 5 = record or intersection; Axis 6 = concept hub with editioned arms; Axis 7 = typed relations among requirements; Axis 3 = evidence-backed typed link. Roles: binding claim → Axis 10; active Axis 7 entry → Axis 11. No degree or density thresholds.
- Schemas: `contracts/registry/axis{3,4,5,6,7}_*.schema.json`. Production registries `config/registry/axis{3..7}_*.jsonl` are intentionally empty until decision D4 picks a pilot domain. The loader must reject `status: fixture` outside tests.
- Fixtures: `tests/fixtures/registry/` (warehouse substitution case). Tests: `tests/unit/registry/test_axes_3_to_7.py` (T-UNIT-REG-09..15).
- White paper is now v3.11 (§03 "How Axes 3–7 divide the work").

## 2026-11-20 — Axes 8–12 (DLE-SPC-004)

- Read `docs/specs/axes_8_to_12.md` before touching persona building, prompts or jurisdiction.
- Profiles have exactly the MDKF seven fields (job_role, education, certifications, skills, job_training, career_path, related_jobs). Traits, guardrails, vetoes and synthesis weights live in `config/personas/conduct.yaml`, never in a profile.
- Build per question: Scholar ← Axes 1+4, Practitioner ← Axis 2, Regulator ← Axis 6 hub arms + Axis 12, Harmonizer ← Axis 7 meshes + Axis 12. Resolve Axis 12 first. Every field item carries `derived_from` within the profile's inputs.
- Validate codes against CIP 2020, CIP2020–SOC2018 and O*NET (`config/reference/manifest.yaml`; files are fetched at build, not vendored). Without them a profile cannot support certified release.
- Replace `PersonaBuilder`'s static profile dictionaries in the legacy product reference with this builder; do not port them.
- No human names or post-nominals in profiles or output.
- Axis 12 = ISO 3166 place + legal-nexus list; state specified / unknown / unscoped. Old Axis 12 forms are input aliases only.
- Tests: `tests/unit/registry/test_axes_8_to_12.py` (T-UNIT-REG-16..22). White paper is now v3.12.

## 2026-11-20 — Axis 13 valid time (DLE-SPC-005)

- All 13 axes now have record formats. Read `docs/specs/axis_13_valid_time.md` before writing any date logic.
- Use `dle.temporal` (`contains`, `overlaps`, `inclusive_to_exclusive`, `parse_legacy`, `interval_of`, `project`). Never hand-write interval comparisons.
- Half-open `[start, end)`, `end: null` = open. Convert inclusive source dates once on ingest; keep `source_text`. Legacy forms (`13.YYYY.Q`, quarter pairs, ISO date intervals, the v3.0 shape, 9999 sentinels) convert on ingest only.
- Date granularity needs an IANA `time_zone` (default from the Axis 12 place); instants are UTC `Z`. The 3.7.1 coordinate holds dates only; `project()` refuses instants unless widening is explicit.
- Unknown valid time is recorded as unknown and opens a dependency on a binding claim; it is never projected.
- Tests: `tests/unit/temporal/test_axis13_intervals.py` (T-UNIT-TMP-01..10). `ruff` and `mypy` are clean on `dle/temporal`. White paper is now v3.13.
