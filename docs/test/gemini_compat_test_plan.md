# Gemini compatibility test plan (G4)

**Goal.** Prove FR-API-01–03 and FR-TOOL-01–03: an unmodified Gemini SDK client behaves the same against the middleware as against Google. This is the phase 1 exit gate.

## Approach

Each case runs twice with the same client code: once against Google (recorded) and once against the middleware. Recordings are captured once with a live key and replayed by a fake upstream so CI never calls Google. A case passes when the SDK-visible results are equivalent: same types, same fields populated, same errors, same streaming chunk structure. Text need not match.

- **Clients:** `google-genai` (Python) and `@google/genai` (JS), pinned to the latest release at phase 1 start, plus the previous minor release. Raw REST with `curl` for one case per route.
- **Upstream:** `tests/gemini_compat/fake_upstream.py` replays recordings keyed by request hash.
- **Models:** pass-through (`gemini-4-carbon`) for every case; governed (`dle-13axis-strict`) for cases marked G once phase 2 lands.
- **Platforms:** Linux and Windows CI.

## Cases

| ID | Feature | Check | Mode |
| --- | --- | --- | --- |
| GC-01 | List models | DLE virtual models present; Gemini models listed; pagination works | P |
| GC-02 | Get model | `models/dle-13axis-strict` resolves | P |
| GC-03 | Single-turn text | `response.text` populated, `finishReason` STOP | P, G |
| GC-04 | System instruction | Honored; changes session hash | P, G |
| GC-05 | Multi-turn chat (`chats.create`) | History round-trips; session hash stable across turns | P, G |
| GC-06 | Generation config | temperature, maxOutputTokens, responseMimeType JSON, responseSchema honored | P |
| GC-07 | Streaming (`generate_content_stream`) | Chunks iterate; final chunk has usage; no client timeout during 60 s gate (keepalives) | P, G |
| GC-08 | Count tokens | Same count as Google | P |
| GC-09 | Auth header and query key | Both accepted; bad key gives 401 with Gemini error shape | P |
| GC-10 | Invalid request | 400 `INVALID_ARGUMENT`, SDK raises the same exception type | P |
| GC-11 | Rate limit | 429 `RESOURCE_EXHAUSTED`, SDK retry behavior unchanged | P |
| GC-12 | Grounding metadata parse | SDK exposes `grounding_metadata.grounding_chunks` and `grounding_supports` | G |
| GC-13 | Held answer | 200, STOP, hold text, `X-DLE-Release-Mode: held` readable via raw response | G |
| GC-14 | Function calling, single | `functionCall` returned unchanged; `functionResponse` accepted | P, G |
| GC-15 | Function calling, parallel | Multiple `functionCall` parts preserved in order | P, G |
| GC-16 | Automatic function calling (Python SDK) | SDK's auto loop completes through the middleware | P, G |
| GC-17 | Tool config modes | AUTO, ANY, NONE honored | P |
| GC-18 | Function call with ID | `id` round-trips | P |
| GC-19 | Inline image input | `inlineData` passes; governed run treats it as non-text evidence | P |
| GC-20 | Google Search tool | Result parts and Google's own grounding metadata pass through | P |
| GC-21 | URL context tool | Passes through | P |
| GC-22 | Code execution tool | `executableCode` and `codeExecutionResult` parts pass through | P |
| GC-23 | Thinking config | `thinkingConfig` passes; thought parts not leaked into governed text | P, G |
| GC-24 | Large context | 500k-token request passes within limits | P |
| GC-25 | Cancellation | Client abort mid-stream frees the run; receipt records `cancelled` | G |
| GC-26 | Unknown future field | Extra request and response fields pass through untouched | P |

## Exit criteria

All P cases pass on both SDKs, both platforms, current and previous SDK minor versions. G cases are added to the gate at phase 2. Any failure blocks release (defect severity 2).
