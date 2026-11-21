# Intake scoring method for S, R, B and Z (G12)

**Document ID:** DLE-SPC-002 · **Version:** 0.1.0 · **Status:** Draft · **Owner:** Architect · **Date:** 2026-11-20 · **Requirements:** FR-TIER-01–02, DVSS-K10

## What the paper fixes (paper §07)

- D (topic count), R (regulatory exposure), M (ambiguity), each 0–3. S = D + R + M.
- D bands: 1, 2, 3–4, 5+ pillars. R bands: none, voluntary guidance, binding framework, cross-framework conflict. M bands: lookup, comparison, conditional or multi-period decision, open counterfactual.
- B = 1 when intake detects a binding predicate, or R ≥ 2.
- Z = 1 when maximum cosine similarity to a curated failure centroid meets a threshold, with a pinned embedding model; centroids and threshold from development data only.
- S_eff = max(S, 3B, 6Z). Store feature values and the evidence behind each.

## What this spec decides (D2)

| Feature | Method | Why |
| --- | --- | --- |
| D | Count of distinct Axis 1 pillars among K02-validated anchors, banded | Deterministic once anchors exist |
| R | Rules first: matched authority sources and Axis 6/7 entries; model score (intake job) only raises R, never lowers a rule result | Auditable floor; model catches phrasing rules miss |
| M | Model-scored with a fixed rubric and three anchored examples per band | Ambiguity is linguistic |
| B | Rule lexicon of deontic predicates (may, must, shall, prohibited, approve, authorize, permitted, required, compliant) on the normalized query, OR R ≥ 2, OR model flag | Recall matters most; any source sets B |
| Z | Local embedding (D3), cosine to failure centroids, threshold set on the development challenge set for ≥ 95% recall | Paper method unchanged |

## Model call for R and M

Job pin `intake`; temperature 0; JSON output `{ "R": 0-3, "M": 0-3, "binding_flag": bool, "rationale": str }`; rationale stored, never shown. Prompt includes the band definitions verbatim from paper §07.

## Combination

```
R_final = max(R_rules, R_model)
B = rule_lexicon_hit or R_final >= 2 or binding_flag
S = D + R_final + M
S_eff = max(S, 3*B, 6*Z)
```

## Validation

- Router fixtures: one per band boundary for D, R and M; every B trigger path; Z hit.
- Recall on the 50-item development challenge set ≥ 95% for routing to Tier 3 when expected; measured again on the 100-item held-out set in the study (paper §17: at most one miss for a 95.3% lower bound).
- Feature values and their evidence go into the run state and receipt.
