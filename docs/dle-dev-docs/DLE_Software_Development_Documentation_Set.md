# DataLogicEngine 13-Axis Middleware — Software Development Documentation Set

Nov 20, 2026 · @kevin herrera

## 1. Document control

This set governs how the 13-axis middleware is specified, built, verified and released. It covers the Gemini-compatible API, the three core engines (12-step refinement workflow, 10-layer FROST stack, Quad Persona engine), the tier logic that drives them, and the chat test UI. The design source is the DataLogicEngine white paper v3.13 and the [Application Blueprint](https://claude.ai/artifact/6Q6zGoHyFYZTnJH8udgejn); where this set and the blueprint disagree, this set wins and the blueprint is corrected.

**Product type.** Installed middleware on a workstation, server or VM. Its only outbound connection is to the Gemini API. Market is US only: regulated industry and federal. That makes the obligations those of a software manufacturer, not a service provider.

### Documents in this set

| ID | Document | Standard basis | Owner | Changes when |
| --- | --- | --- | --- | --- |
| DLE-SDP | Software Development Plan | ISO/IEC/IEEE 12207:2017 | Tech lead | Process or phase plan changes |
| DLE-SRS | Software Requirements Specification | ISO/IEC/IEEE 29148:2018 | Tech lead | Any requirement added, changed or retired |
| DLE-SAD | Software Architecture Description | ISO/IEC/IEEE 42010:2022 | Architect | A component, boundary or decision changes |
| DLE-ICD | Interface Control Document | ISO/IEC/IEEE 15289:2019 (interface description) | API owner | Any external contract changes |
| DLE-SDD | Software Design Description | IEEE 1016-2009 | Module owners | A module's interface or data model changes |
| DLE-STP | Test and V&V Plan | ISO/IEC/IEEE 29119-3:2021, IEEE 1012-2016 | Test lead | Test levels, criteria or integrity levels change |
| DLE-SEC | Secure Development and Threat Model | NIST SP 800-218 v1.1 and 800-218A, OWASP ASVS 5.0, OWASP Top 10 for LLM Applications | Security lead | New attack surface, dependency or finding |
| DLE-AIM | AI Management and Risk | ISO/IEC 42001:2023, ISO/IEC 23894:2023, NIST AI RMF 1.0 with AI 600-1 | AI risk owner | Model, threshold, calibration or intended use changes |
| DLE-CMR | Configuration, Release and Operations | IEEE 828-2012, SLSA v1.0, CycloneDX 1.6 | Release manager | Each release |
| DLE-RTM | Requirements Traceability Matrix | ISO/IEC/IEEE 29148:2018 §6.5 | Tech lead | Every SRS or test change |

Four product-design documents complete the set: **DLE-USR** User Personas and Stories (§12), **DLE-UXJ** User Journeys (§13), **DLE-STY** Style Guide for UI and code (§14, WCAG 2.2 AA), and **DLE-SB** Storybook Component Catalog (§15). The product owner keeps the first two; the UI lead keeps the last two.

One person may hold several owner roles. Remediation work done by coding agents follows the same review gates as human work.

### Identifiers and versioning

- Requirements: `FR-<area>-<nn>` (functional), `NFR-<attribute>-<nn>` (non-functional), `IR-<nn>` (interface). IDs are never reused.
- Architecture decisions: `ADR-<nnn>`, one file per decision in `docs/adr/`.
- Tests: `T-<level>-<area>-<nn>`, each naming the requirement IDs it verifies.
- Documents use semantic versions. A minor version adds or clarifies; a major version changes an accepted requirement or interface.
- The paper's function IDs (DVSS-K01–K12, DVSS-P01–P14) and component IDs (E1–E6, H1–H16, M1–M4, O1–O4, C1) are reused as-is.

### Approval

A document version is accepted when its owner and one reviewer who did not write it approve the pull request that changes it. The SRS, ICD and AI management documents also need the release manager's sign-off, since they bind what a release may claim.

| Version | Date | Change |
| --- | --- | --- |
| 0.1 | 2026-11-20 | First draft of the full set |

## 2. Software Development Plan (DLE-SDP)

The middleware is built incrementally in seven phases, each closed by an exit gate that must pass before the next starts. Work follows the ISO/IEC/IEEE 12207 technical processes, tailored for a small team using coding agents.

### Lifecycle model

Incremental delivery with a fixed architecture. The SAD and ICD are baselined before phase 1. Each phase then runs the same loop: refine requirements, design, implement, verify, and review against the exit gate. A working, useful system exists from phase 2 on.

| Phase | Builds | Engines touched | Exit gate |
| --- | --- | --- | --- |
| 1 · Gemini pass-through | Gateway, sessions, translator, tool bridge, composer, model gateway, chat UI | None yet; the workflow runs as a stub | Official Python and JS SDKs run text, streaming, multi-turn and function calling exactly as against Google |
| 2 · Verify and gate | Evidence, claim extractor, NLI, verifier, scorer, release controller (advisory), receipts | Workflow steps 9–12; FROST layers 8–10 | Released answers carry grounding metadata; unsupported claims hold; receipts verify |
| 3 · Address and spine | Registry, coordinate resolver, graph packer, overlay | Steps 1–4 and 7–8; layers 1, 2, 6, 7 | Coordinate fixtures pass; PPR retrieval runs behind a switch next to dense retrieval |
| 4 · Roles and ledger | Quad Persona engine, writer, ledger, retry and escalation | Steps 5–6 and 11 loops; layers 3–5 | Every §18 fixture passes against real Gemini calls |
| 5 · Router and tiers | Intake scoring, binding detection, risk check, tier table | Tier drives all three engines | Router fixtures pass; per-tier role fan-out and call budgets match the tier table |
| 6 · Calibration pilot | Calibration job, strict profile, drift latch | Layer 9 cutoff and drift | About 100 graded queries at α = .05; coverage and loss reported |
| 7 · Full study | Evaluation harness | All | The §17 study runs to its registered plan |

Function bindings by phase: phase 1 builds H16 with K01 and K10 stubs; phase 2 adds K04, K05, K08, K11, K12 and P04, P12, P13; phase 3 adds K02, K06, K07 and P01, P03, P06; phase 4 adds K03, K09 and P02, P07, P08, P10, P11; phase 5 completes K10 with real intake scoring; phases 6–7 run P14 offline and the kernel-only ablation. P05 and P09 are built last, behind their profile switches.

### Roles

| Role | Responsibility |
| --- | --- |
| Tech lead | Owns requirements, plan and phase gates; approves merges to `main` |
| Architect | Owns the SAD and ADRs; reviews any change that crosses a component boundary |
| Security lead | Owns the threat model, dependency policy and release security checks |
| AI risk owner | Owns model pins, thresholds, calibration data and the system card |
| Release manager | Builds, signs and publishes releases; owns the changelog |
| Coding agent | Implements tickets; never approves its own pull request or edits a frozen fixture |

### Reviews

| Review | When | Input | Output |
| --- | --- | --- | --- |
| Requirements review | Start of each phase | SRS delta | Accepted requirement IDs |
| Design review | Before code on any boundary change | SDD delta, ADR | Approved design or rework list |
| Code review | Every pull request | Diff, test results, coverage delta | Approve or request changes |
| Phase gate review | End of each phase | Exit-gate test report, RTM | Go or no-go for the next phase |
| Release readiness review | Each release | Release checklist (§10) | Signed release or hold |

### Definition of done for a ticket

- [ ] Each changed behavior traces to a requirement ID, and the RTM is updated.
- [ ] Unit and contract tests added or updated, passing on Linux and Windows CI.
- [ ] Lint, type check, SAST, dependency scan and secret scan pass with no new findings.
- [ ] Fixtures in `tests/fixtures/` are unchanged unless the ticket is a reviewed fixture change.
- [ ] Docs touched: SDD for interfaces, ICD for API, ADR for decisions, `HANDOFF.md` for agent context.
- [ ] Reviewed and approved by someone other than the author.

### Tooling

Python 3.12 with FastAPI; SQLite with FTS5 and sqlite-vec; ONNX Runtime for local NLI; React and Vite with `@google/genai` for the chat UI. Quality gates: `ruff`, `mypy --strict` on `dle/`, `pytest` with coverage, `mutmut` on the release path, Semgrep, `pip-audit`, `gitleaks`. CI runs Linux and Windows and fails on errors as well as failures.

## 3. Software Requirements Specification (DLE-SRS)

The middleware shall look like the Gemini API to any client, and shall run every request through the 12-step workflow, the 10-layer FROST stack and the Quad Persona engine at the depth its tier sets. Each requirement below is atomic, uses "shall", and is verified by the method shown (T test, I inspection, A analysis, D demonstration).

### 3.1 Purpose, users and operating environment

- **Users.** Application developers who call the API through a Gemini SDK; testers using the chat UI; an administrator who manages registries, keys and policy.
- **Environment.** Windows 11, Windows Server 2022 or Linux on a workstation, server or VM. Python 3.12 runtime. One outbound HTTPS connection to the Gemini API.
- **Out of scope.** Hosting for third parties, model training, EU market placement.

### 3.2 Functional requirements

**API compatibility (FR-API)**

| ID | Requirement | Verify |
| --- | --- | --- |
| FR-API-01 | The system shall serve `GET /v1beta/models`, `:generateContent`, `:streamGenerateContent` and `:countTokens` with Gemini request and response shapes. | T |
| FR-API-02 | The system shall expose virtual models `dle-13axis-strict` and `dle-13axis-advisory` and pass through any other model name unchanged. | T |
| FR-API-03 | An unmodified google-genai SDK client shall work after only its base URL and API key change. | T |
| FR-API-04 | Released responses shall carry `groundingMetadata` linking each material claim to its source passage. | T |
| FR-API-05 | Every response shall carry `X-DLE-Release-Mode` and `X-DLE-Receipt` headers. | T |
| FR-API-06 | A held answer shall return `finishReason` STOP with the hold reason and receipt, not an HTTP error. | T |
| FR-API-07 | Streaming shall send SSE keepalives while the gate runs and stream text only after release. | T |
| FR-API-08 | The system shall serve `GET /v1/receipts/{id}` and `GET /v1/sources`. | T |

**Sessions and tools (FR-SES, FR-TOOL)**

| ID | Requirement | Verify |
| --- | --- | --- |
| FR-SES-01 | The session ID shall be the hash of the JCS-canonical history, excluding the newest user turn, scoped by tenant, model and systemInstruction. | T |
| FR-SES-02 | An `X-DLE-Session` header, when present, shall override the computed session ID. | T |
| FR-SES-03 | The session ID shall also be the receipt chain ID. | T |
| FR-TOOL-01 | The system shall pass every client tool and function declaration to Gemini unchanged and shall not block any `functionCall`. | T |
| FR-TOOL-02 | A `functionCall` shall be returned to the client as Gemini returns it. | T |
| FR-TOOL-03 | A `functionResponse` shall be ingested as app-tool evidence and the run shall resume at workflow step 4. | T |
| FR-TOOL-04 | Results from Google built-in tools shall enter the evidence store at lower weight than authoritative sources. | T |
| FR-TOOL-05 | A function flagged consequential shall trigger Regulator review of the surrounding claims, never a block. | T |

**12-step refinement workflow (FR-WF)**

| ID | Requirement | Verify |
| --- | --- | --- |
| FR-WF-01 | Every governed request shall execute steps 1–12 in order, recording each step's start, end and outputs in the run state. | T |
| FR-WF-02 | At step 11 the system shall retry from step 4 only when a fixable evidence gap and an authorized source both exist. | T |
| FR-WF-03 | Retries shall number at most 2, each adding one hop, to at most 4 hops. | T |
| FR-WF-04 | A binding claim drafted with no Regulator active shall cause one escalation: S\_eff recomputed with B = 1 and re-entry at step 5. | T |
| FR-WF-05 | Escalation shall happen at most once per request and shall be logged even when it precedes the first retry. | T |
| FR-WF-06 | Retry decisions shall be taken before the calibrated cutoff is read. | T, I |
| FR-WF-07 | The release rule shall be applied exactly once, to the terminal candidate. | T |

**10-layer FROST stack (FR-FL)**

| ID | Requirement | Verify |
| --- | --- | --- |
| FR-FL-01 | Each of the ten layers shall be a separate module with one responsibility and one durable output record. | I |
| FR-FL-02 | Each attempt shall append to the run state; no layer shall overwrite an earlier attempt's evidence or veto history. | T |
| FR-FL-03 | Layer 1 shall validate anchors and compute the tier and active-axis mask; model-proposed labels stay candidates until validated. | T |
| FR-FL-04 | Layer 2 shall record the graph revision, selected edges and source manifest. | T |
| FR-FL-05 | Layer 7 shall check jurisdiction and effective interval on every issued claim and record the missing premise when it fails. | T |
| FR-FL-06 | Layer 10 shall hash the returned bytes, sign, anchor and purge session data under retention policy. | T |
| FR-FL-07 | Every material claim in the final text shall point to its latest verified claim record. | T |

**Quad Persona engine (FR-QP)**

| ID | Requirement | Verify |
| --- | --- | --- |
| FR-QP-01 | The engine shall provide four roles bound to axes 8–11: Scholar, Practitioner, Regulator and Harmonizer. | T |
| FR-QP-02 | The Regulator shall be activated for any binding claim; the Harmonizer when an Axis 7 entry applies. | T |
| FR-QP-03 | Profile selection shall apply mandatory qualifications first, then rank by M = 0.25E + 0.45C + 0.30X with a stable tie-break, and persist the winner. | T |
| FR-QP-04 | Each profile shall carry seven fields: job role, education, certifications, technical skills, job training, career path, related jobs. | T |
| FR-QP-05 | Each role shall receive only its sealed, role-filtered packet; packet digests shall be recorded. | T |
| FR-QP-06 | In blinded mode the Regulator and Harmonizer shall see the proposal before the advocates' arguments. | T |
| FR-QP-07 | Every role output shall validate against the role artifact schema; unknown IDs shall be rejected. | T |
| FR-QP-08 | Agreement among roles shall not raise the score by itself. | T, A |

**Tiers (FR-TIER)**

| ID | Requirement | Verify |
| --- | --- | --- |
| FR-TIER-01 | The router shall compute S\_eff = max(S, 3B, 6Z), with B also set when R ≥ 2. | T |
| FR-TIER-02 | Tiers shall be S\_eff 0–2, 3–5 and 6–9. | T |
| FR-TIER-03 | Roles, starting hops, retries and call budgets per tier shall come from one configuration table, read by all three engines. | T, I |
| FR-TIER-04 | Worst-case model calls shall not exceed 9 (21 escalated) at tier 1, 18 (22 escalated) at tier 2 and 18 at tier 3. | T |

**Function bindings (FR-FN)**

The engines do their work through 26 bound functions: 12 kernel functions (DVSS-K01–K12) that always run and 14 policy functions (DVSS-P01–P14) that a release profile turns on. The 100-slot KA catalog is inventory only. KA numbers are legacy references, never dispatch keys.

| ID | Requirement | Verify |
| --- | --- | --- |
| FR-FN-01 | Every bound function shall be dispatched by its DVSS ID; a KA number shall never select or authorize an implementation. | T, I |
| FR-FN-02 | All 12 kernel functions shall be host-implemented and always active; the service shall refuse to start if any is missing or fails its self-test. | T |
| FR-FN-03 | A release profile shall enable policy functions only by DVSS ID, and the policy digest shall include the enabled set. | T |
| FR-FN-04 | Catalog-only entries (KA-001–KA-100 without a DVSS binding, and KA-101–KA-114) shall be loadable for traceability but shall have no executable registration. | T |
| FR-FN-05 | An external adapter shall be enabled only when its version, input and output schema hashes, scope and permissions match the binding record; no permission shall be inherited through a matching number or registry flag. | T |
| FR-FN-06 | Veto authority shall come only from DVSS-K12 and the objection ledger, never from a registry `Can_Veto` field. | T, I |
| FR-FN-07 | Where a profile declares escalation (P07), role token allocation (P08) or drift gating (P12) and the module is disabled, the host fallback shall run; the behavior shall never be skipped. | T |
| FR-FN-08 | Each run shall record every function invoked, with ID, version, binding level and outcome, and the receipt shall list them. | T |
| FR-FN-09 | The system shall ship `kernel_only` and `kernel_plus_policy` profiles that keep all mandatory host behavior, for the §17 ablation. | T |

**Verification, release and receipts (FR-VER, FR-REL, FR-RCPT)**

| ID | Requirement | Verify |
| --- | --- | --- |
| FR-VER-01 | Claims shall be extracted independently of the writer and scored by the pinned local entailment model. | T |
| FR-VER-02 | Only the verifier shall close an objection, citing evidence that satisfies its predicate. | T |
| FR-VER-03 | The objection ledger shall be append-only. | T |
| FR-REL-01 | The hard gate H shall fail on any open blocking objection or unsupported binding claim. | T |
| FR-REL-02 | The terminal score shall be u = 0.40(1 − min z over J) + 0.20(1 − mean z) + 0.25(1 − min b over J) + 0.15d. | T |
| FR-REL-03 | The strict profile shall release only when H passes and u meets the conformal risk control cutoff. | T |
| FR-REL-04 | A tripped CUSUM drift latch shall force hold until an administrator resets it. | T |
| FR-RCPT-01 | Each response shall produce a JCS-canonical receipt signed with Ed25519. | T |
| FR-RCPT-02 | Receipts shall be anchored under the configured profile: external transparency log, customer-hosted log or local WORM Merkle. | T |
| FR-RCPT-03 | A receipt shall bind the response SHA-256, attempt digests, model version, policy digest and evidence references. | T |

**Chat test UI (FR-UI)**

| ID | Requirement | Verify |
| --- | --- | --- |
| FR-UI-01 | The UI shall call the middleware through the official Gemini JS SDK. | I |
| FR-UI-02 | For each run the UI shall show tier, active roles, steps executed, retries, release mode and the receipt. | D |

### 3.3 Non-functional requirements

| ID | Attribute (ISO/IEC 25010) | Requirement | Verify |
| --- | --- | --- | --- |
| NFR-PERF-01 | Performance | Middleware overhead outside model calls shall be under 400 ms at p95 for tier 1. Target to be confirmed by phase 1 measurement. | T |
| NFR-PERF-02 | Performance | Streaming keepalives shall be sent at least every 10 s. | T |
| NFR-REL-01 | Reliability | A Gemini error or timeout shall yield a hold with a receipt, never an unsigned answer. | T |
| NFR-REL-02 | Reliability | Model calls shall retry with backoff at most 3 times per call. | T |
| NFR-SEC-01 | Security | The API shall bind to loopback by default; any other bind is an explicit, logged opt-in. | T |
| NFR-SEC-02 | Security | Every request shall be authenticated, including from localhost. | T |
| NFR-SEC-03 | Security | All outbound connections shall pass through one egress allowlist whose only default entry is the Gemini endpoint. | T |
| NFR-SEC-04 | Security | Signing keys shall be stored with OS-protected storage and never logged. | T, I |
| NFR-PRIV-01 | Privacy | Logs and diagnostic bundles shall exclude prompt and response content unless debug capture is switched on. | T |
| NFR-PRIV-02 | Privacy | Session data shall be purged at the end of its retention period. | T |
| NFR-MAINT-01 | Maintainability | Every component shall depend on ports, not concrete providers, so the model and NLI backends can be swapped. | I |
| NFR-PORT-01 | Portability | The system shall install and pass the full test suite on Windows and Linux. | T |
| NFR-OBS-01 | Observability | Each run shall record tokens, cost, latency per step and per model call. | T |
| NFR-COST-01 | Cost | Per-request cost shall be metered from dated per-model prices in config/model\_pins.yaml and reported per tier. Gemini 4 Carbon: $2 / $10 per million input / output tokens through 2026-11-30, $4 / $20 from 2026-12-01 (verified 2026-11-20). | T |
| NFR-ACC-01 | Accessibility | The chat UI shall meet WCAG 2.2 AA. | T, I |

## 4. Software Architecture Description (DLE-SAD)

The architecture is a five-layer installed middleware: edge, host, model, stores and offline tools. The host holds the three engines, and only the model layer calls out, to Google. The diagrams live in the [Application Blueprint](https://claude.ai/artifact/6Q6zGoHyFYZTnJH8udgejn); this section records who they serve, what they must answer, and the decisions behind them, as ISO/IEC/IEEE 42010 asks.

### Stakeholders and concerns

| Stakeholder | Concerns |
| --- | --- |
| Application developer | Drop-in Gemini compatibility; tool calls never blocked; predictable latency and cost |
| Regulated or federal operator | What leaves the machine; audit evidence; accreditation inside their boundary |
| Reviewer or auditor | Can a released answer be traced to sources and replayed from its receipt? |
| AI risk owner | Calibration, drift, model version changes, stated limitations |
| Maintainer or coding agent | Clear module boundaries; one place per rule; fixtures that catch regressions |

### Viewpoints and views

| Viewpoint | Concerns framed | View (where) |
| --- | --- | --- |
| Context | Boundary, actors, egress | System context diagram, Blueprint §System context |
| Functional | Engines, components, responsibilities | Three core engines and component map, Blueprint |
| Process | Order of work, loops, tool branch | Request lifecycle diagram, Blueprint |
| Information | Stores, schemas, receipts, retention | §6 of this set; `contracts/` schemas |
| Development | Packages, dependencies, ports | Repository layout, Blueprint; §6 of this set |
| Deployment | Hosts, OS, processes, network | §10 of this set |
| Security | Trust boundaries, threats, controls | §8 of this set |

### Architectural principles

1. **Gemini on the outside, DVSS on the inside.** Clients see the Gemini API; nothing about the 13-axis core leaks into the wire contract except the `X-DLE-*` headers and grounding metadata.
2. **One table drives depth.** The tier table is the only place that sets roles, hops, retries and call budgets.
3. **Engines over services.** The workflow orders work, FROST layers own it, the Quad Persona engine supplies perspectives; shared services hold no engine logic.
4. **Append, never overwrite.** Run state, ledger and receipts are append-only.
5. **Ports at every external edge.** Model, NLI, embeddings and anchoring sit behind interfaces with fakes for tests.
6. **One way out.** All egress goes through a single allowlisted client.

### Architecture decisions

| ADR | Decision | Status | Reason |
| --- | --- | --- | --- |
| ADR-001 | Expose a Gemini-compatible API rather than a custom one | Accepted | Existing apps switch by changing the base URL |
| ADR-002 | Pass all tool and function calls through unblocked | Accepted | End users may need them; risk is handled by evidence weighting and Regulator review |
| ADR-003 | Identify sessions by hashing canonical history | Accepted | Gemini's API is stateless; the hash needs no client change and doubles as the receipt chain ID |
| ADR-004 | Pseudo-stream only after the gate passes | Accepted | Streaming unverified text would bypass the release rule |
| ADR-005 | SQLite for all stores | Accepted | Single-host install, no server to run; FTS5 and sqlite-vec cover search |
| ADR-006 | Local ONNX NLI for entailment | Accepted | Verification must not depend on the model it checks, and must not add egress |
| ADR-007 | Holds return STOP plus headers, not HTTP errors | Accepted | Keeps SDK clients working; the hold is visible in headers and receipt |
| ADR-008 | Gemini 4 Carbon for personas and writer, a cheaper Gemini model for intake and extraction | Proposed | Cost; to be confirmed against phase 2 extraction accuracy |
| ADR-009 | Dispatch functions by DVSS ID through one registry (H16); KA numbers are catalog references only | Accepted | Legacy numbers collide with enterprise registry titles; a number must never grant execution |
| ADR-010 | Kernel functions are host code and cannot be disabled; policy functions are profile-controlled with required host fallbacks | Accepted | Keeps safety behavior independent of configuration and makes the §17 ablation clean |

Each ADR is a file in `docs/adr/` with context, options considered, decision and consequences.

## 5. Interface Control Document (DLE-ICD)

The external contract is the Gemini REST API (`v1beta`) plus two DLE endpoints and four response headers. Anything not listed here is passed through to Gemini unchanged. The contract version is `dle-api 1.0`, reported in `X-DLE-API-Version`.

### Endpoints

| ID | Method and path | Behavior |
| --- | --- | --- |
| IR-01 | `GET /v1beta/models` | Gemini's model list plus `dle-13axis-strict` and `dle-13axis-advisory` |
| IR-02 | `POST /v1beta/models/{model}:generateContent` | Governed run for DLE models; pass-through for others |
| IR-03 | `POST /v1beta/models/{model}:streamGenerateContent` | SSE; keepalives during the gate, then the released text in chunks |
| IR-04 | `POST /v1beta/models/{model}:countTokens` | Forwarded to Gemini |
| IR-05 | `GET /v1/receipts/{id}` | Signed receipt as JSON, with anchor proof |
| IR-06 | `GET /v1/sources` | Registered evidence sources and their authority class |
| IR-07 | `/admin/*` | Registry release, key rotation, drift latch reset; admin credential only, loopback only |

**Authentication.** Clients send a middleware API key in `x-goog-api-key` or `?key=`, the same places the SDK already uses. The middleware's own Gemini key is never exposed to clients.

### Response headers

| Header | Values | Meaning |
| --- | --- | --- |
| `X-DLE-Release-Mode` | `released`, `released_advisory`, `held`, `passthrough` | Outcome of the release rule |
| `X-DLE-Receipt` | Receipt ID | Fetch with IR-05 |
| `X-DLE-Tier` | `1`, `2`, `3` | Tier used, after any escalation |
| `X-DLE-API-Version` | `1.0` | Contract version |
| `X-DLE-Session` (request) | Opaque string | Optional override of the computed session ID |

### Body extensions

- `groundingMetadata.groundingChunks` lists each cited passage with its source ID and revision.
- `groundingMetadata.groundingSupports` links each text segment to the chunks that support it.
- `modelVersion` reports the actual Gemini model version used.
- On a hold, `candidates[0].content` carries the hold notice and `finishReason` stays `STOP`.

### Tool-call contract

1. Client sends tools and function declarations; the middleware forwards them unchanged.
2. When Gemini returns a `functionCall`, the middleware returns it to the client as is, with `X-DLE-Release-Mode: passthrough`, and parks the run.
3. The client runs the function and sends a `functionResponse` in the next turn. The session hash finds the parked run.
4. The middleware ingests the response as app-tool evidence and resumes at workflow step 4.
5. A function the administrator flags consequential adds Regulator review of claims that rely on it.

### Error mapping

| Condition | HTTP | Body |
| --- | --- | --- |
| Bad request shape | 400 | Gemini-style error, `INVALID_ARGUMENT` |
| Missing or bad client key | 401 / 403 | `UNAUTHENTICATED` / `PERMISSION_DENIED` |
| Rate or budget limit | 429 | `RESOURCE_EXHAUSTED` |
| Gemini unavailable or timed out | 200 | Held answer with receipt (NFR-REL-01) |
| Internal fault before any model call | 500 | `INTERNAL`, no content |

### Receipt (summary)

A receipt is a JCS-canonical JSON object signed with Ed25519. It holds receipt ID, session and chain position, response SHA-256, model version, policy digest, tier, attempt digests, claim and objection outcomes, evidence references, function invocations (DVSS ID, version, binding level, implementation, outcome), release mode and anchoring proof. The normative schema is `contracts/receipt.schema.json`.

### Compatibility rules

- New optional headers and body fields are minor changes. Removing or renaming any field is a major change and needs a new `X-DLE-API-Version`.
- A Gemini API change is absorbed by the translator; the contract test suite (`tests/gemini_compat/`) runs against the official SDKs every release.

## 6. Software Design Description (DLE-SDD)

The design is a set of Python packages under `dle/`, one per engine plus shared services, joined by typed interfaces and a single append-only run state. Each module owner keeps the module's entry here current; the code layout is the Blueprint's repository layout.

### Module catalog

| Package | Contents | Depends on |
| --- | --- | --- |
| `dle.edge` | E1 gateway, E2 sessions, E3 translator, E4 tool bridge, E5 composer, E6 admin | `dle.host.workflow`, `contracts` |
| `dle.host.workflow` | H1 orchestrator; `steps/s01_ingest` … `s12_seal` | `frost`, `quad`, `tiers` |
| `dle.host.frost` | `l01_grounding` … `l10_receipt` | `services`, `quad` |
| `dle.host.quad` | H8: `roles`, `profiles`, `packets`, `artifact` | `services`, `models` (via ports) |
| `dle.host.tiers` | The tier table and its loader | `config` |
| `dle.host.services` | H2 router through H15 receipts | `store`, `models` (via ports) |
| `dle.models` | M1 gateway, M2 registry, M3 NLI, M4 embeddings, `fakes/` | Egress client |
| `dle.store` | One module per SQLite database, with migrations | — |
| dle.host.functions | H16: registry, adapters, kernel/ (K01–K12), policy/ (P01–P14) | services, config, contracts |

Dependencies point downward only. `edge` never imports `services` directly, and no engine imports another engine's internals.

### Core interfaces

```python
class RunRequest(BaseModel):          # built by E3 from a Gemini request
    session_id: str; tenant: str; model: str
    contents: list[Content]; tools: list[Tool]; system_instruction: str | None

class RunResult(BaseModel):           # read by E5 to build the Gemini response
    mode: Literal["released", "released_advisory", "held", "passthrough"]
    text: str | None; function_call: FunctionCall | None
    grounding: GroundingMetadata | None; receipt_id: str; tier: int

class ModelPort(Protocol):
    async def generate(self, call: ModelCall) -> ModelReply: ...
class EntailmentPort(Protocol):
    def score(self, premise: str, hypothesis: str) -> Entailment: ...
class EvidencePort(Protocol):
    def search(self, scope: QueryScope, k: int) -> list[Passage]: ...

class Layer(Protocol):                # every FROST layer module
    number: int
    def run(self, state: RunState, ctx: StepContext) -> LayerRecord: ...

class Ledger:          def merge(self, records: list[RoleArtifact]) -> LedgerDelta: ...
class ReleasePolicy:   def decide(self, terminal: Candidate) -> Decision: ...
class ReceiptService:  def seal(self, run: RunState, response_bytes: bytes) -> Receipt: ...
```

### Run state

`RunState` is append-only. It holds the snapshot ID, query scope, tier and active-axis mask, graph revision, an ordered list of attempts, role packet manifests, claim and objection ledgers, candidate versions, policy digest and the step log. An attempt records which steps and layers ran, with each `LayerRecord`. Functions return deltas; only the orchestrator appends them.

### Run states and transitions

| State | Entered when | Leaves to |
| --- | --- | --- |
| `received` | E3 builds the RunRequest | `running` |
| `running` | Step 1 starts | `parked_tool`, `retrying`, `escalated`, `deciding` |
| `parked_tool` | Gemini returns a functionCall | `running` (at step 4, on functionResponse) or `expired` |
| `escalated` | Binding claim with no Regulator, first time | `running` (at step 5, higher tier) |
| `retrying` | Step 11 finds a fixable gap with an authorized source, retries < 2 | `running` (at step 4, one more hop) |
| `deciding` | No retry left or none useful | `released`, `released_advisory`, `held` |
| terminal | Step 12 seals the receipt | — |

### Data stores

| Store | Holds | Retention |
| --- | --- | --- |
| `registry.db` | Axis registries, spine, crosswalks, persona profile store | Versioned releases, kept |
| `evidence.db` | Passages, FTS5 index, sqlite-vec embeddings, source authority | Until the source is retired |
| `sessions.db` | Session overlay, parked runs, session hypotheses | Configurable, default 24 h |
| `receipts.db` | Receipts, chain links, Merkle roots | Configurable, default 7 years |
| `ops.db` | Run metrics, cost, drift statistics | Default 90 days |
| `calibration/` | Graded sets and cutoff artifacts | Kept per model pin |
| `keys/` | Ed25519 signing keys, OS-protected | Rotated by admin |

### Configuration

All tunables live in `config/` as versioned files: release profiles, the tier table, the persona profile store, model pins, function flags and source policy. The policy digest in each receipt is the hash of the loaded configuration.

### Function registry and dispatch (H16)

A new host component, H16, sits between the engines and the functions they use. Workflow steps and FROST layers never call function code directly. They call `functions.invoke("DVSS-K05", ctx)`, and H16 decides what runs.

**Three binding levels, three loaders.**

| Level | Source | At startup | At runtime |
| --- | --- | --- | --- |
| Kernel (K01–K12) | `dle/host/functions/kernel/` | All 12 must register and pass self-tests, or the service exits | Always invoked at their hooks; no profile can disable them |
| Policy (P01–P14) | `dle/host/functions/policy/` | Registered; enabled per release profile | Invoked only if enabled; P07, P08 and P12 fall back to host code when disabled but declared |
| Catalog (KA-001–KA-114) | `config/catalog/ka100.csv`, `enterprise_ka114.json` | Loaded read-only into `registry.db` | Never dispatchable; visible in the admin UI and traceability map |

**Binding record.** Each kernel and policy function has one entry in `config/functions.yaml`:

```yaml
- id: DVSS-K05
  name: Evidence acquisition and binding verification
  level: kernel
  legacy_ka: KA-015          # traceability only; collides with registry "Temporal Reasoning"
  hooks: [s04_retrieve, s09_verify_authority]
  layers: [L2, L8]
  version: 1.0.0
  input_schema: contracts/functions/k05.in.json
  output_schema: contracts/functions/k05.out.json
  permissions: {reads: [evidence, overlay], writes: [run_state], can_hold: false, can_escalate: false}
  implementation: host       # host | adapter
```

**Adapter gate.** A policy function may use an external implementation, such as an enterprise DataLogicEngine module, through an adapter. H16 enables it only when the adapter's declared version, the SHA-256 of its input and output schemas, its scope and its permissions all equal the binding record. Any mismatch keeps the host implementation and logs `adapter_rejected`. Enterprise registry fields, including `Can_Veto`, are ignored.

**Dispatch rules.**

1. Look up the DVSS ID; unknown IDs and KA numbers raise `UnboundFunction`.
2. Check the binding level and the active profile; a disabled policy function returns `skipped` unless it has a required host fallback.
3. Validate input against the schema, run within the per-function time budget, validate output.
4. Append a `FunctionRecord` (ID, version, level, implementation, duration, outcome) to the run state.
5. Only K04 (gate), K11 (disclosure or abstention) and K12 (compliance veto) may produce a hold; any other function can only add evidence, objections or flags.

**Tier interaction.** The tier table decides which hooks fire, so it decides which functions run. P08 role token allocation runs only when more than one role is active; P11 falsification prompts default to tier 3; P02 Pareto options run only when two or more feasible options survive reconciliation.

**Kernel bindings.** Always on in every profile.

| ID | Function | Legacy KA | Hook (step / layer) | Implemented in |
| --- | --- | --- | --- | --- |
| DVSS-K01 | Schema and invariant validation | KA-004 | 1 / L1, and every function boundary | E3, `contracts/` |
| DVSS-K02 | Coordinate parsing | KA-011 | 2 / L1 | H4 |
| DVSS-K03 | Profile matching | KA-012 | 5 / L3 | H8 `profiles.py` |
| DVSS-K04 | Hard and CRC gate | KA-014 | 11 / L9 | H12, H14 |
| DVSS-K05 | Evidence acquisition and binding verification | KA-015 | 4, 9 / L2, L8 | H5, H12 |
| DVSS-K06 | Temporal filtering | KA-017 | 4, 8 / L2, L7 | H5, `l07_scope` |
| DVSS-K07 | Bounded expansion | KA-020 | 4 / L2 | H6 |
| DVSS-K08 | Source-age decay | KA-023 | 10 / L8 | H13 (freshness b) |
| DVSS-K09 | Two-retry limit | KA-026 | 11 / L9 | H1 |
| DVSS-K10 | Hybrid triage | KA-031 | 1 / L1 | H2, `tiers.py` |
| DVSS-K11 | Disclosure or abstention | KA-039 | 11–12 / L9–L10 | H14, E5 |
| DVSS-K12 | Unresolved compliance veto | KA-091 | 6, 11 / L5, L9 | H11, H14 |

**Policy bindings.** Profile defaults chosen for the middleware; any can be changed per deployment.

| ID | Function | Legacy KA | Hook (step / layer) | Strict | Advisory | Host fallback |
| --- | --- | --- | --- | --- | --- | --- |
| DVSS-P01 | Jurisdiction hierarchy | KA-018 | 8 / L7 | On | On | — |
| DVSS-P02 | Pareto options | KA-030 | 6 / L5 | On | On | — |
| DVSS-P03 | Session node synthesis | KA-040 | 3–4 / L2 | On | On | — |
| DVSS-P04 | Contradiction detection | KA-041 | 6 / L5 | On | On | — |
| DVSS-P05 | Quarantined promotion | KA-046 | Offline O2 only | Off | Off | — |
| DVSS-P06 | Ontology alignment | KA-048 | 7 / L6 | On | On | — |
| DVSS-P07 | Binding escalation | KA-059 | 5, 11 / L3, L9 | On | On | Required: H1 escalation |
| DVSS-P08 | Role token allocation | KA-060 | 5 / L3 | On | On | Required: equal split |
| DVSS-P09 | Cross-domain analogy | KA-067 | 5 / L4 | Off | On (hypotheses only) | — |
| DVSS-P10 | Profile tie-breaking | KA-072 | 5 / L3 | On | On | — |
| DVSS-P11 | Falsification prompts | KA-075 | 5 / L4 | Tier 3 | Tier 3 | — |
| DVSS-P12 | Fixed-baseline drift monitoring | KA-095 | 11 / L9 | On | On | Required: H14 CUSUM latch |
| DVSS-P13 | Safety policy | KA-098 | 1, 11 / L1, L9 | On | On | — |
| DVSS-P14 | Offline policy tuning | KA-100 | Offline O1 only | Off at runtime | Off at runtime | — |

**Ablation profiles.** `kernel_only` runs K01–K12 plus the three required host fallbacks (P07, P08, P12 behavior) and nothing else. `kernel_plus_policy` adds the strict profile's policy set. Both use the same model pins, tier table and calibration data, so any difference in outcomes is attributable to the policy functions.

## 7. Test and V&V Plan (DLE-STP)

Every requirement is verified by a named test before release. Components that decide whether an answer is released get the highest integrity level and the deepest verification. The plan follows ISO/IEC/IEEE 29119-3 for test documentation and IEEE 1012 for integrity levels.

### Integrity levels (IEEE 1012)

| Level | Meaning here | Components | Extra verification |
| --- | --- | --- | --- |
| 4 | A fault could release an unsupported or unauthorized answer, or forge evidence of review | Verifier, scorer, release controller, ledger, receipts, function registry (H11–H16), M3 NLI | 100% branch coverage, mutation score ≥ 90%, independent reviewer, property-based tests |
| 3 | A fault could skip a role, step or layer, or mis-tier a request | Orchestrator, router, tier table, Quad Persona engine, FROST layers (H1, H2, H8) | Branch coverage ≥ 90%, mutation score ≥ 80%, fixture coverage of every branch |
| 2 | A fault could break compatibility or lose evidence | Edge (E1–E5), evidence, graph, overlay, registry | Contract tests against official SDKs, line coverage ≥ 85% |
| 1 | A fault affects convenience only | Chat UI, admin views, offline reports | Line coverage ≥ 70%, smoke tests |

### Test levels

| Level | Scope | Where | Runs |
| --- | --- | --- | --- |
| Unit | One function or class, model and NLI faked | `tests/unit/` | Every push |
| Contract | JSON schemas, Gemini request and response shapes, receipt verification | `tests/contract/` | Every push |
| Engine | Step order, layer coverage, tier fan-out, retry, escalation, append-only state | `tests/engines/` | Every push |
| Gemini compatibility | Official Python and JS SDKs against the running middleware, fake model | `tests/gemini_compat/` | Every pull request |
| Fixture (§18 suite) | Warehouse and other worked cases end to end, frozen expected outcomes | `tests/fixtures/` | Every pull request, fake model; nightly, real Gemini |
| Security | Auth, loopback bind, egress allowlist under a deny-all network, injection probes | `tests/security/` | Every pull request |
| Performance | Overhead p95 per tier, keepalive timing, token and cost per tier | `tests/perf/` | Nightly |
| Evaluation | Calibration pilot and the §17 study | `offline/evaluate` | Phases 6 and 7, then each model pin change |

### Required engine tests

- Steps 1–12 run in order for every tier; no step is skipped silently.
- Each FROST layer writes exactly one record per run, and no attempt overwrites an earlier one.
- Tier 1 calls only the Scholar; tier 2 calls Scholar and Practitioner; tier 3 calls the roles its triggers require.
- A binding claim at tier 1 escalates once and only once.
- A retry happens only with a fixable gap and an authorized source; never more than 2; hops never above 4.
- A tool call parks the run and resumes at step 4 with the response as app-tool evidence.
- Role agreement alone never changes u.
- Model call counts never exceed the tier budget (FR-TIER-04).

### Required function-binding tests

- Removing any kernel function's registration makes startup fail with its DVSS ID named.
- Calling `invoke("KA-015")` or any catalog entry raises `UnboundFunction`.
- An adapter whose schema hash, version, scope or permissions differ from the binding record is rejected and the host implementation runs.
- A registry entry marked `Can_Veto: Yes` (for example KA-024) cannot produce a hold.
- With P07, P08 or P12 disabled but declared, the host fallback runs and the receipt records `implementation: host_fallback`.
- Only K04, K11 and K12 can set a hold; every other function's attempt to do so is rejected.
- Each receipt lists every function invoked, and the list matches the run state.
- `kernel_only` and `kernel_plus_policy` produce identical behavior on the mandatory-host fixtures.

### Statistical evaluation

The calibration pilot grades about 100 queries and reports coverage and loss at α = .05. The full study uses 150 held-out test queries, enough to check α = .05 but not .01, plus a separate adversarial challenge set of 50 development and 100 held-out items. Held-out items are never used for tuning; their hashes are registered before the study runs.

### Entry and exit criteria

- **Entry to a phase:** previous phase gate passed; requirement IDs for the phase accepted.
- **Exit from a phase:** its exit-gate test passes; all level 3–4 tests for touched components pass; no open defect of severity 1 or 2.
- **Release:** every requirement in the RTM has a passing test; Gemini compatibility suite passes against the current SDK versions on Windows and Linux.

### Defect severity

| Severity | Definition | Release impact |
| --- | --- | --- |
| 1 | Unsupported or unauthorized answer can be released, or a receipt can be forged | Blocks release |
| 2 | A step, role or layer can be skipped; egress outside the allowlist; SDK client breaks | Blocks release |
| 3 | Wrong metadata, cost or latency over target | Release with a documented known issue |
| 4 | Cosmetic or UI only | Fix when convenient |

## 8. Secure Development and Threat Model (DLE-SEC)

The middleware's attack surface is its local API, the content it ingests (evidence, tool results, model output) and its one outbound connection. Development follows NIST SSDF (SP 800-218, with the 800-218A generative AI profile), and the API is built to OWASP ASVS 5.0 Level 2.

### Trust boundaries

1. **Client → edge.** Untrusted callers, even on localhost.
2. **Content → host.** Evidence passages, `functionResponse` payloads and Google built-in tool results are untrusted data, never instructions.
3. **Host ↔ model.** Model output is untrusted until the verifier checks it.
4. **Host → Gemini API.** The only egress; carries prompt content and nothing else.
5. **Admin → config and keys.** Privileged; loopback only.

### Threats and controls

| Threat | Class | Control | Requirement |
| --- | --- | --- | --- |
| Unauthenticated local caller drives the API | STRIDE spoofing | Key on every request; loopback bind by default | NFR-SEC-01, -02 |
| Prompt injection in evidence or tool results steers a role | OWASP LLM prompt injection | Content marked as data in packets; roles see sealed role-filtered packets; verifier extracts claims independently and checks them with local NLI | FR-QP-05, FR-VER-01 |
| Model invents a citation or claim | OWASP LLM misinformation | Hard gate H, entailment scoring, conformal cutoff; holds instead of release | FR-REL-01–-03 |
| Tool calls cause harmful actions | OWASP LLM excessive agency | Middleware never executes tools; client executes; consequential flag adds Regulator review | FR-TOOL-01, -05 |
| Tampering with ledger, receipts or audit trail | STRIDE tampering, repudiation | Append-only stores; Ed25519 signatures; anchored Merkle roots; verify on read | FR-VER-03, FR-RCPT-01–-03 |
| Data leaves by a second path | Information disclosure | Single egress client with allowlist; CI test under deny-all network | NFR-SEC-03 |
| Prompt or response content in logs | Information disclosure | Content excluded from logs and diagnostics by default | NFR-PRIV-01 |
| Cost or call blow-up from crafted requests | OWASP LLM unbounded consumption | Per-tier call budget, retry and hop caps, rate and budget limits returning 429 | FR-TIER-04, FR-WF-03 |
| Poisoned session overlay affects later turns | OWASP LLM vector and embedding weakness | Session hypotheses tagged, never promoted to facts; overlay scoped by session hash and tenant | FR-SES-01, FR-FL-03 |
| Compromised dependency or model file | Supply chain | Pinned lockfile, hash-checked NLI model, SBOM, SCA in CI, signed releases | §10 |
| Gemini key theft | Information disclosure | OS-protected secret store; never returned to clients or logged | NFR-SEC-04 |

### SSDF practice mapping

| SSDF group | What the project does | Evidence |
| --- | --- | --- |
| PO · Prepare the organization | Roles and reviews in DLE-SDP; security requirements in DLE-SRS | This set, CI configuration |
| PS · Protect the software | Protected `main`, signed commits, signed releases, provenance attestations | Repo settings, release artifacts |
| PW · Produce well-secured software | Threat model above; ADRs; code review; SAST, SCA, secret scan; security tests | CI logs, `tests/security/` |
| RV · Respond to vulnerabilities | Coordinated disclosure policy (ISO/IEC 29147, 30111), `security.txt`, triage within 5 working days, fix timelines by severity | `SECURITY.md`, advisories |

### Secure coding rules

- Validate every inbound body against its schema before use; reject unknown fields on DLE endpoints.
- Never build prompts by concatenating untrusted text into instruction slots; use the packet builder.
- No `eval`, `exec`, `pickle` or shell calls on content.
- All outbound HTTP through the egress client; a CI rule fails any other network import.
- Secrets only through the secret store; a CI rule fails hard-coded keys.

## 9. AI Management and Risk (DLE-AIM)

The middleware's claims about its own answers are measured, not asserted: release depends on a calibrated cutoff, drift is monitored, and every number published about the system comes from the evaluation harness. The controls follow ISO/IEC 42001, with risk work under ISO/IEC 23894 and the NIST AI RMF functions (Govern, Map, Measure, Manage) and its Generative AI Profile (AI 600-1).

### Intended use and limits

- **Intended use.** Grounded, reviewable answers to questions about documents and records the operator registers, where a held answer is better than an unsupported one.
- **Not intended for.** Fully automated consequential decisions without human review; questions whose sources are not registered; any use outside the US.
- **Known limits.** The four roles share one base model and its blind spots, so agreement is not independent evidence. Entailment scoring can miss multi-hop reasoning errors. Calibration holds only for the model pin and query mix it was measured on.

### Risk register

| Risk | NIST AI RMF area | Control | Owner |
| --- | --- | --- | --- |
| Confabulated claim released | Measure, Manage | Hard gate, entailment, conformal cutoff, hold on doubt | AI risk owner |
| Silent model change at Google | Manage | `modelVersion` latch; any change re-runs calibration before strict mode resumes | AI risk owner |
| Calibration decays with query drift | Measure | CUSUM latch on fixed baseline forces hold; recalibration job | AI risk owner |
| Correlated persona error | Map | No agreement bonus; blinded assurance roles; stated limit in system card | Architect |
| Over-reliance on released answers | Govern | Release mode in every response; receipts link claims to sources; human-oversight guidance in docs | Tech lead |
| Stale or out-of-scope authority used | Map, Measure | Layer 7 scope checks; source revisions in receipts | Tech lead |

### Lifecycle controls

| ISO/IEC 42001 area | Implementation |
| --- | --- |
| AI policy and roles | DLE-SDP roles; AI risk owner approves model pins and thresholds |
| Impact assessment | Per deployment profile, before first production use and on intended-use change |
| Data for AI systems | Calibration and evaluation sets versioned, hashed, held-out items never used for tuning |
| Documentation for users | System card generated from config and evaluation results each release |
| Monitoring | Drift latch, hold rate, release rate, cost per tier in `ops.db` |
| Change control | Any change to model pin, NLI model, u weights, cutoff or tier table is a major configuration change needing re-evaluation |

### System card contents

Published with each release: intended use and limits, model pins with versions, tier table, release profiles and α, latest calibration coverage and loss, challenge-set results, known failure modes, and the human-oversight instructions for operators.

## 10. Configuration, Release and Operations (DLE-CMR)

Every release is built hermetically from a tagged commit, signed, shipped with an SBOM and provenance, and tied to the exact configuration whose digest appears in its receipts.

### Configuration items

| Item | Location | Versioned by |
| --- | --- | --- |
| Source code | Git, protected `main` | Commit SHA, release tag |
| Contracts and schemas | `contracts/` | Semantic version in each schema |
| Policy configuration | `config/` (profiles, tier table, persona store, pins, flags, source policy) | Policy digest |
| Registries | `registry.db` releases from O2 | Registry release ID |
| Calibration artifacts | `calibration/` | Model pin plus dataset hash |
| NLI model file | `models/nli/` | SHA-256 checked at load |
| Documentation set | This doc and `docs/` | Document version table |

### Branching and versioning

- Trunk-based: short-lived branches, pull requests into `main`, no direct pushes.
- Releases use semantic versioning. A change to the wire contract, receipt schema or release rule is a major version.
- Each release has a changelog entry listing requirement IDs added or changed and configuration changes.

### Release checklist

- [ ] All tests in DLE-STP pass on Windows and Linux; RTM has no untested requirement.
- [ ] SAST, SCA and secret scan clean, or each finding triaged and recorded.
- [ ] CycloneDX 1.6 SBOM generated and attached.
- [ ] Build provenance attestation generated (SLSA v1.0, target Build Level 3).
- [ ] Installer and packages signed (Authenticode for Windows; Sigstore for Python and container artifacts).
- [ ] Egress test passes under a deny-all network with only the Gemini endpoint allowed.
- [ ] System card regenerated; calibration current for the shipped model pin.
- [ ] Release readiness review approved by the release manager.

### Deployment

| Item | Default |
| --- | --- |
| Process | One FastAPI service under a service account without admin rights |
| Bind | `127.0.0.1:8740`; LAN bind is an explicit opt-in with TLS |
| Outbound | `generativelanguage.googleapis.com:443` only |
| Data directory | Per-machine directory with OS ACLs limited to the service account |
| Chat UI | Static files served by the same process, or `npm run dev` in development |

A hardening guide ships with each release: service account rights, firewall rules for the single outbound host, key storage scope and uninstall steps that dispose of stores and keys.

### Operations

- **Health.** `GET /healthz` reports store access, model reachability, NLI load and drift latch state.
- **Metrics.** Release, hold and advisory rates by tier; p50 and p95 latency per step; tokens and cost per tier.
- **Alerts.** Drift latch tripped; hold rate up 2× on its 7-day baseline; Gemini error rate over 5%; `modelVersion` changed.
- **Backups.** Daily copy of `registry.db`, `receipts.db` and `keys/` to an operator-chosen location; restore tested each release.
- **Key rotation.** Signing keys rotate yearly or on suspicion; old public keys stay published so past receipts still verify.
- **Support.** Diagnostic bundles exclude content by default. A security update support period is declared per major version.

## 11. Requirements Traceability Matrix (DLE-RTM)

Each requirement traces back to its white paper section and forward to its components, tests and build phase. The rows below are the baseline at group level. The per-requirement matrix is generated in CI from `@verifies("FR-…")` markers on tests, and the build fails if any SRS ID has no test.

| Requirements | Paper source | Components | Tests | Phase |
| --- | --- | --- | --- | --- |
| FR-API-01–03 | Middleware design | E1, E3, M1 | T-COMPAT-API-01–10 | 1 |
| FR-API-04–06 | §16c–§16d receipts, release modes | E5, H14 | T-CONTRACT-RESP-01–06 | 2 |
| FR-API-07 | ADR-004 | E5 | T-COMPAT-STREAM-01–04 | 1 |
| FR-API-08 | §16d | E6, H15 | T-CONTRACT-RCPT-01–04 | 2 |
| FR-SES-01–03 | ADR-003 | E2, H15 | T-UNIT-SES-01–08 | 1 |
| FR-TOOL-01–05 | ADR-002 | E4, H5, H8 | T-COMPAT-TOOL-01–08, T-ENG-TOOL-01–04 | 1, 4 |
| FR-WF-01–07 | §12 refinement workflow | H1 | T-ENG-WF-01–14 | 4 |
| FR-FL-01–07 | §11 FROST stack | `frost/` l01–l10 | T-ENG-FL-01–12 | 2–4 |
| FR-QP-01–08 | §07–§10 personas | H8 | T-ENG-QP-01–16, §18 fixtures | 4 |
| FR-TIER-01–04 | Routing, S\_eff | H2, `tiers.py` | T-UNIT-TIER-01–10, T-ENG-TIER-01–06 | 5 |
| FR-FN-01–09 | Function bindings (DVSS-K01–K12, P01–P14), ADR-009, ADR-010 | H16, `functions/` | T-ENG-FN-01–12, T-EVAL-ABL-01 | 2–5, 7 |
| FR-VER-01–03 | Verification, ledger | H10–H12, M3 | T-UNIT-VER-01–12, mutation suite | 2, 4 |
| FR-REL-01–04 | Gate H, u, cutoff, CUSUM | H13, H14, O1 | T-UNIT-REL-01–14, T-EVAL-CAL-01 | 2, 6 |
| FR-RCPT-01–03 | Receipts, anchoring profiles | H15 | T-CONTRACT-RCPT-05–12 | 2 |
| FR-UI-01–02 | Test interface | C1 | T-UI-01–06 | 1, 5 |
| NFR-PERF-01–02 | — | All runtime | T-PERF-01–04 | 1, 5 |
| NFR-REL-01–02 | — | M1, H14 | T-UNIT-MODEL-01–06 | 1 |
| NFR-SEC-01–04 | Product security | E1, M1, `keys/` | T-SEC-01–12 | 1 |
| NFR-PRIV-01–02 | Retention policy | All stores | T-SEC-13–18 | 2 |
| NFR-MAINT-01, NFR-PORT-01 | — | All | Inspection, Windows and Linux CI | All |
| NFR-OBS-01, NFR-COST-01 | Cost model | M1, `ops.db` | T-PERF-05–08 | 1 |
| NFR-ACC-01 | — | C1 | T-UI-A11Y-01–04 | 5 |

## 12. User Personas and Stories (DLE-USR)

Five personas use the middleware, and every user story names one of them, states its value, and traces to SRS requirements so a story is done only when those requirements' tests pass. Priorities use MoSCoW (Must, Should, Could, Won't this release).

### Personas

| Persona | Who | Goal | Main surface |
| --- | --- | --- | --- |
| P1 App developer | Builds a product on the Gemini SDK | Swap in governed answers without rewriting code | API |
| P2 Tester | Checks answer quality before rollout | See why an answer was released or held | Chat test UI |
| P3 Reviewer or auditor | Compliance, legal or model-risk staff | Prove a past answer was grounded and unaltered | Receipt viewer, `/v1/receipts` |
| P4 Administrator | Runs the install for the operator | Keep sources, keys, calibration and drift healthy | Admin UI, `/admin` |
| P5 End user | Uses the app built by P1 | Get a trustworthy answer, or a clear reason there isn't one | The P1 app (indirect) |

### Epic E1 · Drop-in Gemini compatibility

| ID | Story | Acceptance criteria | Priority | Traces to |
| --- | --- | --- | --- | --- |
| US-01 | As P1, I want to change only the base URL and key, so that my existing Gemini app runs unchanged. | Given a working google-genai app, when its base URL points at the middleware, then text, streaming and multi-turn calls succeed with no code change. | Must | FR-API-01–03 |
| US-02 | As P1, I want my tools and functions to work as before, so that my app's features keep working. | Given function declarations, when Gemini calls one, then my app receives the `functionCall` unchanged and its `functionResponse` is accepted. | Must | FR-TOOL-01–03 |
| US-03 | As P1, I want to know if an answer was held, so that my app can show the right message. | Given a held answer, then the response has `finishReason` STOP and `X-DLE-Release-Mode: held`. | Must | FR-API-05–06 |
| US-04 | As P1, I want citations in a standard field, so that I can render sources without parsing text. | Given a released answer, then `groundingMetadata` links each claim to a passage. | Should | FR-API-04 |

### Epic E2 · Understanding a run

| ID | Story | Acceptance criteria | Priority | Traces to |
| --- | --- | --- | --- | --- |
| US-05 | As P2, I want to see the tier and which personas ran, so that I can judge whether depth matched the question. | Given any run, the run panel shows tier, S\_eff inputs and active roles. | Must | FR-UI-02, FR-TIER-01 |
| US-06 | As P2, I want to see the 12 steps with retries and escalation marked, so that I can spot where a run went back. | Given a run with a retry, the step timeline shows steps 4–11 twice and labels the retry reason. | Must | FR-WF-01–05 |
| US-07 | As P2, I want each claim shown with its support score and source, so that I can find weak claims fast. | Given a run, the claims table lists each claim, its z score, binding flag and source link, sorted weakest first. | Should | FR-VER-01, FR-FL-07 |
| US-08 | As P2, I want to read each persona's findings and objections, so that I can see disagreement. | Given a tier 3 run, each role's artifact is viewable, with open objections highlighted. | Should | FR-QP-07, FR-VER-02 |

### Epic E3 · Proof and audit

| ID | Story | Acceptance criteria | Priority | Traces to |
| --- | --- | --- | --- | --- |
| US-09 | As P3, I want to verify a receipt offline, so that I don't have to trust the server. | Given a receipt and the published public key, the bundled verifier reports valid or names the failing check. | Must | FR-RCPT-01–03 |
| US-10 | As P3, I want to replay which sources and policy produced an answer, so that I can review it months later. | Given a receipt ID, I can see the policy digest, model version, source revisions and claim outcomes. | Must | FR-RCPT-03 |
| US-11 | As P3, I want an export of receipts for a date range, so that I can hand them to an examiner. | Given a range, the admin export produces a signed bundle with a Merkle proof per receipt. | Could | FR-RCPT-02 |

### Epic E4 · Operating the install

| ID | Story | Acceptance criteria | Priority | Traces to |
| --- | --- | --- | --- | --- |
| US-12 | As P4, I want to register a source and its authority class, so that roles can cite it. | Given a new document, after registration it appears in `/v1/sources` and in retrieval results. | Must | FR-API-08 |
| US-13 | As P4, I want an alert and a hold when drift trips, so that stale calibration never releases answers. | Given the CUSUM latch trips, strict releases stop, the health page shows the latch, and reset needs an admin action. | Must | FR-REL-04 |
| US-14 | As P4, I want to flag a function as consequential, so that claims relying on it get Regulator review. | Given a flagged function, any run that uses its result activates the Regulator. | Should | FR-TOOL-05 |
| US-15 | As P4, I want to see cost per tier, so that I can budget usage. | Given a week of traffic, the metrics page shows tokens and dollars per tier. | Should | NFR-COST-01 |

### Epic E5 · End-user trust

| ID | Story | Acceptance criteria | Priority | Traces to |
| --- | --- | --- | --- | --- |
| US-16 | As P5, I want a plain reason when no answer is given, so that I know what to do next. | Given a hold, the hold notice names the missing evidence or authority in one sentence. | Must | FR-API-06 |
| US-17 | As P5, I want to know an answer is advisory, so that I don't treat it as verified. | Given `released_advisory`, the notice text marks it advisory. | Should | FR-REL-03 |

## 13. User Journeys (DLE-UXJ)

Four journeys cover the moments that decide whether the product is trusted. Each maps the stages a persona goes through, what could go wrong, and the design response that the stories and components must deliver.

### J1 · Developer integrates an existing Gemini app (P1)

| Stage | Doing | Touchpoint | Risk | Design response | Stories |
| --- | --- | --- | --- | --- | --- |
| 1 Discover | Reads the quick start | README, ICD | Fears a rewrite | Quick start shows the two-line base URL change first | US-01 |
| 2 Connect | Sets base URL and key, runs a test call | SDK, `/v1beta/models` | Wrong key or bind address | Clear 401 message; health page shows bind and model reachability | US-01 |
| 3 Use tools | Runs a function-calling flow | Tool bridge | Thinks tools are blocked | Tools pass through unchanged; doc states this up front | US-02 |
| 4 Handle outcomes | Meets a held answer | `X-DLE-Release-Mode`, hold notice | Shows users a blank reply | Sample code for released, advisory and held cases | US-03, US-16 |
| 5 Show sources | Renders citations | `groundingMetadata` | Parses text by hand | Standard Gemini field plus a rendering snippet | US-04 |

### J2 · Tester reviews why an answer was released or held (P2)

| Stage | Doing | Touchpoint | Risk | Design response | Stories |
| --- | --- | --- | --- | --- | --- |
| 1 Ask | Sends a question in the chat UI | Chat composer, model picker | Picks the wrong profile | Strict and advisory shown as separate models with labels | US-05 |
| 2 Read result | Sees the answer and its release badge | Message bubble, release badge | Misses that it was advisory | Badge colour and text both state the mode | US-17 |
| 3 Open the run | Opens the run panel | Tier card, persona chips, step timeline | Overwhelmed by detail | Summary first (tier, roles, mode); details expand | US-05, US-06 |
| 4 Find weak spots | Sorts claims, opens objections | Claims table, persona drawer | Can't tell which claim caused the hold | Weakest claims first; blocking objection pinned at top | US-07, US-08 |
| 5 Report | Copies the receipt ID into a bug | Receipt chip | Loses context | Receipt link reopens the exact run | US-10 |

### J3 · Auditor verifies a past answer (P3)

| Stage | Doing | Touchpoint | Risk | Design response | Stories |
| --- | --- | --- | --- | --- | --- |
| 1 Receive | Gets a receipt ID from a case file | Receipt viewer | Doesn't know where to start | Single field: paste ID or upload file | US-10 |
| 2 Verify | Runs signature and anchor checks | Verifier, offline CLI | Has to trust the server | Offline CLI with published public keys | US-09 |
| 3 Inspect | Reads sources, policy, model version | Receipt detail view | Sources since changed | Shows source revision as cited, not latest | US-10 |
| 4 Export | Bundles receipts for an examiner | Admin export | Bundle not self-proving | Signed bundle with per-receipt Merkle proofs | US-11 |

### J4 · Administrator handles a drift alert (P4)

| Stage | Doing | Touchpoint | Risk | Design response | Stories |
| --- | --- | --- | --- | --- | --- |
| 1 Alerted | Sees drift latch tripped | Health page, alert | Ignores it | Strict releases stop until reset; banner on every admin page | US-13 |
| 2 Diagnose | Checks model version, hold rate, query mix | Metrics page, model registry | Blames the wrong cause | Timeline overlays `modelVersion` changes on hold rate | US-13, US-15 |
| 3 Recalibrate | Runs the calibration job on fresh graded data | Offline O1, admin upload | Reuses held-out data | Job refuses datasets whose hashes match the held-out registry | US-13 |
| 4 Reset | Loads the new artifact, resets the latch | Admin action with confirmation | Accidental reset | Two-step confirm, logged with admin identity | US-13 |

## 14. Style Guide (DLE-STY)

One rule runs through the UI: the release mode is always stated in words and never by colour alone, and a hold looks calm, not like an error. Design tokens live in `ui/src/tokens.css` and are the only source of colour, type and spacing; components never hard-code values. The second half of this section is the code style guide.

### Colour tokens

| Token | Use | Light | Dark |
| --- | --- | --- | --- |
| `--dle-bg` | Page background | #FFFFFF | #0D1117 |
| `--dle-surface` | Cards, panels | #F6F8FA | #161B22 |
| `--dle-border` | Dividers, outlines | #D0D7DE | #30363D |
| `--dle-text` | Body text | #1F2328 | #E6EDF3 |
| `--dle-text-muted` | Secondary text | #57606A | #8B949E |
| `--dle-accent` | Links, focus ring, primary button | #0969DA | #58A6FF |
| `--dle-released` | Released badge, supported claims | #1A7F37 | #3FB950 |
| `--dle-advisory` | Advisory badge, weak support | #9A6700 | #D29922 |
| `--dle-held` | Held badge, open objections | #57606A | #8B949E |
| `--dle-error` | System errors only (401, 500, failed verify) | #CF222E | #F85149 |

All text tokens meet WCAG 2.2 AA contrast (4.5:1) on `--dle-bg` and `--dle-surface` in both themes; CI checks this with the token file.

### Type, spacing and shape

| Token group | Values |
| --- | --- |
| Font families | UI: system sans stack; code and IDs: system monospace stack |
| Type scale | 12 / 14 / 16 / 20 / 24 px; body 14 px, line height 1.5 |
| Weights | 400 body, 600 headings and labels |
| Spacing | 4 px base: 4, 8, 12, 16, 24, 32 |
| Radius | 4 px controls, 8 px cards and panels |
| Elevation | One shadow level for drawers and menus; none on cards |
| Motion | 150 ms ease-out; off when `prefers-reduced-motion` is set |

### Status language

| Mode | Badge text | Icon | Notice wording pattern |
| --- | --- | --- | --- |
| Released | Verified | Check | "Verified against N sources." |
| Advisory | Advisory | Info | "Advisory: not fully verified. See flagged claims." |
| Held | Held for review | Pause | "Held: \<missing evidence or authority>. \<what would resolve it>." |
| Pass-through | Tool call | Arrow | "Waiting for your app to run \<function>." |
| Error | Error | Alert | "\<What failed>. \<What to do>." |

### Writing for the UI

- Plain words, sentence case, no exclamation marks.
- Say what happened, then what to do: "Key not accepted. Check the middleware API key in settings."
- Name things as the docs do: tier, persona, step, layer, receipt. Show IDs (US-, FR-, receipt IDs) in monospace.
- Numbers carry units; scores show two decimals.

### Accessibility rules

- WCAG 2.2 AA throughout; every interactive element reachable and usable by keyboard, with a visible 2 px focus ring in `--dle-accent`.
- Status is conveyed by text plus icon, never colour alone.
- Live regions announce release mode when a streamed answer completes.
- Tables have header cells and captions; the step timeline is a list with text labels, not only a drawing.
- Touch targets at least 24 × 24 px.

### Code style guide

| Area | Rule | Enforced by |
| --- | --- | --- |
| Python formatting | PEP 8 via `ruff format`; line length 100 | Pre-commit, CI |
| Python linting | `ruff` rule sets E, F, I, B, UP, S, ANN; zero warnings | CI |
| Python types | Full annotations; `mypy --strict` on `dle/` | CI |
| Docstrings | Google style on every public function, naming the requirement IDs it implements | Review, `ruff` D rules |
| Naming | Modules `snake_case`; classes `PascalCase`; FROST modules `lNN_name.py`; workflow steps `sNN_name.py` | Review |
| Errors | Raise typed exceptions from `dle.errors`; never return a default on failure | Review, Semgrep rule |
| TypeScript | `strict` mode, ESLint and Prettier; components in `PascalCase.tsx` with a sibling `.stories.tsx` | CI |
| Commits | Conventional Commits (`feat:`, `fix:`, `docs:`), with requirement or story IDs in the body | Commit hook |

## 15. Storybook Component Catalog (DLE-SB)

Every UI component in the chat test UI and admin views has Storybook stories for each state a user can meet. Each story names the user stories it serves, so the catalog is also a visual test of the journeys. Stories are written in Component Story Format 3, use mocked middleware responses, and run accessibility and interaction checks in CI.

### Conventions

- One `ComponentName.stories.tsx` beside each component; title path `DLE/<Area>/<Component>`.
- Story names are states, not variants: `Released`, `Advisory`, `Held`, `Loading`, `Error`, `Empty`.
- Data comes from `ui/src/fixtures/`, generated from the §18 fixture runs and real signed receipts, never hand-typed.
- Network calls are mocked with Mock Service Worker handlers that return Gemini-shaped bodies and `X-DLE-*` headers.
- Each story's `parameters.dle.stories` lists its user story IDs; a CI script fails if a Must story (§12) has no Storybook story.
- Addons: accessibility (axe), interactions (`play` functions), viewport, light and dark theme switch.
- Visual snapshots run on every pull request; a changed snapshot needs reviewer approval.

### Catalog

| Component | Area | Stories (states) | User stories |
| --- | --- | --- | --- |
| `ChatComposer` | Chat | Empty, Typing, Sending, Disabled, With model picker (strict and advisory) | US-05 |
| `MessageBubble` | Chat | Released, Advisory, Held, Streaming with keepalive, Tool call waiting, Error | US-03, US-16, US-17 |
| `ReleaseBadge` | Shared | Verified, Advisory, Held for review, Tool call, Error, each in light and dark | US-03, US-17 |
| `CitationList` | Chat | Several sources, One source, Stale revision warning, None | US-04 |
| `RunSummaryCard` | Run panel | Tier 1, Tier 2, Tier 3, Escalated tier 1 to 2 | US-05 |
| `PersonaChips` | Run panel | Scholar only, Scholar and Practitioner, All four, Blinded mode | US-05, US-08 |
| `StepTimeline` | Run panel | Straight run, One retry, Two retries, Escalation, Parked on tool call | US-06 |
| `ClaimsTable` | Run panel | All supported, Weak claims first, Binding claim unsupported, Empty | US-07 |
| `PersonaDrawer` | Run panel | Findings only, Open blocking objection, Objection closed by verifier | US-08 |
| `ReceiptChip` | Shared | Sealed, Pending anchor, Copy-to-clipboard confirmation | US-10 |
| `ReceiptViewer` | Audit | Valid, Signature fails, Anchor missing, Source revision since changed | US-09, US-10 |
| `ExportDialog` | Audit | Date range picker, Building bundle, Done, Failure | US-11 |
| `SourceRegistryTable` | Admin | List, Add source form, Validation error, Authority class edit | US-12 |
| `DriftBanner` | Admin | Healthy (hidden), Tripped, Reset confirmation step 1, Step 2 | US-13 |
| `FunctionFlagsEditor` | Admin | No flags, Consequential flag set, Save error | US-14 |
| `CostByTierChart` | Admin | One week, No data, Tier 3 spike | US-15 |
| `HealthPanel` | Admin | All green, Model unreachable, NLI not loaded, Drift latch on | US-13 |

### Example story

```tsx
// ui/src/components/MessageBubble.stories.tsx
import type { Meta, StoryObj } from "@storybook/react";
import { expect, within } from "@storybook/test";
import { MessageBubble } from "./MessageBubble";
import { releasedRun, heldRun } from "../fixtures/runs";

const meta = {
  title: "DLE/Chat/MessageBubble",
  component: MessageBubble,
  parameters: { dle: { stories: ["US-03", "US-16", "US-17"] } },
} satisfies Meta<typeof MessageBubble>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Released: Story = { args: { run: releasedRun } };

export const Held: Story = {
  args: { run: heldRun },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Held for review")).toBeVisible();      // text, not colour alone
    await expect(c.getByRole("status")).toHaveTextContent(/Held:/);  // live region announces mode
  },
};
```

### Where it runs

| Command | Purpose |
| --- | --- |
| `npm run storybook` | Local catalog on port 6006 |
| `npm run test-storybook` | Interaction and axe checks for every story, in CI |
| `npm run build-storybook` | Static catalog published with each release as `storybook-static/` |

## 16. Glossary

| Term | Meaning |
| --- | --- |
| 13-axis address | The coordinate that places a question in the registry: pillar, sector, crosswalk and role axes, among others |
| Advisory profile | Release profile that returns answers failing the cutoff with `released_advisory` instead of holding them |
| Binding claim (B) | A claim that states an obligation, authorization or prohibition; forces Regulator review |
| Conformal risk control | Method that sets the release cutoff on graded data so expected loss stays at or below α |
| CUSUM drift latch | Cumulative-sum monitor against a fixed baseline; once tripped, it holds releases until reset |
| DVSS | The 13-axis reference design described in the white paper |
| Escalation | One-time jump to a higher tier when a binding claim appears without the Regulator |
| FROST | The 10-layer simulation stack; each layer owns one kind of work |
| Hard gate (H) | Pass/fail check before scoring: no open blocking objection and no unsupported binding claim |
| History hash | Session ID computed from the JCS-canonical conversation history |
| JCS | JSON Canonicalization Scheme (RFC 8785), used before hashing and signing |
| MDKF | Multi-Domain Knowledge Framework; source of the seven-field persona profiles |
| Objection ledger | Append-only record of objections; only the verifier closes one |
| PPR | Personalized PageRank; retrieval by diffusion from anchors over the spine |
| Quad Persona engine | Selects and runs the Scholar, Practitioner, Regulator and Harmonizer roles |
| Receipt | Signed, anchored record binding a response to its evidence, attempts and policy |
| Refinement workflow | The 12 ordered steps every governed request runs, with its retry loop |
| S\_eff | Effective routing score, max(S, 3B, 6Z); sets the tier |
| Strict profile | Release profile that holds anything failing the gate or cutoff |
| Tier | Depth of processing (1–3) chosen from S\_eff; sets roles, hops, retries and call budget |
| u | Terminal score combining support, binding-claim strength and freshness |
| Z | Risk-check flag that forces tier 3 |
| Adapter gate | H16 check that enables an external implementation only when version, schema hashes, scope and permissions match the binding record |
| Binding level | Kernel (always on), policy (profile-enabled) or catalog (inventory only, never runs) |
| Catalog-only | A KA slot recorded for traceability with no execution permission in the 13-axis design |
| DVSS-K01–K12 | The 12 kernel functions the host must implement; the design's load-bearing invariants |
| DVSS-P01–P14 | The 14 policy functions a release profile may enable |
| H16 Function registry | Host component that dispatches bound functions by DVSS ID and records each call |
