# Developer quick start (G21)

**Document ID:** DLE-GDE-001 · **Version:** 0.1.0 · **Status:** Draft · **Audience:** application developers (persona P1, journey J1)

Point your existing Gemini app at the middleware and it gets verified answers. Two settings change: the base URL and the API key.

## 1. Connect

**Python**
```python
from google import genai
client = genai.Client(
    api_key="<DLE client key from your administrator>",
    http_options={"base_url": "http://127.0.0.1:8740"},
)
```

**JavaScript**
```ts
import { GoogleGenAI } from "@google/genai";
const ai = new GoogleGenAI({
  apiKey: "<DLE client key>",
  httpOptions: { baseUrl: "http://127.0.0.1:8740" },
});
```

## 2. Pick a model

| Model | Behavior |
| --- | --- |
| `dle-13axis-strict` | Releases only verified answers; otherwise holds with a reason |
| `dle-13axis-advisory` | Also returns not-fully-verified answers, marked advisory |
| `gemini-4-carbon` (or any Gemini model) | Passed straight through, no verification |

## 3. Handle the three outcomes

Every response is a normal Gemini response with `finishReason: STOP`. Read the release mode from the `X-DLE-Release-Mode` header (or `dleMetadata.releaseMode` in the body):

```python
r = client.models.generate_content(model="dle-13axis-strict", contents=question)
mode = r.sdk_http_response.headers.get("x-dle-release-mode")   # released | released_advisory | held
if mode == "released":
    show(r.text, sources=r.candidates[0].grounding_metadata)
elif mode == "released_advisory":
    show(r.text, banner="Advisory: not fully verified")
else:  # held
    show(r.text, banner="Held for review")   # r.text is the reason and what would resolve it
receipt_id = r.sdk_http_response.headers.get("x-dle-receipt")
```

Never show a held response as if it were an answer; its text is the hold reason.

## 4. Show sources

`groundingMetadata.groundingChunks` lists the cited passages (`uri` = `dle://source/<id>@<revision>#<locator>`); `groundingSupports` maps text spans to chunks. Render them the same way you render Google Search grounding.

## 5. Tools and functions

Declare tools exactly as with Gemini. Function calls come back to your app unchanged; send the `functionResponse` in the next turn as usual. The middleware treats your function results as evidence. Ask your administrator to flag functions with real-world effects as consequential, which adds compliance review of answers that rely on them.

## 6. Multi-turn and sessions

Use chats as usual. The middleware identifies a conversation by its history; editing an earlier turn starts a new session. To group requests yourself, send `X-DLE-Session: <your id>`.

## 7. Streaming

Streaming works, but verified text arrives only after checking finishes; you receive keepalives meanwhile. Expect a longer first token on complex questions.

## 8. Receipts

`GET /v1/receipts/<id>` returns the signed receipt: sources used, checks run, release decision. Keep receipt IDs with any answer you store.

## Errors

| HTTP | Meaning | Action |
| --- | --- | --- |
| 400 | Malformed request | Fix the request |
| 401 / 403 | Key missing or wrong | Check the key |
| 429 | Rate or budget limit | Back off and retry |
| 500 | Internal fault before any model call | Retry; report with the time |

A model outage is not an error: you get a held answer with a reason.
