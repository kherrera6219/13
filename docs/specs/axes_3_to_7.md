# DLE-SPC-003 — Axes 3–7: records, generation and traversal

Status: Accepted 2026-11-20 · Owner: registry owner · Audience: coding agents
Contracts: `contracts/registry/axis{3,4,5,6,7}_*.schema.json` · Registries: `config/registry/` · White paper: v3.11 §03, §05, §06, Appendix A

## 1. Decisions this spec implements

| # | Decision | Effect on code |
| --- | --- | --- |
| A1 | Axis 1 stops at the pillar. All drill-down beneath a pillar or sector is Axis 4. | Never emit `[PL:1.<p>.<m>…]` with a non-zero member. Pillar atoms are `[PL:1.<p>.0.0]`. |
| A2 | Axis 4 depth is dynamic (1–7 levels). No fixed 4×4×4×4 fan-out. | Branch generator stops when the question is specific enough or at depth 7. |
| A3 | Axis 5 covers both permanent records and intersections; session nodes use `TMP`. | `kind` is `record` or `intersection`; session nodes follow the coordinate schema's TMP variant. |
| A4 | Axis 6 = one concept fanned out to rule sources. Axis 7 = typed overlap, conflict or dependency among requirements. | Separate record types; neither is a "regulation level" or "internal policy" bucket. |
| A5 | Axis 3 is a typed, evidence-backed edge, not a composite code. | Link IDs are opaque ordinals; meaning lives in subject, predicate, object. |
| A6 | Role activation is rule-based. | Any binding claim activates Axis 10. Any active Axis 7 entry activates Axis 11. No degree or density thresholds. |

## 2. What is stored and what is generated

| Axis | Stored registry | Generated at query time | Can support a binding claim |
| --- | --- | --- | --- |
| 3 Honeycomb | `axis3_links.jsonl` | Candidate links proposed by the model | Only `verified` links |
| 4 Branch | `axis4_branches.jsonl` (promoted branches only) | Candidate members beneath a pillar or sector | Only `verified` branches |
| 5 Crossroads | `axis5_nodes.jsonl` | `TMP` nodes for the session | Only `verified` permanent nodes, or a TMP node whose every claim cites retrieved evidence |
| 6 Octopus | `axis6_hubs.jsonl` | none | Only `verified` hubs and arms |
| 7 Spiderweb | `axis7_meshes.jsonl` | none | Only `verified` meshes |

Status values: `proposed` (discovery only), `verified` (may anchor), `retired` (kept for replay, never retrieved), `fixture` (tests only; the loader rejects fixture records outside tests).

## 3. Record formats

The JSON Schemas are authoritative. Summary:

- **Axis 3 link** `[LINK:3.n]`: `subject`, `predicate` (requires, supplies, depends_on, constrains, uses_method_of, is_analogous_to, applies_to, part_of), `object`, `scope`, `cost > 0`, at least one `evidence` item, `status`, `owner`, `valid_from`/`valid_to`, optional `jurisdiction`. Traverse either way; keep the stored direction when reading the predicate.
- **Axis 4 branch**: `[BR:4.1.<pillar>.<i>…]` under a pillar, `[BR:4.2.<sector>.<naics…>]` under a sector. Sector branches reuse NAICS 2022 codes as path components and must carry `naics_2022`. `parent` is null at the first level. `depth` 1–7.
- **Axis 5 node** `[NODE:5.n]`: `kind`, `label`, `anchors` (pillar, sector and branch atoms), `via_links` (required for intersections), optional `evidence`.
- **Axis 6 hub** `[HUB:6.n]`: `concept`, `definition`, `arms[]`. Each arm names `authority`, `instrument`, `citation`, `edition`, `relation` (defines, uses, requires, permits, prohibits, exempts) and evidence. Record the edition with every citation.
- **Axis 7 mesh** `[MESH:7.n]`: `requirements[]` (hub arms as `[HUB:6.n]#arm-id` or `CITE:<authority> <citation>`), `relations[]` of type equivalent, overlaps, conflicts, depends_on or stricter_than, each with evidence.

IDs are ordinals, assigned on promotion, never reused or renumbered (DLE-STD-001).

## 4. Generation rules (Axes 4 and 5)

1. **Anchor.** Intake fixes Axis 1 pillars and Axis 2 sector (DLE-REG-001, DLE-REG-002).
2. **Drill down (Axis 4).** Look up promoted branches under the anchor first. If none fits, the model proposes candidate members one level at a time. Each candidate becomes a session `TMP` node labelled with the member name and anchored to its parent (the pillar, sector or a promoted branch). It is not an Axis 4 atom until promoted. Descend while the question is broader than the current node; climb back one level if a pass returns too little. Stop at depth 7.
3. **Sector drill-down** follows the NAICS 2022 hierarchy (subsector → industry group → industry). Do not invent sector branches; take codes from the pinned NAICS edition.
4. **Crossroads (Axis 5).** Where a drill-down path meets an Axis 3 link, reuse a permanent node if one exists with the same anchors and links; otherwise create a session TMP node with `via_links`.
5. **Session nodes** are deleted when the run is sealed. A durable citation binds evidence, never a TMP address.

## 5. Traversal order and distance

Per attempt, after anchoring: Axis 4 (vertical) → Axis 3 (lateral) → Axis 5 (materialize) → Axis 6 (fan out from concepts found) → Axis 7 (mesh across the requirements found). Distance for pruning and diffusion: `d(i,j) = d_tree(i,j) + w3 · honeycomb_hops(i,j) + w67 · crosswalk_cost(i,j)` with `w3, w67 > 0` from `config/tiers.yaml`. Only `verified` records (and `proposed` records flagged discovery-only) enter retrieval; `retired` and `fixture` never do in production.

## 6. Role activation

- Axis 6 entries feed the Axis 10 Regulator packet. Any binding claim activates Axis 10 at the run's tier (white paper §07).
- An active Axis 7 entry activates the Axis 11 Harmonizer, which receives the mesh relations and must address every `conflicts` and `depends_on` relation.

## 7. How the registries grow

1. A run may emit proposals: a new link, a branch candidate that recurred, a hub arm, a mesh relation. Each proposal carries its evidence and the run ID.
2. Proposals land in a review queue with `status: proposed`; they may be used for discovery only.
3. A reviewer verifies the evidence and promotes the record through a governed registry release (white paper §06, "Adding a subject area"): new ordinal, manifest digest, calibration check.
4. A record whose evidence lapses (Axis 13 `valid_to`, superseded edition) moves to `retired`.

## 8. Seed status

Production registries are empty. `tests/fixtures/registry/` holds the warehouse substitution case from the white paper as `fixture` records. Real seeding needs decision D4 (pilot domain) and the G15 corpus plan.

## 9. Tests

`tests/unit/registry/test_axes_3_to_7.py` (T-UNIT-REG-09..15): schemas compile; fixtures validate; every atom resolves to a registered pillar, sector or record; intersections cite existing links; mesh requirements resolve to hub arms; production files hold no fixture records.
