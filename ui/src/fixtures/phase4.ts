import type {
  PersonaObjectionItem,
  PersonaSummary,
  RunSummary,
  StepTraceItem,
} from "../types/dle";

export const RUN_SUMMARY_TIER1: RunSummary = {
  initialTier: 1,
  finalTier: 1,
  escalated: false,
  escalationReason: null,
  retries: 0,
  maxRetries: 2,
  attemptsCount: 1,
  blindedAssuranceRoles: false,
  consequentialTools: [],
};

export const RUN_SUMMARY_TIER2: RunSummary = {
  initialTier: 2,
  finalTier: 2,
  escalated: false,
  escalationReason: null,
  retries: 1,
  maxRetries: 2,
  attemptsCount: 2,
  blindedAssuranceRoles: false,
  consequentialTools: [],
};

export const RUN_SUMMARY_TIER3: RunSummary = {
  initialTier: 3,
  finalTier: 3,
  escalated: false,
  escalationReason: null,
  retries: 0,
  maxRetries: 2,
  attemptsCount: 1,
  blindedAssuranceRoles: true,
  consequentialTools: ["submit_purchase_order"],
};

export const RUN_SUMMARY_ESCALATED: RunSummary = {
  initialTier: 1,
  finalTier: 2,
  escalated: true,
  escalationReason: "binding_claim_missing_regulator",
  retries: 0,
  maxRetries: 2,
  attemptsCount: 2,
  blindedAssuranceRoles: false,
  consequentialTools: [],
};

const SCHOLAR_PERSONA: PersonaSummary = {
  roleAxis: 8,
  roleName: "scholar",
  profileId: "[ROLE:8.1101.1]",
  mScore: 0.892,
  tokenBudget: 768,
  lowFit: false,
  blinded: false,
  falsificationEnabled: false,
  valid: true,
  claimsCount: 2,
  objectionsCount: 0,
  inputSha256: "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
  outputSha256: "f0e1d2c3b4a5968778695a4b3c2d1e0ffedcba9876543210fedcba9876543210",
  findings: [
    {
      scope: "rf_telemetry",
      assertion: "Candidate B maintains 5 GHz MCS9 throughput under aisle attenuation.",
      passageIds: ["pas-101"],
    },
    {
      scope: "environmental",
      assertion: "Dual diversity antennas remain inside thermal budget at 45C.",
      passageIds: ["pas-102"],
    },
  ],
};

const PRACTITIONER_PERSONA: PersonaSummary = {
  roleAxis: 9,
  roleName: "practitioner",
  profileId: "[ROLE:9.4931.1]",
  mScore: 0.841,
  tokenBudget: 640,
  lowFit: false,
  blinded: false,
  falsificationEnabled: false,
  valid: true,
  claimsCount: 1,
  objectionsCount: 0,
  inputSha256: "11223344556677889900aabbccddeeff00112233445566778899aabbccddeeff",
  outputSha256: "ffeeddccbbaa99887766554433221100ffeeddccbbaa99887766554433221100",
  findings: [
    {
      scope: "field_ops",
      assertion: "Warehouse fork-lift mounting bracket clears rack aisle clearances.",
      passageIds: ["pas-103"],
    },
  ],
};

const REGULATOR_PERSONA: PersonaSummary = {
  roleAxis: 10,
  roleName: "regulator",
  profileId: "[ROLE:10.1310.1]",
  mScore: 0.875,
  tokenBudget: 768,
  lowFit: false,
  blinded: false,
  falsificationEnabled: false,
  valid: true,
  claimsCount: 1,
  objectionsCount: 1,
  inputSha256: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
  outputSha256: "9876543210fedcba9876543210fedcba9876543210fedcba9876543210fedcba",
  findings: [
    {
      scope: "governance",
      assertion: "Change Order sign-off requires buyer countersignature prior to PO execution.",
      passageIds: ["pas-104"],
    },
  ],
};

const HARMONIZER_PERSONA: PersonaSummary = {
  roleAxis: 11,
  roleName: "harmonizer",
  profileId: "[ROLE:11.0001.1]",
  mScore: 0.445,
  tokenBudget: 512,
  lowFit: true,
  blinded: false,
  falsificationEnabled: true,
  valid: true,
  claimsCount: 1,
  objectionsCount: 0,
  inputSha256: "00112233445566778899aabbccddeeff112233445566778899aabbccddeeff00",
  outputSha256: "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
  findings: [
    {
      scope: "falsification",
      assertion: "Tested counterexample: single-source outage leaves legacy AP sparing depleted.",
      passageIds: ["pas-105"],
    },
  ],
};

export const PERSONAS_SCHOLAR_ONLY: PersonaSummary[] = [SCHOLAR_PERSONA];

export const PERSONAS_SCHOLAR_PRACTITIONER: PersonaSummary[] = [
  SCHOLAR_PERSONA,
  PRACTITIONER_PERSONA,
];

export const PERSONAS_ALL_FOUR: PersonaSummary[] = [
  SCHOLAR_PERSONA,
  PRACTITIONER_PERSONA,
  REGULATOR_PERSONA,
  HARMONIZER_PERSONA,
];

export const PERSONAS_BLINDED: PersonaSummary[] = [
  { ...REGULATOR_PERSONA, blinded: true, falsificationEnabled: true },
  { ...HARMONIZER_PERSONA, blinded: true },
  { ...SCHOLAR_PERSONA, falsificationEnabled: true },
  { ...PRACTITIONER_PERSONA, falsificationEnabled: true },
];

export const OBJECTIONS_OPEN_BLOCKING: PersonaObjectionItem[] = [
  {
    objectionId: "obj-reg-att-1",
    roleAxis: 10,
    proposalId: "prop-1",
    blocking: true,
    predicate: "missing_buyer_countersignature_for_change_order",
    state: "open",
    closureEvidence: [],
  },
];

export const OBJECTIONS_CLOSED_VERIFIER: PersonaObjectionItem[] = [
  {
    objectionId: "obj-reg-att-1",
    roleAxis: 10,
    proposalId: "prop-1",
    blocking: true,
    predicate: "missing_buyer_countersignature_for_change_order",
    state: "closed",
    closureEvidence: ["claim-buyer-signoff-verified", "pas-104"],
  },
];

const BASE_ATT1_STEPS: StepTraceItem[] = [
  {
    stepId: "s01_ingest",
    layerId: "l01_grounding",
    attemptId: "att-1",
    event: "initial",
    status: "ok",
    dvssIds: ["DVSS-K01", "DVSS-P13", "DVSS-K10"],
    durationMs: 2.4,
  },
  {
    stepId: "s02_anchor",
    layerId: "l01_grounding",
    attemptId: "att-1",
    event: "initial",
    status: "ok",
    dvssIds: ["DVSS-K02"],
    durationMs: 4.1,
  },
  {
    stepId: "s03_screen",
    layerId: "l02_retrieval",
    attemptId: "att-1",
    event: "initial",
    status: "ok",
    dvssIds: ["DVSS-K06", "DVSS-P01"],
    durationMs: 1.9,
  },
  {
    stepId: "s04_retrieve",
    layerId: "l02_retrieval",
    attemptId: "att-1",
    event: "initial",
    status: "ok",
    dvssIds: ["DVSS-K07", "DVSS-K05"],
    durationMs: 11.2,
  },
  {
    stepId: "s05_deliberate",
    layerId: "l03_persona_selection",
    attemptId: "att-1",
    event: "initial",
    status: "ok",
    dvssIds: ["DVSS-K03", "DVSS-P08", "DVSS-P10", "DVSS-P11"],
    durationMs: 8.6,
  },
  {
    stepId: "s05_deliberate",
    layerId: "l04_deliberation",
    attemptId: "att-1",
    event: "initial",
    status: "ok",
    dvssIds: ["DVSS-P11"],
    durationMs: 14.3,
  },
  {
    stepId: "s06_reconcile",
    layerId: "l05_arbitration",
    attemptId: "att-1",
    event: "initial",
    status: "ok",
    dvssIds: ["DVSS-P02"],
    durationMs: 2.2,
  },
  {
    stepId: "s07_crosswalk",
    layerId: "l06_alignment",
    attemptId: "att-1",
    event: "initial",
    status: "ok",
    dvssIds: ["DVSS-P06"],
    durationMs: 3.1,
  },
  {
    stepId: "s08_scope",
    layerId: "l07_scope",
    attemptId: "att-1",
    event: "initial",
    status: "ok",
    dvssIds: ["DVSS-K06", "DVSS-P01"],
    durationMs: 1.7,
  },
  {
    stepId: "s09_verify_authority",
    layerId: "l08_verification",
    attemptId: "att-1",
    event: "initial",
    status: "ok",
    dvssIds: ["DVSS-P04", "DVSS-P13", "DVSS-K05"],
    durationMs: 9.8,
  },
  {
    stepId: "s10_score",
    layerId: "l08_verification",
    attemptId: "att-1",
    event: "initial",
    status: "ok",
    dvssIds: ["DVSS-K12", "DVSS-K08"],
    durationMs: 2.0,
  },
  {
    stepId: "s11_refine_decide",
    layerId: "l09_decision",
    attemptId: "att-1",
    event: "initial",
    status: "gate_passed",
    dvssIds: ["DVSS-P12", "DVSS-K04", "DVSS-K11"],
    durationMs: 1.8,
  },
  {
    stepId: "s12_seal",
    layerId: "l10_receipt",
    attemptId: "att-1",
    event: "initial",
    status: "released",
    dvssIds: ["DVSS-K11"],
    durationMs: 3.5,
  },
];

export const STEPS_STRAIGHT: StepTraceItem[] = BASE_ATT1_STEPS;

export const STEPS_ONE_RETRY: StepTraceItem[] = [
  ...BASE_ATT1_STEPS.slice(0, 11),
  {
    stepId: "s11_refine_decide",
    layerId: "l09_decision",
    attemptId: "att-1",
    event: "initial",
    status: "retry",
    dvssIds: ["DVSS-K09"],
    durationMs: 1.5,
  },
  {
    stepId: "s04_retrieve",
    layerId: "l02_retrieval",
    attemptId: "att-2",
    event: "retry",
    status: "ok",
    dvssIds: ["DVSS-K07", "DVSS-K05"],
    durationMs: 12.6,
  },
  {
    stepId: "s10_score",
    layerId: "l08_verification",
    attemptId: "att-2",
    event: "retry",
    status: "ok",
    dvssIds: ["DVSS-K12", "DVSS-K08"],
    durationMs: 2.1,
  },
  {
    stepId: "s11_refine_decide",
    layerId: "l09_decision",
    attemptId: "att-2",
    event: "retry",
    status: "gate_passed",
    dvssIds: ["DVSS-P12", "DVSS-K04", "DVSS-K11"],
    durationMs: 1.9,
  },
  {
    stepId: "s12_seal",
    layerId: "l10_receipt",
    attemptId: "att-2",
    event: "retry",
    status: "released",
    dvssIds: ["DVSS-K11"],
    durationMs: 3.2,
  },
];

export const STEPS_TWO_RETRIES: StepTraceItem[] = [
  ...STEPS_ONE_RETRY.slice(0, 14),
  {
    stepId: "s11_refine_decide",
    layerId: "l09_decision",
    attemptId: "att-2",
    event: "retry",
    status: "retry",
    dvssIds: ["DVSS-K09"],
    durationMs: 1.4,
  },
  {
    stepId: "s04_retrieve",
    layerId: "l02_retrieval",
    attemptId: "att-3",
    event: "retry",
    status: "ok",
    dvssIds: ["DVSS-K07", "DVSS-K05"],
    durationMs: 10.9,
  },
  {
    stepId: "s11_refine_decide",
    layerId: "l09_decision",
    attemptId: "att-3",
    event: "retry",
    status: "gate_held",
    dvssIds: ["DVSS-K09", "DVSS-K04", "DVSS-K11"],
    durationMs: 1.8,
  },
  {
    stepId: "s12_seal",
    layerId: "l10_receipt",
    attemptId: "att-3",
    event: "retry",
    status: "held",
    dvssIds: ["DVSS-K11"],
    durationMs: 3.6,
  },
];

export const STEPS_ESCALATION: StepTraceItem[] = [
  ...BASE_ATT1_STEPS.slice(0, 11),
  {
    stepId: "s11_refine_decide",
    layerId: "l09_decision",
    attemptId: "att-1",
    event: "initial",
    status: "escalated_tier_2",
    dvssIds: ["DVSS-P07"],
    durationMs: 1.6,
  },
  {
    stepId: "s05_deliberate",
    layerId: "l04_deliberation",
    attemptId: "att-2",
    event: "tier_escalation",
    status: "ok",
    dvssIds: ["DVSS-K03", "DVSS-P08"],
    durationMs: 15.1,
  },
  {
    stepId: "s11_refine_decide",
    layerId: "l09_decision",
    attemptId: "att-2",
    event: "tier_escalation",
    status: "gate_passed",
    dvssIds: ["DVSS-P12", "DVSS-K04", "DVSS-K11"],
    durationMs: 2.0,
  },
  {
    stepId: "s12_seal",
    layerId: "l10_receipt",
    attemptId: "att-2",
    event: "tier_escalation",
    status: "released",
    dvssIds: ["DVSS-K11"],
    durationMs: 3.4,
  },
];

export const STEPS_PARKED_TOOL: StepTraceItem[] = [
  ...BASE_ATT1_STEPS.slice(0, 3),
  {
    stepId: "s04_retrieve",
    layerId: "l02_retrieval",
    attemptId: "att-1",
    event: "initial",
    status: "parked_tool_call",
    dvssIds: ["DVSS-K05"],
    durationMs: 4.5,
  },
];
