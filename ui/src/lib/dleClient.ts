import { GoogleGenAI, type Content, type GenerateContentResponse } from "@google/genai";
import type { ChatRun, DleHeaders, HealthStatus, ReleaseMode } from "../types/dle";

export interface SendMessageInput {
  baseUrl: string;
  apiKey: string;
  model: string;
  prompt: string;
  history: ChatRun[];
  streaming: boolean;
  sessionOverride?: string;
  onChunk?: (partialText: string) => void;
}

export interface SendMessageResult {
  run: ChatRun;
  headers: DleHeaders;
}

function normalizeReleaseMode(raw: string | null, hasToolCall: boolean): ReleaseMode {
  if (raw === "released" || raw === "released_advisory" || raw === "held") {
    return raw;
  }
  if (raw === "passthrough") {
    return hasToolCall ? "tool_call" : "passthrough";
  }
  return "passthrough";
}

function defaultNoticeFor(mode: ReleaseMode, toolName?: string): string {
  switch (mode) {
    case "released":
      return "Verified against configured evidence sources.";
    case "released_advisory":
      return "Advisory: not fully verified. See flagged claims.";
    case "held":
      return "Held: verification threshold not met. Attach or inspect receipt for details.";
    case "tool_call":
      return `Waiting for your app to run ${toolName ?? "requested tool"}.`;
    case "passthrough":
      return "Pass-through response delivered directly from Gemini.";
    case "error":
      return "Request failed. Check configuration and try again.";
  }
}

export function formatFriendlyError(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  if (msg.includes("401") || msg.includes("UNAUTHENTICATED")) {
    return "Key not accepted. Check the middleware API key in settings.";
  }
  if (msg.includes("429") || msg.includes("RESOURCE_EXHAUSTED")) {
    return "Rate limit reached. Wait a moment before retrying.";
  }
  if (msg.includes("503") || msg.includes("UNAVAILABLE")) {
    return "Upstream model unavailable. Verify backend status in health panel.";
  }
  return msg || "Request failed. Check middleware status and try again.";
}

export async function fetchHealth(baseUrl: string): Promise<HealthStatus> {
  const target = `${baseUrl.replace(/\/$/, "")}/healthz`;
  const resp = await fetch(target);
  if (!resp.ok) {
    throw new Error(`Health check returned HTTP ${resp.status}`);
  }
  return (await resp.json()) as HealthStatus;
}

export async function sendChatMessage(input: SendMessageInput): Promise<SendMessageResult> {
  let captured: DleHeaders = {
    releaseMode: "passthrough",
    receiptId: null,
    tier: null,
    apiVersion: null,
  };

  const capturingFetch: typeof fetch = async (reqInput, reqInit) => {
    const response = await fetch(reqInput, reqInit);
    const modeHeader = response.headers.get("X-DLE-Release-Mode");
    const receiptHeader = response.headers.get("X-DLE-Receipt");
    const tierHeader = response.headers.get("X-DLE-Tier");
    const apiVerHeader = response.headers.get("X-DLE-API-Version");

    captured = {
      releaseMode: normalizeReleaseMode(modeHeader, false),
      receiptId: receiptHeader,
      tier: tierHeader !== null && !Number.isNaN(Number(tierHeader)) ? Number(tierHeader) : null,
      apiVersion: apiVerHeader,
    };
    return response;
  };

  const requestHeaders: Record<string, string> = {};
  if (input.sessionOverride && input.sessionOverride.trim().length > 0) {
    requestHeaders["X-DLE-Session"] = input.sessionOverride.trim();
  }

  const ai = new GoogleGenAI({
    apiKey: input.apiKey,
    httpOptions: {
      baseUrl: input.baseUrl,
      apiVersion: "v1beta",
      headers: requestHeaders,
      fetch: capturingFetch,
    },
  });

  const contents: Content[] = input.history
    .filter((item) => item.releaseMode !== "error")
    .map((item) => ({
      role: item.role === "user" ? "user" : "model",
      parts: [{ text: item.text }],
    }));
  contents.push({
    role: "user",
    parts: [{ text: input.prompt }],
  });

  let aggregatedText = "";
  let toolName: string | undefined;

  if (input.streaming) {
    const stream = await ai.models.generateContentStream({
      model: input.model,
      contents,
    });
    for await (const chunk of stream) {
      if (chunk.text) {
        aggregatedText += chunk.text;
        input.onChunk?.(aggregatedText);
      }
      if (chunk.functionCalls && chunk.functionCalls.length > 0) {
        toolName = chunk.functionCalls[0].name;
      }
    }
  } else {
    const response: GenerateContentResponse = await ai.models.generateContent({
      model: input.model,
      contents,
    });
    aggregatedText = response.text ?? "";
    if (response.functionCalls && response.functionCalls.length > 0) {
      toolName = response.functionCalls[0].name;
    }
  }

  const finalMode: ReleaseMode =
    toolName && captured.releaseMode === "passthrough" ? "tool_call" : captured.releaseMode;
  const finalText =
    aggregatedText ||
    (toolName ? `Tool call requested: ${toolName}` : defaultNoticeFor(finalMode));

  const run: ChatRun = {
    id: `assistant-${Date.now()}`,
    role: "assistant",
    model: input.model,
    text: finalText,
    releaseMode: finalMode,
    noticeText: defaultNoticeFor(finalMode, toolName),
    receiptId: captured.receiptId,
    receiptStatus: captured.receiptId ? "pending_anchor" : undefined,
    tier: captured.tier,
    toolCallName: toolName,
    timestamp: new Date().toISOString(),
  };

  return {
    run,
    headers: { ...captured, releaseMode: finalMode },
  };
}
