import type {
  ChatRun,
  CitationItem,
  ClaimRow,
  EvidenceSource,
  SignedReceipt,
} from "../types/dle";

export const SAMPLE_CITATIONS: CitationItem[] = [
  {
    index: 1,
    title: "Valve Compliance Spec (§4.2)",
    uri: "dle://sources/src-4b0f0041#c-001",
    authorityClass: "primary_text",
    excerpt:
      "Dual-redundant pressure relief valves certified under ISO 9001 are required for shipping widgets.",
  },
  {
    index: 2,
    title: "Packaging Addendum WH-2026",
    uri: "dle://sources/src-9d1a0022#c-003",
    authorityClass: "binding_instrument",
    excerpt: "All Class-II hazardous assemblies require sealed lot inspection tags before dispatch.",
  },
];

export const SAMPLE_CLAIMS: ClaimRow[] = [
  {
    claimId: "claim-001",
    assertion: "Shipping widgets must include dual-redundant ISO 9001 pressure relief valves.",
    binding: true,
    hedged: false,
    supportZ: 0.94,
    contradictionZ: 0.01,
    status: "supported",
    sourceIds: ["src-4b0f0041#c-001"],
  },
  {
    claimId: "claim-002",
    assertion: "Sealed lot inspection tags must accompany Class-II hazardous dispatches.",
    binding: true,
    hedged: false,
    supportZ: 0.58,
    contradictionZ: 0.08,
    status: "weak",
    sourceIds: ["src-9d1a0022#c-003"],
  },
];

export const SAMPLE_RECEIPT: SignedReceipt = {
  payload: {
    schema_version: "3.8.0",
    run_id: "9cc29cd3-ac19-4929-b8ce-f8894b1b9be2",
    utc: "2026-11-22T22:15:00Z",
    policy_sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    response_sha256: "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
    profile: "strict",
    decision: {
      release_mode: "gate_passed",
      terminal_u: 0.084,
      cusum: 0.034,
      drift_latched: false,
      hard_gate: true,
    },
    attempts: [
      {
        attempt_id: "att-0",
        tier: 1,
        claims: [
          {
            claim_id: "claim-001",
            assertion: "Shipping widgets must include dual-redundant ISO 9001 pressure relief valves.",
            binding: true,
            hedged: false,
            belief: 0.94,
            contradiction: 0.01,
            source_ids: ["src-4b0f0041#c-001"],
          },
          {
            claim_id: "claim-002",
            assertion: "Sealed lot inspection tags must accompany Class-II hazardous dispatches.",
            binding: true,
            hedged: false,
            belief: 0.58,
            contradiction: 0.08,
            source_ids: ["src-9d1a0022#c-003"],
          },
        ],
        objections: [],
      },
    ],
    sources: [
      { source_id: "src-4b0f0041", title: "Valve Compliance Spec (§4.2)", authority_class: "primary_text" },
    ],
    function_invocations: Array.from({ length: 12 }, (_, idx) => ({
      seq: idx + 1,
      dvss_id: `DVSS-K${String(idx + 1).padStart(2, "0")}`,
      outcome: "ok",
    })),
  },
  envelope: {
    digest_sha256: "f1d2d2f924e986ac86fdf7b36c94bcdf32beec15f1d2d2f924e986ac86fdf7b3",
    key_id: "dle-ed25519-001",
    algorithm: "Ed25519",
    signature_b64: "c2lnbmF0dXJlLWJhc2U2NC1wbGFjZWhvbGRlcg==",
    log_id: "local-worm-merkle:chain-default",
    inclusion_proof_ref: "checkpoint:1#seq:1",
    verified_checkpoint_sha256: "9b71d224bd62f3785d96d46ad3ea3d73319bfbc2890caadae2dff72519673ca7",
    anchoring_profile: "local_worm_merkle",
    verification_level: "locally_sealed",
  },
};

export const SAMPLE_HELD_RECEIPT: SignedReceipt = {
  ...SAMPLE_RECEIPT,
  payload: {
    ...SAMPLE_RECEIPT.payload,
    decision: {
      release_mode: "hard_veto_block",
      terminal_u: 0.95,
      cusum: 0.88,
      drift_latched: false,
      hard_gate: false,
    },
    attempts: [
      {
        attempt_id: "att-0",
        tier: 2,
        claims: [
          {
            claim_id: "claim-held-01",
            assertion: "Unverified orbital cargo schedules bypass hazardous compliance.",
            binding: true,
            hedged: false,
            belief: 0.05,
            contradiction: 0.78,
            source_ids: [],
          },
        ],
        objections: [
          {
            objection_id: "obj-contra-1",
            role_axis: 10,
            blocking: true,
            predicate: "contradicts_primary_text",
            state: "open",
          },
        ],
      },
    ],
  },
};

export const SAMPLE_SOURCES: EvidenceSource[] = [
  {
    sourceId: "4b0f0041-5f23-41c2-8722-57b5004793c1",
    title: "Valve Compliance Spec (§4.2)",
    authorityClass: "primary_text",
    jurisdiction: "US-FEDERAL",
    validFrom: "2026-01-01",
    validTo: null,
    retainable: true,
    contentSha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    ingestedUtc: "2026-11-22T20:00:00Z",
  },
  {
    sourceId: "9d1a0022-41cb-4f90-90a2-001122334455",
    title: "Warehouse Substitution SOP-14",
    authorityClass: "binding_instrument",
    jurisdiction: "ISO-9001",
    validFrom: "2026-03-15",
    validTo: "2027-12-31",
    retainable: true,
    contentSha256: "60303ae22b998861bce3b28f33eec1be758a213c86c93c076dbe9f558c11c752",
    ingestedUtc: "2026-11-22T20:15:00Z",
  },
];

export const SAMPLE_GROUNDED_RUN: ChatRun = {
  id: "run-phase2-grounded",
  role: "assistant",
  model: "dle-13axis-strict",
  text: "Dual-redundant pressure relief valves certified under ISO 9001 are required for shipping widgets.",
  releaseMode: "released",
  noticeText: "Verified against 2 configured evidence sources.",
  receiptId: "9cc29cd3-ac19-4929-b8ce-f8894b1b9be2",
  receiptStatus: "sealed",
  tier: 1,
  sourceCount: 2,
  citations: SAMPLE_CITATIONS,
  claims: SAMPLE_CLAIMS,
  receipt: SAMPLE_RECEIPT,
  terminalU: 0.084,
  timestamp: "2026-11-22T22:15:00Z",
};
