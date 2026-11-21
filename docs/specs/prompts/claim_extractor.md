# Prompt and model contract: claim extractor (G7)

**Document ID:** DLE-PRM-001 · **Version:** 0.1.0 · **Status:** Draft · **Owner:** AI risk owner · **Date:** 2026-11-20 · **Requirements:** FR-VER-01, FR-FL-07

## Purpose

Turn a draft answer and the role artifacts into atomic, scoped claims that the verifier can score one by one. The extractor's recall bounds the whole gate: a claim it misses is never checked (paper §16a). It runs independently of the writer: separate call, separate prompt, no access to the writer's reasoning.

## Model call

| Setting | Value |
| --- | --- |
| Job pin | `claim_extraction` in `config/model_pins.yaml` |
| Temperature / top_p | 0 / 1 |
| Response format | `application/json` with `responseSchema` = `contracts/prompts/claim_extraction.schema.json` |
| Tools | none |
| Input budget | draft + role artifacts; passages are **not** sent (the extractor must not judge support) |

## Prompt (version `extractor-1.0.0`)

```text
SYSTEM
You extract claims. You do not judge whether claims are true or supported.
Return JSON matching the schema. No prose.

Rules:
1. One claim per atomic assertion. Split compound sentences ("A and B" -> two claims).
2. Keep each claim's scope: entity, quantity with units, time interval, jurisdiction or site.
3. binding = true if the claim states a permission, obligation, prohibition, approval,
   authorization or a safety requirement.
4. Copy the exact character span of the draft each claim comes from (span_start, span_end).
5. Include claims stated in role artifacts that the draft relies on, with source = "artifact".
6. Do not invent claims. Do not drop hedged claims; set hedged = true.
7. Questions, instructions to the user and pure formatting are not claims.

USER
<draft id="{{proposal_id}}">{{draft_text}}</draft>
<artifacts>{{role_artifacts_json}}</artifacts>
```

Untrusted text (draft, artifacts) is wrapped in tags and never placed in the system slot (DLE-SEC secure coding rules).

## Output contract

See `contracts/prompts/claim_extraction.schema.json`. The host then:
1. checks every span maps to the draft text (K01 invariant);
2. assigns stable claim IDs `run/<attempt>/claim-<nn>`;
3. drops nothing silently: a claim whose span fails is kept with `span_valid: false` and raises an objection.

## Quality targets and tests

| Metric | Target | Measured on |
| --- | --- | --- |
| Claim recall (vs human-annotated claims) | ≥ 0.95 | 200 labeled drafts from development data |
| Binding-flag recall | ≥ 0.98 | Same, binding subset |
| Span validity | 100% after host check | All runs |
| Precision | ≥ 0.85 | Same set |

Golden tests: `tests/contract/prompts/test_claim_extractor.py` with 30 frozen draft→claims pairs, including the warehouse case (claims S1, P1, R1-c1). A prompt change is a minor version bump and must re-run the labeled set; a recall drop of more than 2 points blocks the change. The same set decides ADR-008.
