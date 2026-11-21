# Function specification catalog (G6)

**Document ID:** DLE-FNS-001 · **Version:** 0.1.0 · **Status:** Draft · **Owner:** Architect · **Date:** 2026-11-20

One specification per bound function. Binding records (hooks, permissions, versions) are in `config/functions.yaml`; this file defines behavior. Every function: validates input and output against `contracts/functions/<id>.{in,out}.json` (K01), runs within a 750 ms host budget unless stated, appends a `FunctionRecord`, and on internal error returns `outcome: error`, which fails the run closed (AGENTS.md rule 11). Only K04, K11 and K12 may return `outcome: hold`.

Formulas cite the white paper. Constants marked *dev-set* are fixed on development data and frozen before calibration.

---

## Kernel functions

### DVSS-K01 · Schema and invariant validation
- **Hook:** Step 1 (request), and at every function boundary.
- **Input:** any payload plus the schema ID it claims.
- **Behavior:** JSON Schema 2020-12 validation; invariants: IDs unique within a run, every passage ID cited exists in the packet, timestamps UTC, intervals half-open.
- **Output:** `{valid, errors[]}`.
- **Failure:** invalid client request → HTTP 400; invalid internal payload → `error`, run held by K11.
- **Tests:** T-UNIT-FN-K01-01–08 (malformed, unknown passage, non-UTC time, overlapping IDs).

### DVSS-K02 · Coordinate parsing
- **Hook:** Step 2.
- **Input:** proposed anchors (from intake and model), registry release ID.
- **Behavior:** parse canonical strings `[TAG:axis.n.n…]`; validate against the registry; assign each of Axes 2–11 a slot state from `slot_states`: `specified`, `empty`, `unknown`, `not_applicable`; Axis 12 uses `jurisdiction_state`: `specified`, `unknown`, `unscoped`; Axes 1 and 13 must carry entries (paper §03, contracts/coordinate.schema.json). Model-proposed labels stay `candidate` until validated (paper §11 L1). A record that omits a slot's state fails validation, so a missing value never waives a requirement: `unknown` on a slot a binding claim depends on opens a dependency.
- **Output:** 13-axis coordinate (contracts/coordinate.schema.json), uncertain matches, active-axis mask.
- **Failure:** unparseable anchor → recorded as uncertain match, not an error.
- **Tests:** coordinate fixtures from the paper (§04b), alias-pair handling.

### DVSS-K03 · Profile matching
- **Hook:** Step 5 (L3).
- **Input:** active roles, profile store, query coordinate.
- **Behavior:** filter by mandatory qualifications; score M = 0.25E + 0.45C + 0.30X with E = min(1, degree/required) · exp(−γ·d), C = fraction of required credentials, X = min(1, years/required) · sector-lineage match; omit inapplicable terms and renormalize; missing evidence for an applicable term scores 0 (paper §08). Tie-break by P10 if enabled, else by profile ID.
- **Output:** one profile ID per role with its M and feature values.
- **Failure:** no eligible profile → generic role profile flagged `low_fit`; recorded as objection by the Harmonizer at Tier 3.
- **Tests:** worked example E = 1, C = 0.5, X = 0.8 → M = 0.715.

### DVSS-K04 · Hard and CRC gate
- **Hook:** Step 11, once, on the frozen terminal candidate.
- **Input:** terminal candidate, claim records, ledger, calibration artifact, drift state.
- **Behavior:** H = valid schema and scope ∧ non-empty assessable claim set ∧ authority checks complete for every binding claim ∧ zero unresolved blocking objections. Score u = 0.40(1 − min_{j∈J} z_j) + 0.20(1 − mean_i z_i) + 0.25(1 − min_{j∈J} b_j) + 0.15d (F-SCORE-01). Empty claim set → u = 1. Compare u to the single approved cutoff t̂ (conformal risk control, paper §16b). Applies the ordered decision table of paper §16c.
- **Output:** `{H, u, cutoff, decision}` with decision in `block`, `withhold_drift`, `abstain_or_explain`, `release`.
- **Failure:** missing calibration artifact → `block`.
- **Tests:** paper worked score u = 0.0547; d = 0.5 → 0.1297; cutoff .080 vs .048.

### DVSS-K05 · Evidence acquisition and binding verification
- **Hook:** Step 4 (hydrate) and Step 9 (authority check per binding claim).
- **Input:** query scope, selected vertices, binding claims.
- **Behavior:** one controlled connector interface for both purposes, logged separately; per passage keep source class, revision, digest, locator, retrieval time, applicable interval, authority, access scope, retain/replay permission (paper §07). Idempotency key per request. Unavailable source keeps the obligation open.
- **Output:** passages, authority-check results per binding claim (`verified`, `not_found`, `unavailable`, `not_applicable`).
- **Tests:** attempted vs successful retrieval recorded distinctly; repeated request reuses recorded result.

### DVSS-K06 · Temporal filtering
- **Hook:** Steps 4 and 8.
- **Input:** passages with intervals, query scopes.
- **Behavior:** half-open intervals [start, end); overlap when each starts before the other ends; inclusive last dates converted once at ingest; each historical and prospective scope evaluated independently (paper §07).
- **Output:** applicable passages per scope; excluded passages with reason.
- **Tests:** superseded clause still governs a past interval; boundary day.

### DVSS-K07 · Bounded expansion
- **Hook:** Step 4.
- **Input:** anchors, spine, tier, retry count.
- **Behavior:** PPR with damping 0.85, ≤ 80 iterations, stop when successive vectors differ ≤ 1.76 × 10⁻⁶ (paper §06). Filter by access, scope, hop count, minimum score; stable record-ID tie-break; reserve slots for synthesized nodes; ≤ 250 vertices; starting hops 1 (Tier 1) or 2 (Tiers 2–3), +1 per authorized retry, ≤ 4; edge and token budgets re-applied after expansion.
- **Output:** retained vertices with scores, graph digest.
- **Tests:** limits hold after expansion; determinism across runs.

### DVSS-K08 · Source-age decay
- **Hook:** Step 10.
- **Input:** claims with source class p, scope, age.
- **Behavior:** b_i = p_i · I[active in scope] · exp(−λ_i · age_i), age in years relative to scope; default λ: 0 (stable mathematical facts), 0.01 (technical), 0.05 (frequently amended text) (paper §16a, F-DECAY-01). Age informs the heuristic score only; applicability is K06's job.
- **Output:** b per claim.
- **Tests:** c1 b = 0.9359, c2 b = 0.9753, c3 b = 0.9900.

### DVSS-K09 · Two-retry limit
- **Hook:** Step 11.
- **Input:** attempt list, gap analysis, authorized next source.
- **Behavior:** frozen policy F: retry only for a predefined recoverable evidence or scope gap with a named authorized next source or resolvable verifier failure; never reads the cutoff, labels or drift state; stop on exhaustion, permanent veto, no useful new evidence, or resolution; at most 2 retries; escalation logged separately and not counted (paper §16b).
- **Output:** `retry(next_source)` or `terminal(candidate_id)`.
- **Tests:** third retry refused; decision unchanged when the cutoff changes (replay test).

### DVSS-K10 · Hybrid triage
- **Hook:** Step 1.
- **Input:** normalized query, intake scores.
- **Behavior:** S = D + R + M, B, Z per `docs/specs/intake_scoring.md`; S_eff = max(S, 3B, 6Z); tier from `config/tiers.yaml`; Z hit forces Tier 3 with all four roles.
- **Output:** tier, active roles, feature values and their evidence.
- **Tests:** router fixtures; challenge development set.

### DVSS-K11 · Disclosure or abstention
- **Hook:** Steps 11–12.
- **Input:** K04 decision, profile.
- **Behavior:** maps decisions to user-visible text using `config/notices.yaml`: strict abstains on `abstain_or_explain`; advisory returns a bounded uncertainty explanation; drift warnings and missing-evidence notices are part of the returned text and covered by the response hash (paper §16c).
- **Output:** final text, release mode.
- **Tests:** a release naming a warning but returning the bare draft fails verification.

**Canonical release-mode mapping** (`strict`, `kernel_only`, and `kernel_plus_policy` all use strict release semantics):

| Condition / K04 decision | Profile | `receipt.decision.release_mode` | `X-DLE-Release-Mode` / `receipts.release_mode` | Notice ID |
| --- | --- | --- | --- | --- |
| `block` (hard gate fail / veto / service error) | any | `hard_veto_block` | `held` | `NOTICE-HOLD-01..03`, `NOTICE-HOLD-06..07` |
| `withhold_drift` | `strict` / `kernel_only` / `kernel_plus_policy` | `review_required` | `held` | `NOTICE-HOLD-05` |
| `withhold_drift` | `advisory` | `annotated_release_drift_warning` | `released_advisory` | `NOTICE-ADV-02` |
| `abstain_or_explain` | `strict` / `kernel_only` / `kernel_plus_policy` | `abstained` | `held` | `NOTICE-HOLD-04` |
| `abstain_or_explain` | `advisory` | `annotated_release_ka39` | `released_advisory` | `NOTICE-ADV-01` |
| `release` | any | `gate_passed` | `released` | `NOTICE-REL-01` |
| Non-DLE model or `functionCall` pass-through | any | *(none / pass-through)* | `passthrough` | `NOTICE-TOOL-01` (when function call pending) |
| Client abort mid-stream (GC-25) | any | `cancelled` | `cancelled` *(no response body)* | — |

### DVSS-K12 · Unresolved compliance veto
- **Hook:** Step 6 (ledger merge) and Step 11.
- **Input:** objection ledger.
- **Behavior:** a blocking objection stays open until the verifier closes it with evidence satisfying its predicate; an objection first appearing already closed is treated as open; any open blocking objection fails H. Veto authority comes only from here, never from registry flags.
- **Output:** open blocking objections.
- **Tests:** R1 stays open on B/2 in the warehouse case; closure without evidence rejected.

---

## Policy functions

| ID | Function | Behavior summary | Default (strict) | Fallback |
| --- | --- | --- | --- | --- |
| DVSS-P01 | Jurisdiction hierarchy | Orders applicable authorities by jurisdiction and precedence; conflicted precedence on a binding claim opens a review item | On | — |
| DVSS-P02 | Pareto options | After feasibility checks, keeps options not dominated on every objective in compatible units; runs only with ≥ 2 feasible options (paper §10) | On | — |
| DVSS-P03 | Session node synthesis | Adds session hypotheses to the overlay as derived nodes; they stay hypotheses and are never cited as evidence | On | — |
| DVSS-P04 | Contradiction detection | Normalizes claims to (subject, predicate, object, units, scope, interval, evidence) and flags opposite polarity on the same normalized claim | On | — |
| DVSS-P05 | Quarantined promotion | Offline only: stages session-derived nodes for registry review; never writes the live registry | Off | — |
| DVSS-P06 | Ontology alignment | Reconciles terms across Axis 3, 6 and 7 crosswalks; keeps unresolved interpretations | On | — |
| DVSS-P07 | Binding escalation | Binding claim without the Regulator → single escalation, S_eff recomputed with B = 1, objections carried forward | On | Required: H1 escalation logic |
| DVSS-P08 | Role token allocation | Role artifact tokens proportional to each role's PPR mass; equal split if all zero; largest-remainder rounding, role-ID tie-break; recomputed after expansion (paper §07) | On | Required: equal split |
| DVSS-P09 | Cross-domain analogy | Proposes analogies as hypotheses for roles to test; never evidence | Off | — |
| DVSS-P10 | Profile tie-breaking | Breaks equal M by credential count, then sector lineage, then profile ID | On | — |
| DVSS-P11 | Falsification prompts | Adds a "what would make this wrong" instruction and a disconfirming-evidence slot to each role packet | Tier 3 | — |
| DVSS-P12 | Fixed-baseline drift monitoring | CUSUM C_t = max(0, C_{t−1} + u_t − μ₀ − δ), δ = 0.02, alarm when C_t > λ; latches on registry, source-policy, scorer or generator change; cleared only by an approved calibration artifact (paper §16c) | On | Required: H14 latch |
| DVSS-P13 | Safety policy | Input checks (prompt injection markers in content, disallowed request classes) and output checks (secrets, personal data in logs); adds objections, never holds directly | On | — |
| DVSS-P14 | Offline policy tuning | Offline only: proposes tier thresholds and λ values from development data; outputs a staged artifact needing AI risk owner approval | Off at runtime | — |

Full one-page specifications for P01–P14 follow the kernel format and are written in the phase that builds each function (documentation set §2, function bindings by phase).

## Test obligations

Each function ships with unit tests named `T-UNIT-FN-<ID>-<nn>`, a contract test of its I/O schemas, and at least one engine test proving its hook fires at the right step. K04, K09, K11 and K12 additionally carry property-based and mutation tests (integrity level 4).
