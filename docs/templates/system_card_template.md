# System card: DataLogicEngine 13-Axis Middleware v{{version}} (G23 template)

Generated from configuration and evaluation results at each release (DLE-AIM). Fields in `{{ }}` are filled by `offline/evaluate --system-card`.

## Intended use
Grounded, reviewable answers about documents and records an operator registers, where a held answer is better than an unsupported one. US deployments only.

## Not intended for
Fully automated consequential decisions without human review; questions whose sources are not registered.

## Models
| Job | Model | Version | Pinned |
| --- | --- | --- | --- |
{{model_pin_rows}}
Entailment: {{nli_model}} ({{nli_sha256}}).

## Configuration
Tier table digest {{tier_digest}} · Profiles {{profiles}} · Policy functions enabled {{policy_set}} · α = {{alpha}} · cutoff t̂ = {{cutoff}}.

## Evaluation results ({{study_date}}, protocol {{protocol_commit}})
| Measure | Result |
| --- | --- |
| Held-out accepted loss (150) | {{accepted_loss}} |
| Coverage (released share) | {{coverage}} |
| Over-abstention | {{over_abstention}} |
| Router recall on challenge set (100) | {{router_recall}} |
| Claim extractor recall | {{extractor_recall}} |
| Grader agreement κ | {{kappa}} |
| Kernel-only vs kernel+policy loss difference | {{ablation_diff}} |

## Known limitations
- The four roles share one base model; their agreement is not independent evidence.
- Single-premise entailment can miss multi-hop reasoning errors.
- Calibration holds only for the model pin, registry release and query mix it was measured on; changes latch the drift monitor.
- Claim extraction can miss claims; missed claims are never checked.
- {{additional_limits}}

## Human oversight
Held answers state what evidence or authority would resolve them. Advisory answers are marked. Every answer has a signed receipt for review. Administrators monitor drift and recalibrate per the runbook.

## Contact
{{security_contact}}
