# Pre-registered study protocol (G19)

**Document ID:** DLE-EVL-003 · **Version:** 0.1.0 · **Status:** Draft, to be frozen before phase 6 · **Owner:** AI risk owner · **Date:** 2026-11-20

Implements paper §17 for the middleware. Once frozen, this file, the rubric (DLE-EVL-002), the held-out hash file and all config digests are committed and the commit hash is recorded here. Nothing below changes after freezing.

## Hypotheses

Paper §17 core hypotheses (evaluated before any test query is run):

| ID | Hypothesis | Primary comparison / sample | Refuted if / decision rule |
| --- | --- | --- | --- |
| H1 · Addressing | A decoded address adds value beyond the evidence it retrieves | Decoded address + evidence vs. identical evidence without an address (150 held-out test queries) | Graded loss at matched coverage is no better with the address |
| H2 · Roles | Four structured roles catch errors one reviewer misses | Full design vs. one structured reviewer with the same evidence and gate (150 held-out test queries) | Single reviewer matches graded loss and violation catches at lower cost |
| H3 · Gate | The release rule controls accepted loss at useful coverage | 150 held-out test queries, `strict` profile, vs. $\alpha = 0.05$ | Summed accepted loss > 2 full errors (one-sided 95% exact upper bound 4.1% at ≤ 2), or certified coverage falls below pre-registered minimum |
| H4 · Routing | The router sends disguised binding / failure-resembling questions to full review (Tier 3) | 100 held-out challenge items | Lower 95% exact binomial confidence bound on recall is below 95% (requires ≤ 1 miss for 95.3% lower bound) |

## Middleware-specific pre-registered endpoints

| ID | Endpoint | Sample / arms | Decision rule |
| --- | --- | --- | --- |
| M1 · Extractor recall | Claim-extractor recall on drafts | 200 labeled development drafts | Point estimate ≥ 0.95 and 95% CI lower bound ≥ 0.92; decides ADR-008 within 2 points of Gemini 4 Carbon |
| M2 · Catalog ablation | Policy functions improve decisions over kernel-only (paper §17 Catalog comparison) | Same 150 held-out queries, `kernel_only` vs `kernel_plus_policy` | Family-clustered paired bootstrap comparison of loss and coverage (95% CI); no directional claim if CI spans 0 |

## Frozen elements

Tasks, as-of dates, graph snapshots, registry release, source sets, model pins (with `modelVersion`), prompts (versions), NLI model hash, tier table, profiles, K09 policy F, cutoff t̂, CUSUM μ₀ and λ, seeds and budgets.

## Metrics reported

Accepted loss and coverage (both, paper §16b note 3); over-abstention rate; per-tier latency, tokens and cost; κ between graders; router confusion matrix; extractor recall; hold reasons by notice ID; ablation differences per function where attributable through FunctionRecords.

## Analysis

One-sided 95% exact binomial bounds for `H3` (each loss counted as a full error, conservative) and `H4`; family-clustered paired bootstrap 95% confidence intervals on the fixed held-out set for `H1`, `H2`, and `M2`. No interim looks at held-out data. Any deviation is reported as a deviation, with reason.

## Stopping and integrity

The study stops only on completion or on a defect of severity 1 or 2, which voids the run; the fix requires a new calibration and a new held-out set.
