export type ReleaseMode =
  | "released"
  | "released_advisory"
  | "held"
  | "passthrough"
  | "tool_call"
  | "error";

export type ReceiptStatus = "sealed" | "pending_anchor";

export interface DleHeaders {
  releaseMode: ReleaseMode;
  receiptId: string | null;
  tier: number | null;
  apiVersion: string | null;
}

export interface ChatRun {
  id: string;
  role: "user" | "assistant";
  model: string;
  text: string;
  releaseMode: ReleaseMode;
  noticeText: string;
  receiptId: string | null;
  receiptStatus?: ReceiptStatus;
  tier: number | null;
  streaming?: boolean;
  toolCallName?: string;
  sourceCount?: number;
  errorDetail?: string;
  timestamp: string;
}

export interface HealthStatus {
  status: "ok" | "degraded";
  bind: string;
  modelReachable: boolean;
  nliLoaded: boolean;
  driftLatch: "clear" | "tripped";
  kernelFunctions: number;
  version: string;
}
