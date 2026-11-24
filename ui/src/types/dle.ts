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

export interface CoordinateSummary {
  manifestSha256: string;
  jurisdictionState: string;
  activeAxes: number[];
  activatedRoles: string[];
  atomsByAxis: Record<string, string[]>;
}

export interface GraphNodeItem {
  vertexId: string;
  axisId: number;
  score: number;
  hop: number;
  synthetic: boolean;
}

export interface GraphEdgeItem {
  src: string;
  dst: string;
  edgeType: string;
  weight: number;
}

export interface GraphSummary {
  pprEnabled: boolean;
  hops: number;
  pprIterations: number;
  verticesRetained: number;
  graphSha256: string;
  nodes: GraphNodeItem[];
  edges: GraphEdgeItem[];
}

export interface RunSummary {
  initialTier: number;
  finalTier: number;
  escalated: boolean;
  escalationReason: string | null;
  retries: number;
  maxRetries: number;
  attemptsCount: number;
  blindedAssuranceRoles: boolean;
  consequentialTools: string[];
  sEff?: number;
  modelCallsUsed?: number;
  modelCallBudget?: number;
  costUsd?: number;
}

export interface IntakeSummary {
  promptVersion: string;
  d: number;
  rRules: number;
  rModel: number;
  rFinal: number;
  m: number;
  b: number;
  z: number;
  s: number;
  sEff: number;
  tier: number;
  activeRoles: string[];
  startingHops: number;
  maxModelCalls: number;
  maxModelCallsEscalated: number;
  pillarCount: number;
  deonticHits: string[];
  rRuleReasons: string[];
  zMaxCosine: number;
  zMatchedCentroid: string | null;
  modelBindingFlag: boolean;
}

export interface ConsequentialFunctionItem {
  name: string;
  reason: string;
}

export interface FunctionFlagsResponse {
  schemaVersion: string;
  consequentialFunctions: ConsequentialFunctionItem[];
}

export interface CostByTierDay {
  date: string;
  tier1Usd: number;
  tier2Usd: number;
  tier3Usd: number;
  totalUsd: number;
  runsByTier: Record<string, number>;
}

export interface PersonaFindingItem {
  scope: string;
  assertion: string;
  passageIds: string[];
}

export interface PersonaSummary {
  roleAxis: number;
  roleName: string;
  profileId: string;
  mScore: number;
  tokenBudget: number;
  lowFit: boolean;
  blinded: boolean;
  falsificationEnabled: boolean;
  valid: boolean;
  claimsCount: number;
  objectionsCount: number;
  inputSha256: string;
  outputSha256: string;
  findings?: PersonaFindingItem[];
}

export interface PersonaObjectionItem {
  objectionId: string;
  roleAxis: number;
  proposalId: string;
  blocking: boolean;
  predicate: string;
  state: "open" | "closed";
  closureEvidence: string[];
}

export interface StepTraceItem {
  stepId: string;
  layerId: string;
  attemptId: string;
  event: string;
  status: string;
  dvssIds: string[];
  durationMs: number;
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
  coordinate?: CoordinateSummary | null;
  graph?: GraphSummary | null;
  runSummary?: RunSummary | null;
  intake?: IntakeSummary | null;
  personas?: PersonaSummary[];
  steps?: StepTraceItem[];
  objections?: PersonaObjectionItem[];
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
