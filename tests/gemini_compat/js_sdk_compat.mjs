/**
 * Official `@google/genai` JavaScript SDK compatibility suite (GC-01..GC-26 P-cases).
 * Executed against a live local DLE middleware via DLE_BASE_URL + DLE_API_KEY env vars.
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "../..");
const require = createRequire(path.join(repoRoot, "ui/package.json"));
const { GoogleGenAI, Type } = require("@google/genai");

const baseUrl = process.env.DLE_BASE_URL;
const apiKey = process.env.DLE_API_KEY;
const adminKey = process.env.DLE_ADMIN_KEY;
assert.ok(baseUrl, "DLE_BASE_URL env var is required");
assert.ok(apiKey, "DLE_API_KEY env var is required");

function makeClient(overrideKey = apiKey, extraBody = undefined, customFetch = undefined) {
  return new GoogleGenAI({
    apiKey: overrideKey,
    httpOptions: {
      baseUrl,
      apiVersion: "v1beta",
      ...(extraBody ? { extraBody } : {}),
      ...(customFetch ? { fetch: customFetch } : {}),
      retryOptions: { attempts: 1 },
    },
  });
}

async function runSuite() {
  const results = [];
  const ai = makeClient();

  // GC-01 List models + pagination
  {
    const pager = await ai.models.list({ config: { pageSize: 2 } });
    const names = [];
    for await (const m of pager) {
      if (m.name) {
        names.push(m.name);
      }
    }
    assert.ok(names.includes("models/dle-13axis-strict"));
    assert.ok(names.includes("models/dle-13axis-advisory"));
    assert.ok(names.includes("models/gemini-4-carbon"));
    assert.ok(names.includes("models/gemini-embedding-001"));
    results.push("GC-01");
  }

  // GC-02 Get model
  {
    const m = await ai.models.get({ model: "models/dle-13axis-strict" });
    assert.equal(m.name, "models/dle-13axis-strict");
    results.push("GC-02");
  }

  // GC-03 Single turn
  {
    const res = await ai.models.generateContent({
      model: "gemini-4-carbon",
      contents: "JS SDK single turn test.",
    });
    assert.ok(res.text && res.text.includes("gemini-4-carbon"));
    assert.equal(res.candidates?.[0]?.finishReason, "STOP");
    results.push("GC-03");
  }

  // GC-04 System instruction
  {
    const res = await ai.models.generateContent({
      model: "gemini-4-carbon",
      contents: "Status?",
      config: { systemInstruction: "Concise policy tone." },
    });
    assert.ok(res.text && res.text.includes("[with-system]"));
    results.push("GC-04");
  }

  // GC-05 Multi-turn chats.create
  {
    const chat = ai.chats.create({ model: "gemini-4-carbon" });
    const r1 = await chat.sendMessage({ message: "First JS turn" });
    const r2 = await chat.sendMessage({ message: "Second JS turn" });
    assert.ok(r1.text?.includes("turn=1"));
    assert.ok(r2.text?.includes("turn=3"));
    results.push("GC-05");
  }

  // GC-06 Generation config JSON + schema
  {
    const res = await ai.models.generateContent({
      model: "gemini-4-carbon",
      contents: "Return JSON decision.",
      config: {
        temperature: 0.1,
        maxOutputTokens: 256,
        responseMimeType: "application/json",
        responseSchema: {
          type: Type.OBJECT,
          properties: {
            answer: { type: Type.STRING },
            confidence: { type: Type.NUMBER },
          },
          required: ["answer", "confidence"],
        },
      },
    });
    const parsed = JSON.parse(res.text ?? "{}");
    assert.equal(parsed.answer, "verified");
    results.push("GC-06");
  }

  // GC-07 Streaming (pass-through + governed SSE keepalive)
  {
    const stream = await ai.models.generateContentStream({
      model: "gemini-4-carbon",
      contents: "Stream chunks cleanly in JS.",
    });
    let text = "";
    let hasUsage = false;
    for await (const chunk of stream) {
      if (chunk.text) {
        text += chunk.text;
      }
      if (chunk.usageMetadata?.totalTokenCount) {
        hasUsage = true;
      }
    }
    assert.ok(text.length > 0);
    assert.ok(hasUsage);

    const govStream = await ai.models.generateContentStream({
      model: "dle-13axis-strict",
      contents: "Stream governed response in JS.",
    });
    let govText = "";
    for await (const chunk of govStream) {
      if (chunk.text) {
        govText += chunk.text;
      }
    }
    assert.ok(govText.length > 0);
    results.push("GC-07");
  }

  // GC-08 Count tokens
  {
    const cnt = await ai.models.countTokens({
      model: "gemini-4-carbon",
      contents: "Count JS SDK tokens.",
    });
    assert.ok((cnt.totalTokens ?? 0) > 0);
    results.push("GC-08");
  }

  // GC-09 Bad key -> 401
  {
    const badAi = makeClient("invalid-" + "js-key-01");
    await assert.rejects(
      () =>
        badAi.models.generateContent({
          model: "gemini-4-carbon",
          contents: "Should fail 401",
        }),
      (err) => String(err).includes("401") || err?.status === 401,
    );
    results.push("GC-09");
  }

  // GC-10 Invalid argument -> 400
  {
    await assert.rejects(
      () =>
        ai.models.generateContent({
          model: "gemini-4-carbon",
          contents: "TRIGGER_400 JS validation",
        }),
      (err) => String(err).includes("400") || err?.status === 400,
    );
    results.push("GC-10");
  }

  // GC-11 Rate limit -> 429
  {
    await assert.rejects(
      () =>
        ai.models.generateContent({
          model: "gemini-4-carbon",
          contents: "TRIGGER_429 JS rate limit",
        }),
      (err) => String(err).includes("429") || err?.status === 429,
    );
    results.push("GC-11");
  }

  // GC-14 + GC-15 Function calls single & parallel
  {
    const tools = [
      {
        functionDeclarations: [
          { name: "get_weather", description: "Weather lookup" },
          { name: "get_time", description: "Time lookup" },
        ],
      },
    ];
    const single = await ai.models.generateContent({
      model: "gemini-4-carbon",
      contents: "Check weather",
      config: { tools },
    });
    assert.equal(single.functionCalls?.length, 1);
    assert.equal(single.functionCalls?.[0]?.name, "get_weather");
    results.push("GC-14");

    const parallel = await ai.models.generateContent({
      model: "gemini-4-carbon",
      contents: "Run parallel weather and time",
      config: { tools },
    });
    assert.deepEqual(
      parallel.functionCalls?.map((c) => c.name),
      ["get_weather", "get_time"],
    );
    results.push("GC-15");

    // GC-17 Tool config modes AUTO / ANY / NONE
    for (const mode of ["AUTO", "ANY", "NONE"]) {
      const mRes = await ai.models.generateContent({
        model: "gemini-4-carbon",
        contents: `Check tool mode ${mode}`,
        config: {
          tools,
          toolConfig: { functionCallingConfig: { mode } },
        },
      });
      if (mode === "NONE") {
        assert.equal(mRes.functionCalls?.length ?? 0, 0);
      } else {
        assert.equal(mRes.functionCalls?.[0]?.name, "get_weather");
      }
    }
    results.push("GC-17");

    // GC-18 Function call with ID round-trip
    const idRes = await ai.models.generateContent({
      model: "gemini-4-carbon",
      tools,
      contents: [
        { role: "user", parts: [{ text: "Check weather id" }] },
        {
          role: "model",
          parts: [{ functionCall: { id: "js-id-88", name: "get_weather", args: {} } }],
        },
        {
          role: "function",
          parts: [
            {
              functionResponse: {
                id: "js-id-88",
                name: "get_weather",
                response: { ok: true },
              },
            },
          ],
        },
      ],
    });
    assert.ok(idRes.text?.includes("js-id-88"));
    results.push("GC-18");
  }

  // GC-19 Inline image + GC-20 Google Search + GC-21 URL Context + GC-22 Code Execution + GC-23 Thinking + GC-24 Large + GC-26 Unknown
  {
    const imgRes = await ai.models.generateContent({
      model: "gemini-4-carbon",
      contents: [
        { text: "Inspect sticker" },
        {
          inlineData: {
            mimeType: "image/png",
            data: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII=",
          },
        },
      ],
    });
    assert.ok(imgRes.text?.includes("image/png"));
    results.push("GC-19");

    const res = await ai.models.generateContent({
      model: "gemini-4-carbon",
      contents: "Search policy spec.",
      config: { tools: [{ googleSearch: {} }] },
    });
    assert.ok((res.candidates?.[0]?.groundingMetadata?.groundingChunks?.length ?? 0) === 1);
    results.push("GC-20");

    const urlRes = await ai.models.generateContent({
      model: "gemini-4-carbon",
      contents: "Read https://example.org/doc",
      config: { tools: [{ urlContext: {} }] },
    });
    assert.ok(urlRes.text?.includes("URL context"));
    results.push("GC-21");

    const codeRes = await ai.models.generateContent({
      model: "gemini-4-carbon",
      contents: "Compute 6*7",
      config: { tools: [{ codeExecution: {} }] },
    });
    const codeParts = codeRes.candidates?.[0]?.content?.parts ?? [];
    assert.ok(codeParts.some((p) => p.executableCode));
    assert.ok(codeParts.some((p) => p.codeExecutionResult));
    results.push("GC-22");

    const thinkRes = await ai.models.generateContent({
      model: "gemini-4-carbon",
      contents: "Reason step-by-step",
      config: { thinkingConfig: { includeThoughts: true, thinkingBudget: 256 } },
    });
    const thinkParts = thinkRes.candidates?.[0]?.content?.parts ?? [];
    assert.ok(thinkParts.some((p) => p.thought === true));
    results.push("GC-23");

    const largeRes = await ai.models.generateContent({
      model: "gemini-4-carbon",
      contents: "warehouse policy rule verification ".repeat(45000),
    });
    assert.ok((largeRes.usageMetadata?.promptTokenCount ?? 0) >= 500000);
    results.push("GC-24");

    const futAi = makeClient(apiKey, { futureExperimentalFlag: "js-echo" });
    const futRes = await futAi.models.generateContent({
      model: "gemini-4-carbon",
      contents: "Future field JS.",
    });
    assert.ok(futRes.text && futRes.text.length > 0);
    results.push("GC-26");
  }

  // GC-12 & GC-13 Governed release groundingMetadata + governed held response
  if (adminKey) {
    const resetResp = await fetch(`${baseUrl}/admin/drift/reset`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-DLE-Admin-Key": adminKey,
      },
      body: JSON.stringify({ calibrationArtifactId: "cal-phase6-v1", confirm: "RESET" }),
    });
    assert.equal(resetResp.status, 204);

    const clause =
      "Forklift bay F-18 enforces ANSI Z535 safety signage before pallet loading.";
    const regResp = await fetch(`${baseUrl}/admin/sources`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-DLE-Admin-Key": adminKey,
      },
      body: JSON.stringify({
        title: "Forklift Bay Safety Standard",
        authorityClass: "primary_text",
        content: {
          mimeType: "text/plain",
          data: Buffer.from(clause, "utf8").toString("base64"),
        },
      }),
    });
    assert.equal(regResp.status, 201);

    let lastHeaders = null;
    const govAi = makeClient(apiKey, undefined, async (reqInput, reqInit) => {
      const resp = await fetch(reqInput, reqInit);
      lastHeaders = resp.headers;
      return resp;
    });

    const relRes = await govAi.models.generateContent({
      model: "dle-13axis-strict",
      contents: clause,
    });
    assert.equal(lastHeaders?.get("X-DLE-Release-Mode"), "released");
    assert.ok((relRes.candidates?.[0]?.groundingMetadata?.groundingChunks?.length ?? 0) > 0);
    results.push("GC-12");

    const heldRes = await govAi.models.generateContent({
      model: "dle-13axis-strict",
      contents: "Speculative zero-gravity conveyor lanes bypass warehouse inspection.",
    });
    assert.equal(lastHeaders?.get("X-DLE-Release-Mode"), "held");
    assert.equal(heldRes.candidates?.[0]?.finishReason, "STOP");
    assert.ok(heldRes.text && heldRes.text.trim().length > 0);
    results.push("GC-13");
  }

  console.log(JSON.stringify({ ok: true, passedCases: results }));
}

await runSuite();
