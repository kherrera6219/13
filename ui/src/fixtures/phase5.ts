import type {
  ConsequentialFunctionItem,
  CostByTierDay,
  HealthStatus,
} from "../types/dle";

export const HEALTH_ALL_GREEN: HealthStatus = {
  status: "ok",
  bind: "127.0.0.1:8740",
  modelReachable: true,
  nliLoaded: true,
  driftLatch: "clear",
  kernelFunctions: 12,
  version: "0.1.0",
};

export const HEALTH_MODEL_UNREACHABLE: HealthStatus = {
  status: "degraded",
  bind: "127.0.0.1:8740",
  modelReachable: false,
  nliLoaded: true,
  driftLatch: "clear",
  kernelFunctions: 12,
  version: "0.1.0",
};

export const HEALTH_NLI_NOT_LOADED: HealthStatus = {
  status: "degraded",
  bind: "127.0.0.1:8740",
  modelReachable: true,
  nliLoaded: false,
  driftLatch: "clear",
  kernelFunctions: 12,
  version: "0.1.0",
};

export const HEALTH_DRIFT_LATCH_ON: HealthStatus = {
  status: "degraded",
  bind: "127.0.0.1:8740",
  modelReachable: true,
  nliLoaded: true,
  driftLatch: "tripped",
  kernelFunctions: 12,
  version: "0.1.0",
};

export const FLAGS_EMPTY: ConsequentialFunctionItem[] = [];

export const FLAGS_POPULATED: ConsequentialFunctionItem[] = [
  {
    name: "submit_purchase_order",
    reason: "Creates a binding financial commitment requiring Regulator review.",
  },
  {
    name: "disburse_escrow",
    reason: "Initiates external payment disbursement under treasury controls.",
  },
];

export const COST_ONE_WEEK: CostByTierDay[] = [
  {
    date: "2026-11-17",
    tier1Usd: 0.042,
    tier2Usd: 0.088,
    tier3Usd: 0.031,
    totalUsd: 0.161,
    runsByTier: { "1": 18, "2": 9, "3": 2 },
  },
  {
    date: "2026-11-18",
    tier1Usd: 0.055,
    tier2Usd: 0.091,
    tier3Usd: 0.045,
    totalUsd: 0.191,
    runsByTier: { "1": 21, "2": 10, "3": 3 },
  },
  {
    date: "2026-11-19",
    tier1Usd: 0.039,
    tier2Usd: 0.072,
    tier3Usd: 0.028,
    totalUsd: 0.139,
    runsByTier: { "1": 15, "2": 8, "3": 2 },
  },
  {
    date: "2026-11-20",
    tier1Usd: 0.048,
    tier2Usd: 0.105,
    tier3Usd: 0.052,
    totalUsd: 0.205,
    runsByTier: { "1": 19, "2": 11, "3": 4 },
  },
  {
    date: "2026-11-21",
    tier1Usd: 0.051,
    tier2Usd: 0.095,
    tier3Usd: 0.04,
    totalUsd: 0.186,
    runsByTier: { "1": 20, "2": 9, "3": 3 },
  },
  {
    date: "2026-11-22",
    tier1Usd: 0.044,
    tier2Usd: 0.081,
    tier3Usd: 0.033,
    totalUsd: 0.158,
    runsByTier: { "1": 16, "2": 8, "3": 2 },
  },
  {
    date: "2026-11-23",
    tier1Usd: 0.06,
    tier2Usd: 0.11,
    tier3Usd: 0.049,
    totalUsd: 0.219,
    runsByTier: { "1": 24, "2": 12, "3": 3 },
  },
];

export const COST_TIER3_SPIKE: CostByTierDay[] = [
  ...COST_ONE_WEEK.slice(0, 6),
  {
    date: "2026-11-23",
    tier1Usd: 0.03,
    tier2Usd: 0.08,
    tier3Usd: 0.64,
    totalUsd: 0.75,
    runsByTier: { "1": 10, "2": 7, "3": 32 },
  },
];
