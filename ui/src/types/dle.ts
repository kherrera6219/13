export type ReleaseMode =
  | "released"
  | "released_advisory"
  | "held"
  | "passthrough"
  | "tool_call"
  | "error";

export type ReceiptStatus = "sealed" | "pending_anchor";

export type ClaimStatus = "supported" | "weak" | "contradicted" | "unverified";

export interface CitationItem {
  index: number;
  title: string;
  uri: string;
  excerpt?: string;
  authorityClass?: string;
}

export interface ClaimRow {
  claimId: string;
  assertion: string;
  binding: boolean;
  hedged: boolean;
  supportZ: number;
  contradictionZ: number;
  status: ClaimStatus;
  sourceIds: string[];
}

export interface SignedReceiptDecision {
  release_mode: string;
  terminal_u: number;
  cusum: number;
  drift_latched: boolean;
  hard_gate: boolean;
}

export interface SignedReceiptPayload {
  schema_version: string;
  run_id: string;
  utc: string;
  policy_sha256: string;
  response_sha256: string;
  profile: string;
  decision: SignedReceiptDecision;
  attempts: Array<{
    attempt_id: string;
    tier: number;
    claims: Array<Record<string, unknown>>;
    objections: Array<Record<string, unknown>>;
  }>;
  sources: Array<Record<string, unknown>>;
  function_invocations: Array<Record<string, unknown>>;
}

export interface SignedReceiptEnvelope {
  digest_sha256: string;
  key_id: string;
  algorithm: string;
  signature_b64: string;
  log_id: string;
  inclusion_proof_ref: string;
  verified_checkpoint_sha256: string;
  anchoring_profile: string;
  verification_level: string;
}

export interface SignedReceipt {
  payload: SignedReceiptPayload;
  envelope: SignedReceiptEnvelope;
}

export interface EvidenceSource {
  sourceId: string;
  title: string;
  authorityClass: string;
  jurisdiction?: string | null;
  validFrom?: string | null;
  validTo?: string | null;
  retainable: boolean;
  contentSha256: string;
  ingestedUtc?: string;
}

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
  citations?: CitationItem[];
  claims?: ClaimRow[];
  receipt?: SignedReceipt | null;
  terminalU?: number | null;
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
