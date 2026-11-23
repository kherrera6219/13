import type { ChatRun } from "../types/dle";

export const releasedRun: ChatRun = {
  id: "run-released-001",
  role: "assistant",
  model: "dle-13axis-strict",
  text: "Substitute SKU-4429-B cleanly matches SKU-4429-A under policy WH-2026-Q4 (lot-traceable cold-chain packaging).",
  releaseMode: "released",
  noticeText: "Verified against 2 sources.",
  receiptId: "7a1d2c3e-4f50-4a6b-8c7d-9e0f1a2b3c4d",
  receiptStatus: "sealed",
  tier: 2,
  sourceCount: 2,
  timestamp: "2026-11-22T18:00:00Z",
};

export const advisoryRun: ChatRun = {
  id: "run-advisory-002",
  role: "assistant",
  model: "dle-13axis-advisory",
  text: "Notice: This answer contains claims with weak or conflicting support (run receipt b2e4f6a8-1c3d-4e5f-8a9b-0c1d2e3f4a5b). Verify before acting.",
  releaseMode: "released_advisory",
  noticeText: "Advisory: not fully verified. See flagged claims.",
  receiptId: "b2e4f6a8-1c3d-4e5f-8a9b-0c1d2e3f4a5b",
  receiptStatus: "pending_anchor",
  tier: 1,
  timestamp: "2026-11-22T18:01:00Z",
};

export const heldRun: ChatRun = {
  id: "run-held-003",
  role: "assistant",
  model: "dle-13axis-strict",
  text: "Held: I cannot verify an answer that meets this threshold. Run receipt: c3d4e5f6-7a8b-4c9d-8e0f-1a2b3c4d5e6f.",
  releaseMode: "held",
  noticeText: "Held: missing binding authorization source. Attach current SOP revision to resolve.",
  receiptId: "c3d4e5f6-7a8b-4c9d-8e0f-1a2b3c4d5e6f",
  receiptStatus: "sealed",
  tier: 2,
  timestamp: "2026-11-22T18:02:00Z",
};

export const streamingRun: ChatRun = {
  id: "run-stream-004",
  role: "assistant",
  model: "dle-13axis-strict",
  text: "Verifying claims against warehouse policy index...",
  releaseMode: "released",
  noticeText: "Streaming response in progress; keepalives active.",
  receiptId: null,
  tier: 1,
  streaming: true,
  timestamp: "2026-11-22T18:03:00Z",
};

export const toolCallRun: ChatRun = {
  id: "run-tool-005",
  role: "assistant",
  model: "gemini-4-carbon",
  text: "Tool call requested: lookup_warehouse_lot({\"sku\": \"SKU-4429-A\"})",
  releaseMode: "tool_call",
  noticeText: "Waiting for your app to run lookup_warehouse_lot.",
  receiptId: null,
  toolCallName: "lookup_warehouse_lot",
  tier: null,
  timestamp: "2026-11-22T18:04:00Z",
};

export const errorRun: ChatRun = {
  id: "run-error-006",
  role: "assistant",
  model: "dle-13axis-strict",
  text: "Key not accepted. Check the middleware API key in settings.",
  releaseMode: "error",
  noticeText: "Key not accepted. Check the middleware API key in settings.",
  receiptId: null,
  tier: null,
  errorDetail: "HTTP 401 UNAUTHENTICATED",
  timestamp: "2026-11-22T18:05:00Z",
};
