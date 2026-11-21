# Evaluation data plan and budget (G17, G20)

**Document ID:** DLE-EVL-001 · **Version:** 0.1.0 · **Status:** Draft · **Owner:** AI risk owner · **Date:** 2026-11-20

## 1. Data sets

| Set | Size | Purpose | Source | Use rule |
| --- | --- | --- | --- | --- |
| Development | 300 queries | Tune prompts, intake rubric, λ decay rates, Z centroids, K09 policy F | Domain experts write from the pilot corpus (D4); 20% adapted from public question sets with licenses checked | Free use |
| Development challenge | 50 queries | Router recall and failure centroids | Red-team authors: disguised binding questions, near-miss lookups, injection attempts | Free use |
| Calibration pilot | ~100 queries | First cutoff at α = .05 (phase 6) | Fresh, same authoring process | Grade once; never tune on |
| Calibration (full) | 300 queries | Production cutoff | Fresh | Grade once; never tune on |
| Held-out test | 150 queries | Study endpoints (H3 at α = .05) | Fresh, written after the cutoff is frozen | Sealed until the study run |
| Held-out challenge | 100 queries | Router recall ≥ 95% (≤ 1 miss) | Fresh red-team | Sealed until the study run |
| Extractor labeled set | 200 drafts | Claim and binding-flag recall (G7, ADR-008) | Drafts from development runs, claims annotated by two graders | Development only |

**Sealing.** Before any calibration run, each held-out item's SHA-256 (over JCS of question, as-of date, source set) is written to `offline/registry/heldout_hashes.json` and committed; the commit hash goes in the study protocol. O1 and O3 refuse any dataset containing a registered hash outside the study run.

**Composition.** Each set is stratified by expected tier (roughly 40/35/25 for tiers 1/2/3) and by domain, and records the as-of date and permitted source set per query.

**Provenance and licensing.** Each query records author, date, source documents and license. No personal data. No customer data.

## 2. Budget (G20)

Assumptions: Gemini 4 Carbon at the December 2026 rate of $4 per million input tokens and $20 per million output tokens (verified 2026-11-20); token counts are planning estimates to be replaced by phase 1 measurements (NFR-OBS-01).

| Tier | Model calls (typical) | Input tokens per run | Output tokens per run | Cost per run |
| --- | --- | --- | --- | --- |
| 1 | 4 | 40,000 | 4,000 | $0.24 |
| 2 | 9 | 110,000 | 12,000 | $0.68 |
| 3 | 14 | 220,000 | 24,000 | $1.36 |

At the 40/35/25 mix, a run averages about $0.67. Every graded set is run once per arm; the ablation doubles the held-out runs.

| Item | Runs | Model cost | Grader hours (12 min per answer, two graders, 20% adjudication) |
| --- | --- | --- | --- |
| Development (3 passes) | 900 | ~$600 | — |
| Calibration pilot | 100 | ~$67 | ~44 h |
| Calibration full | 300 | ~$200 | ~132 h |
| Held-out test, two arms | 300 | ~$200 | ~132 h |
| Challenge sets | 150 | ~$100 | ~20 h (routing only) |
| Extractor labels | — | — | ~40 h |
| **Total** | **1,750** | **~$1,180** | **~370 h** |

Grader time, not model spend, is the constraint (blueprint risk "Phases 6 and 7 stall"). Re-estimate after phase 1 with measured tokens.
