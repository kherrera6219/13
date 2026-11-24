# System card: DataLogicEngine 13-Axis Middleware v0.1.0 (G23 template)

Generated from configuration and evaluation results at each release (DLE-AIM). Fields below were filled by `offline/evaluate --system-card`.

## Intended use
Grounded, reviewable answers about documents and records an operator registers, where a held answer is better than an unsupported one. US deployments only.

## Not intended for
Fully automated consequential decisions without human review; questions whose sources are not registered.

## Models
| Job | Model | Version | Pinned |
| --- | --- | --- | --- |
| claim_extraction | `gemini-4-neon` | `gemini-4-neon-001` | yes |
| embeddings | `gemini-embedding-001` | `gemini-embedding-001-001` | yes |
| intake | `gemini-4-neon` | `gemini-4-neon-001` | yes |
| personas | `gemini-4-carbon` | `gemini-4-carbon-001` | yes |
| writer | `gemini-4-carbon` | `gemini-4-carbon-001` | yes |
Entailment: DeterministicLexicalNliScorer (CI) / OnnxNliScorer (DeBERTa-v3 optional) (deterministic-lexical-nli-v1).

## Configuration
Tier table digest 8d46bfc142c542bb · Profiles advisory, kernel_only, kernel_plus_policy, strict · Policy functions enabled DVSS-P01, DVSS-P02, DVSS-P03, DVSS-P04, DVSS-P06, DVSS-P07, DVSS-P08, DVSS-P10, DVSS-P11, DVSS-P12, DVSS-P13 · α = 0.05 · cutoff t̂ = 0.29.

## Evaluation results (2026-11-24, protocol f09d6eb)
| Measure | Result |
| --- | --- |
| Held-out accepted loss (150) | 0.0 (upper 95%: 0.019773) |
| Coverage (released share) | 0.42 |
| Over-abstention | 0.461538 |
| Router recall on challenge set (100) | 0.4 (95% lower: 0.317526) |
| Claim extractor recall | 1.0 (binding: 1.0) |
| Grader agreement κ | 0.930284 |
| Kernel-only vs kernel+policy loss difference | 0.0 (95% CI [0.0, 0.0]) |

## Known limitations
- The four roles share one base model; their agreement is not independent evidence.
- Single-premise entailment can miss multi-hop reasoning errors.
- Calibration holds only for the model pin, registry release and query mix it was measured on; changes latch the drift monitor.
- Claim extraction can miss claims; missed claims are never checked.
- Offline evaluation executed against deterministic FakeModel + lexical NLI; run live Gemini cloud calibration before external clinical/regulatory production use.

## Human oversight
Held answers state what evidence or authority would resolve them. Advisory answers are marked. Every answer has a signed receipt for review. Administrators monitor drift and recalibrate per the runbook.

## Contact
security@dle.local
