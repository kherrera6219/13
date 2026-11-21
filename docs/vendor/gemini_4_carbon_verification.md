# Gemini 4 Carbon verification note (G5)

Checked 2026-11-20 against Google's own pages. Re-check before each release and whenever `modelVersion` changes. Items marked **Unverified** are design assumptions not yet confirmed from a Google source; the phase 1 compatibility suite must confirm them.

## Verified

| Fact | Value | Source (Google) |
| --- | --- | --- |
| Availability | Generally available on the paid tier of the Gemini API (Google AI Studio) and Gemini for business; not on the free tier | [Gemini 4 Carbon is now available](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-4-carbon-now-available/), [Carbon for developers](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-4-carbon-developers/) |
| Introductory price, through 2026-11-30 | $2.00 per 1M input tokens, $10.00 per 1M output tokens (output includes thinking tokens), cached input $0.10 | Same; [Agent Platform pricing](https://cloud.google.com/model-garden/pricing) |
| Price from 2026-12-01 | $4.00 input, $20.00 output, $0.20 cached input per 1M tokens (global endpoint; non-global endpoints are 10% higher) | [Agent Platform pricing](https://cloud.google.com/model-garden/pricing) |
| Sibling model | Gemini 4 Argon (`gemini-4-argon`) has the same rate card; 1M-token shared context; implicit caching only | [What's new in Gemini 4 Argon](https://ai.google.dev/gemini-api/docs/latest-model), [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Gemini 4 Neon | Model ID `gemini-4-neon`; $3.00 input, $15.00 output, $0.15 cached input per 1M tokens (global); 1M context; thinking levels `low`/`medium`/`high`/`xhigh`; paid tier | Google AI Studio / Vertex AI pricing (checked 2026-11-20) |
| Gemini Embedding | Model ID `gemini-embedding-001`; $0.15 per 1M input tokens (text embeddings); same `generativelanguage.googleapis.com:443` host | `ai.google.dev` Gemini API pricing (checked 2026-11-20) |

## Reported by third parties, to confirm in Google's model page

- Model ID `gemini-4-carbon`, labelled stable.
- Context window 1,048,576 tokens shared between input and output.
- Batch, Flex and Priority inference modes listed with separate prices.

## Unverified design assumptions

| Assumption | Used by | How to verify |
| --- | --- | --- |
| `modelVersion` is returned on every response and changes when Google updates the model | M2 model registry, calibration latch | Record across a week of nightly live runs |
| `groundingMetadata` field names accepted by SDK parsers when the middleware populates them | E5 composer, FR-API-04 | Gemini compatibility tests GC-12, GC-13 |
| Built-in tool results (Google Search, URL context, code execution) arrive in parseable parts | E4 tool bridge, FR-TOOL-04 | GC-20–GC-22 |
| Thinking tokens are reported in `usageMetadata.thoughtsTokenCount` | NFR-COST-01 metering | Live run |
| Rate limits for the paid tier at the planned call volume | NFR-REL-02, evaluation budget | Read AI Studio quota page for the project |
| A cheaper Gemini model suitable for intake and extraction (ADR-008) | D8 | Measure extractor recall per G7 |

## Consequences for the design

1. **Prices change in 11 days.** NFR-COST-01 and the evaluation budget must use the December rates. Cost metering reads prices per model and date from `config/model_pins.yaml`; nothing is hard-coded.
2. **No free tier.** CI uses the fake model; only nightly live tests spend money.
3. **Same price as Argon.** Argon is a reasonable fallback pin if Carbon is throttled, but a model change latches calibration (FR-REL-04).
4. **Gemini 4 Neon and cloud embeddings.** `gemini-4-neon` provides a 25% lower post-Dec-1 rate ($3/$15 vs. $4/$20) and is pinned for intake and claim extraction (and selectable for personas/writer); `gemini-embedding-001` resolves Decision D3 over the single allowed Gemini API host.
