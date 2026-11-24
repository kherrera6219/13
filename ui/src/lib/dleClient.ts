import { GoogleGenAI, type Content, type GenerateContentResponse } from "@google/genai";
import type {
  ChatRun,
  CitationItem,
  ClaimRow,
  ClaimStatus,
  CoordinateSummary,
  CostByTierDay,
  DleHeaders,
  EvidenceSource,
  FunctionFlagsResponse,
  GraphSummary,
  HealthStatus,
  IntakeSummary,
  PersonaObjectionItem,
  PersonaSummary,
  ReleaseMode,
  RunSummary,
  SignedReceipt,
  StepTraceItem,
} from "../types/dle";

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

export interface RegisterSourceInput {
  title: string;
  authorityClass: string;
  contentText: string;
  jurisdiction?: string;
  validFrom?: string;
  validTo?: string;
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
      return "Held: verification threshold not met. Inspect receipt for details.";
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

function encodeBase64Utf8(raw: string): string {
  const bytes = new TextEncoder().encode(raw);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export function extractCitations(response?: GenerateContentResponse | null): CitationItem[] {
  const meta = response?.candidates?.[0]?.groundingMetadata;
  if (!meta) {
    return [];
  }
  const chunks = meta.groundingChunks ?? [];
  const supports = meta.groundingSupports ?? [];

  const excerptByIndex = new Map<number, string>();
  for (const sup of supports) {
    const excerptText = sup.segment?.text?.trim();
    if (!excerptText) {
      continue;
    }
    for (const chunkIdx of sup.groundingChunkIndices ?? []) {
      if (typeof chunkIdx === "number" && !excerptByIndex.has(chunkIdx)) {
        excerptByIndex.set(chunkIdx, excerptText);
      }
    }
  }

  return chunks.map((chunk, idx) => {
    const web = chunk.web;
    const retrieved = chunk.retrievedContext;
    const title = retrieved?.title ?? web?.title ?? `Source ${idx + 1}`;
    const uri = retrieved?.uri ?? web?.uri ?? `source-${idx + 1}`;
    const excerpt = retrieved?.text ?? excerptByIndex.get(idx);
    return {
      index: idx + 1,
      title,
      uri,
      ...(excerpt ? { excerpt } : {}),
    };
  });
}

function classifyClaim(supportZ: number, contradictionZ: number): ClaimStatus {
  if (contradictionZ >= 0.4) {
    return "contradicted";
  }
  if (supportZ >= 0.65) {
    return "supported";
  }
  if (supportZ >= 0.35) {
    return "weak";
  }
  return "unverified";
}

export function extractClaimsFromReceipt(receipt: SignedReceipt): ClaimRow[] {
  const attempts = receipt.payload.attempts;
  if (!Array.isArray(attempts) || attempts.length === 0) {
    return [];
  }
  const lastAttempt = attempts[attempts.length - 1];
  const rawClaims = Array.isArray(lastAttempt.claims) ? lastAttempt.claims : [];
  return rawClaims.map((raw, idx) => {
    const claimId =
      typeof raw.claim_id === "string" && raw.claim_id.length > 0
        ? raw.claim_id
        : `claim-${idx + 1}`;
    const assertion = typeof raw.assertion === "string" ? raw.assertion : "";
    const binding = Boolean(raw.binding);
    const hedged = Boolean(raw.hedged);
    const rawSupport =
      typeof raw.support_z === "number"
        ? raw.support_z
        : typeof raw.belief === "number"
          ? raw.belief
          : 0;
    const rawContra = typeof raw.contradiction === "number" ? raw.contradiction : 0;
    const rawSources = Array.isArray(raw.source_ids)
      ? raw.source_ids
      : Array.isArray(raw.passage_ids)
        ? raw.passage_ids
        : [];
    const sourceIds = rawSources.filter((item): item is string => typeof item === "string");
    return {
      claimId,
      assertion,
      binding,
      hedged,
      supportZ: Number(rawSupport),
      contradictionZ: Number(rawContra),
      status: classifyClaim(Number(rawSupport), Number(rawContra)),
      sourceIds,
    };
  });
}

export function extractObjectionsFromReceipt(receipt: SignedReceipt): PersonaObjectionItem[] {
  const attempts = receipt.payload.attempts;
  if (!Array.isArray(attempts) || attempts.length === 0) {
    return [];
  }
  const lastAttempt = attempts[attempts.length - 1];
  const rawObjs = Array.isArray(lastAttempt.objections) ? lastAttempt.objections : [];
  return rawObjs.map((raw, idx) => {
    const objectionId =
      typeof raw.objection_id === "string" && raw.objection_id.length > 0
        ? raw.objection_id
        : `obj-${idx + 1}`;
    const roleAxis = typeof raw.role_axis === "number" ? raw.role_axis : 10;
    const proposalId =
      typeof raw.proposal_id === "string" && raw.proposal_id.length > 0
        ? raw.proposal_id
        : "prop-1";
    const blocking = Boolean(raw.blocking);
    const predicate = typeof raw.predicate === "string" ? raw.predicate : "";
    const state: "open" | "closed" = raw.state === "closed" ? "closed" : "open";
    const rawClosure = Array.isArray(raw.closure_evidence) ? raw.closure_evidence : [];
    const closureEvidence = rawClosure.filter((item): item is string => typeof item === "string");
    return {
      objectionId,
      roleAxis,
      proposalId,
      blocking,
      predicate,
      state,
      closureEvidence,
    };
  });
}

export async function fetchHealth(baseUrl: string): Promise<HealthStatus> {
  const target = `${baseUrl.replace(/\/$/, "")}/healthz`;
  const resp = await fetch(target);
  if (!resp.ok) {
    throw new Error(`Health check returned HTTP ${resp.status}`);
  }
  return (await resp.json()) as HealthStatus;
}

export async function fetchReceipt(
  baseUrl: string,
  apiKey: string,
  receiptId: string,
): Promise<SignedReceipt> {
  const target = `${baseUrl.replace(/\/$/, "")}/v1/receipts/${encodeURIComponent(receiptId)}`;
  const resp = await fetch(target, {
    headers: { "x-goog-api-key": apiKey },
  });
  if (!resp.ok) {
    throw new Error(`Receipt lookup returned HTTP ${resp.status}`);
  }
  return (await resp.json()) as SignedReceipt;
}

export async function fetchSources(
  baseUrl: string,
  apiKey: string,
  pageToken?: string,
): Promise<{ sources: EvidenceSource[]; nextPageToken?: string }> {
  const base = baseUrl.replace(/\/$/, "");
  const query = pageToken ? `?pageToken=${encodeURIComponent(pageToken)}` : "";
  const resp = await fetch(`${base}/v1/sources${query}`, {
    headers: { "x-goog-api-key": apiKey },
  });
  if (!resp.ok) {
    throw new Error(`Sources lookup returned HTTP ${resp.status}`);
  }
  return (await resp.json()) as { sources: EvidenceSource[]; nextPageToken?: string };
}

export async function registerSource(
  baseUrl: string,
  adminKey: string,
  input: RegisterSourceInput,
): Promise<EvidenceSource> {
  const target = `${baseUrl.replace(/\/$/, "")}/admin/sources`;
  const resp = await fetch(target, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-DLE-Admin-Key": adminKey,
    },
    body: JSON.stringify({
      title: input.title,
      authorityClass: input.authorityClass,
      ...(input.jurisdiction?.trim() ? { jurisdiction: input.jurisdiction.trim() } : {}),
      ...(input.validFrom?.trim() ? { validFrom: input.validFrom.trim() } : {}),
      ...(input.validTo?.trim() ? { validTo: input.validTo.trim() } : {}),
      content: {
        mimeType: "text/plain",
        data: encodeBase64Utf8(input.contentText),
      },
    }),
  });
  if (!resp.ok) {
    throw new Error(`Register source returned HTTP ${resp.status}`);
  }
  return (await resp.json()) as EvidenceSource;
}

export async function resetDriftLatch(
  baseUrl: string,
  adminKey: string,
  calibrationArtifactId: string,
): Promise<void> {
  const target = `${baseUrl.replace(/\/$/, "")}/admin/drift/reset`;
  const resp = await fetch(target, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-DLE-Admin-Key": adminKey,
    },
    body: JSON.stringify({
      calibrationArtifactId: calibrationArtifactId.trim(),
      confirm: "RESET",
    }),
  });
  if (!resp.ok) {
    throw new Error(`Drift reset returned HTTP ${resp.status}`);
  }
}

export async function fetchFunctionFlags(
  baseUrl: string,
  adminKey: string,
): Promise<FunctionFlagsResponse> {
  const target = `${baseUrl.replace(/\/$/, "")}/admin/function-flags`;
  const resp = await fetch(target, {
    headers: { "X-DLE-Admin-Key": adminKey },
  });
  if (!resp.ok) {
    throw new Error(`Function flags lookup returned HTTP ${resp.status}`);
  }
  return (await resp.json()) as FunctionFlagsResponse;
}

export async function updateFunctionFlags(
  baseUrl: string,
  adminKey: string,
  payload: FunctionFlagsResponse,
): Promise<FunctionFlagsResponse> {
  const target = `${baseUrl.replace(/\/$/, "")}/admin/function-flags`;
  const resp = await fetch(target, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "X-DLE-Admin-Key": adminKey,
    },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    throw new Error(`Update function flags returned HTTP ${resp.status}`);
  }
  return (await resp.json()) as FunctionFlagsResponse;
}

export async function fetchCostByTier(
  baseUrl: string,
  adminKey: string,
  days = 7,
): Promise<CostByTierDay[]> {
  const target = `${baseUrl.replace(/\/$/, "")}/admin/metrics/cost-by-tier?days=${encodeURIComponent(String(days))}`;
  const resp = await fetch(target, {
    headers: { "X-DLE-Admin-Key": adminKey },
  });
  if (!resp.ok) {
    throw new Error(`Cost metrics lookup returned HTTP ${resp.status}`);
  }
  const body = (await resp.json()) as { days?: CostByTierDay[] };
  return Array.isArray(body.days) ? body.days : [];
}

export async function exportReceiptsBundle(
  baseUrl: string,
  adminKey: string,
  fromIso: string,
  toIso: string,
): Promise<Blob> {
  const target = `${baseUrl.replace(/\/$/, "")}/admin/receipts/export`;
  const resp = await fetch(target, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-DLE-Admin-Key": adminKey,
    },
    body: JSON.stringify({ from: fromIso, to: toIso }),
  });
  if (!resp.ok) {
    throw new Error(`Receipt export returned HTTP ${resp.status}`);
  }
  return await resp.blob();
}

export async function sendChatMessage(input: SendMessageInput): Promise<SendMessageResult> {
  let captured: DleHeaders = {
    releaseMode: "passthrough",
    receiptId: null,
    tier: null,
    apiVersion: null,
  };
  let capturedCoordinate: CoordinateSummary | null = null;
  let capturedGraph: GraphSummary | null = null;
  let capturedRunSummary: RunSummary | null = null;
  let capturedIntake: IntakeSummary | null = null;
  let capturedPersonas: PersonaSummary[] = [];
  let capturedSteps: StepTraceItem[] = [];

  const extractDleMetadata = (obj: unknown) => {
    if (!obj || typeof obj !== "object") {
      return;
    }
    const root = obj as Record<string, unknown>;
    const meta = root.dleMetadata;
    if (!meta || typeof meta !== "object") {
      return;
    }
    const rec = meta as Record<string, unknown>;
    if (rec.coordinate && typeof rec.coordinate === "object") {
      capturedCoordinate = rec.coordinate as CoordinateSummary;
    }
    if (rec.graph && typeof rec.graph === "object") {
      capturedGraph = rec.graph as GraphSummary;
    }
    if (rec.runSummary && typeof rec.runSummary === "object") {
      capturedRunSummary = rec.runSummary as RunSummary;
    }
    if (rec.intake && typeof rec.intake === "object") {
      capturedIntake = rec.intake as IntakeSummary;
    }
    if (Array.isArray(rec.personas)) {
      capturedPersonas = rec.personas as PersonaSummary[];
    }
    if (Array.isArray(rec.steps)) {
      capturedSteps = rec.steps as StepTraceItem[];
    }
    if (typeof rec.tier === "number" && !Number.isNaN(rec.tier)) {
      captured.tier = rec.tier;
    }
    if (typeof rec.releaseMode === "string") {
      captured.releaseMode = normalizeReleaseMode(rec.releaseMode, false);
    }
    if (typeof rec.receiptId === "string" && rec.receiptId.length > 0) {
      captured.receiptId = rec.receiptId;
    }
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
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      try {
        extractDleMetadata(await response.clone().json());
      } catch {
        // Ignore clone parse issues on non-JSON error payloads.
      }
    }
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
  let finalCitations: CitationItem[] = [];

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
      const chunkCitations = extractCitations(chunk);
      if (chunkCitations.length > 0) {
        finalCitations = chunkCitations;
      }
      extractDleMetadata(chunk);
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
    finalCitations = extractCitations(response);
    extractDleMetadata(response);
  }

  const finalMode: ReleaseMode =
    toolName && captured.releaseMode === "passthrough" ? "tool_call" : captured.releaseMode;
  const finalText =
    aggregatedText ||
    (toolName ? `Tool call requested: ${toolName}` : defaultNoticeFor(finalMode));

  let receipt: SignedReceipt | null = null;
  let claims: ClaimRow[] = [];
  let objections: PersonaObjectionItem[] = [];
  let terminalU: number | null = null;
  if (captured.receiptId) {
    try {
      receipt = await fetchReceipt(input.baseUrl, input.apiKey, captured.receiptId);
      claims = extractClaimsFromReceipt(receipt);
      objections = extractObjectionsFromReceipt(receipt);
      terminalU = receipt.payload.decision.terminal_u;
    } catch {
      receipt = null;
    }
  }

  const run: ChatRun = {
    id: `assistant-${Date.now()}`,
    role: "assistant",
    model: input.model,
    text: finalText,
    releaseMode: finalMode,
    noticeText: defaultNoticeFor(finalMode, toolName),
    receiptId: captured.receiptId,
    receiptStatus: receipt ? "sealed" : captured.receiptId ? "pending_anchor" : undefined,
    tier: captured.tier,
    toolCallName: toolName,
    sourceCount: finalCitations.length || receipt?.payload.sources.length || undefined,
    citations: finalCitations,
    claims,
    receipt,
    terminalU,
    coordinate: capturedCoordinate,
    graph: capturedGraph,
    runSummary: capturedRunSummary,
    intake: capturedIntake,
    personas: capturedPersonas,
    steps: capturedSteps,
    objections,
    timestamp: new Date().toISOString(),
  };

  return {
    run,
    headers: { ...captured, releaseMode: finalMode },
  };
}
