import type { CoordinateSummary, GraphSummary } from "../types/dle";

export const SAMPLE_COORDINATE: CoordinateSummary = {
  manifestSha256: "7a1d4f6a89c210e589c3b88864112aa0be800a48fffa11223344556677889900",
  jurisdictionState: "specified",
  activeAxes: [1, 2, 3, 4, 5, 6, 7, 12, 13],
  activatedRoles: ["scholar", "practitioner", "regulator", "harmonizer"],
  atomsByAxis: {
    axis_1_pillars: ["[PL:1.27.0.0]", "[PL:1.28.0.0]"],
    axis_2_sectors: ["[SECTOR:2.8.0.0]"],
    axis_3_honeycomb: ["[LINK:3.17]"],
    axis_4_branches: ["[BR:4.1.27.1.1]", "[BR:4.2.8.493.4931]"],
    axis_5_nodes: ["[NODE:5.42]", "[NODE:5.43]"],
    axis_6_octopus: ["[HUB:6.7]"],
    axis_7_spiderweb: ["[MESH:7.9]"],
    axis_12_jurisdiction: ["[JUR:12.1]"],
  },
};

export const SAMPLE_GRAPH: GraphSummary = {
  pprEnabled: true,
  hops: 2,
  pprIterations: 28,
  verticesRetained: 7,
  graphSha256: "9d2c5e8a7f14b3c01e4a77b5a1e91c4e9d2c5e8a7f14b3c01e4a77b5a1e91c4e",
  nodes: [
    { vertexId: "[NODE:5.42]", axisId: 5, score: 0.3412, hop: 0, synthetic: false },
    { vertexId: "[NODE:5.43]", axisId: 5, score: 0.2145, hop: 1, synthetic: false },
    { vertexId: "[HUB:6.7]", axisId: 6, score: 0.168, hop: 1, synthetic: false },
    { vertexId: "[MESH:7.9]", axisId: 7, score: 0.1194, hop: 2, synthetic: false },
    {
      vertexId: "[TMP:5.TMP.11111111-2222-4333-8444-555555555555]",
      axisId: 5,
      score: 0.089,
      hop: 1,
      synthetic: true,
    },
  ],
  edges: [
    { src: "[NODE:5.42]", dst: "[NODE:5.43]", edgeType: "honeycomb_link", weight: 1.0 },
    { src: "[HUB:6.7]", dst: "[MESH:7.9]", edgeType: "hub_to_mesh", weight: 1.0 },
    { src: "[PL:1.28.0.0]", dst: "[HUB:6.7]", edgeType: "hub_anchor", weight: 1.0 },
  ],
};

export const SAMPLE_DENSE_ONLY_GRAPH: GraphSummary = {
  pprEnabled: false,
  hops: 1,
  pprIterations: 0,
  verticesRetained: 3,
  graphSha256: "3f79bb7b435b05321651daefd374cdc681dc06faa65e374e38337b88ca046dea",
  nodes: [],
  edges: [],
};
