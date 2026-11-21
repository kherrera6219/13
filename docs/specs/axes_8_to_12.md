# DLE-SPC-004 — Axes 8–12: building the four role profiles and the jurisdiction record

Status: Accepted 2026-11-20 · Owner: AI risk owner · Audience: coding agents
Contracts: `contracts/registry/persona_profile.schema.json`, `contracts/registry/axis12_jurisdiction.schema.json` · Config: `config/personas/conduct.yaml`, `config/reference/manifest.yaml` · White paper: v3.12 §03, §08 · Depends on: DLE-REG-001, DLE-REG-002, DLE-SPC-003

## 1. Decisions this spec implements

| # | Decision | Effect on code |
| --- | --- | --- |
| B1 | The seven profile fields are the MDKF set: job role, education, certifications, skills, job training, career path, related jobs. | `fields` has exactly these keys. "Traits" is not a field. |
| B2 | Traits, guardrails and vetoes are role conduct, kept in `config/personas/conduct.yaml`. | Each profile carries `conduct_ref`; prompts load conduct from config, never from the profile. |
| B3 | Profiles are built per question from the address, then validated against reference lists. | No static profile dictionaries in production paths. Every field item records `derived_from`. |
| B4 | Activation is rule-based (DLE-SPC-003 A6). `synthesis_weight` only orders synthesis. | No cosine-similarity or weight threshold may activate or suppress a role. |
| B5 | Axis 12 = ISO 3166 place plus a separate legal-nexus list, with state specified, unknown or unscoped. | Old forms (`12.<Region>.<Sovereign>.<Agency>`, `ISO.ISO.MUNICIPALITY.ORG.FACILITY`, country/region/city) are input aliases only. |
| B6 | No human names or claimed personal credentials in any profile or output. | Profiles describe a perspective; the validator rejects honorifics and post-nominals. |
| B7 | Axis 9 is the Practitioner role. Qualifications live inside every profile. | Do not use Axis 9 for a free-floating "qualifications" code. |

## 2. Inputs per role

| Axis | Role | Required inputs | Optional inputs | Activation |
| --- | --- | --- | --- | --- |
| 8 | Scholar | ≥1 pillar | branches, Axis 3 links | Every tier (white paper §07 tier table) |
| 9 | Practitioner | ≥1 sector | sector branches, Axis 5 records | Tier 2 and above; all four roles at Tier 3 when B = 1 or Z = 1 |
| 10 | Regulator | ≥1 Axis 6 hub and ≥1 hub arm, plus Axis 12 | Axis 13 as-of | Any binding claim |
| 11 | Harmonizer | ≥1 Axis 7 mesh, plus Axis 12 | hub arms named in the mesh | Any active Axis 7 entry |

A role without its required inputs is not built. If the role is required by its activation rule and the input is missing, the slot state becomes `unknown` and a dependency opens (white paper §03).

## 3. Build order

1. **Resolve Axis 12** (§6). Axes 10 and 11 read it; they cannot be built before it.
2. **Draft** each required profile. For each of the seven fields the builder asks one question (the DSQP chain) using only that role's inputs:

   | Field | Question | Primary source |
   | --- | --- | --- |
   | job_role | What role would hold this perspective for these inputs? | Axis 8: pillar/branch → CIP → SOC. Axis 9: NAICS sector → SOC. Axis 10: hub arm authorities. Axis 11: mesh requirements. |
   | education | What formal preparation fits? | CIP 2020 code (the pillar register's CIP column where present) |
   | certifications | Which credentials or competency tags apply? | Hub arms (Axis 10), mesh requirements (Axis 11), sector practice (Axis 9); otherwise a `competency` tag, never an invented credential |
   | skills | Which skills does this question need? | Branch, records, hub arms, mesh relations |
   | job_training | What practical training applies here and in this jurisdiction? | Branch, sector, Axis 12 |
   | career_path | What progression produces this perspective? | SOC related occupations |
   | related_jobs | Which adjacent roles cross-check it? | CIP-SOC crosswalk, O*NET related occupations |

3. **Validate** (§5). Drop or re-ask any field that fails.
4. **Select** with the white paper §08 rule: mandatory qualifications first as eligibility filters, then `M = 0.25E + 0.45C + 0.30X` with inapplicable terms omitted and weights renormalized. Stable tie-break by profile text hash.
5. **Persist** the winning profile with a new `[ROLE:<axis>.<n>]` ordinal, its inputs and its selection scores, then place it in that role's sealed packet. The receipt records the profile ID.

## 4. Conduct

`config/personas/conduct.yaml` holds each role's traits, `must`, `must_not`, `veto_on` and `synthesis_weight`. The persona prompt (DLE-PRM-002) renders conduct beside the profile. A veto from Axis 10 or 11 becomes a blocking objection in the ledger (DVSS-K12); it is not a vote.

## 5. Validation rules

- Every field item has `derived_from` naming at least one atom or hub arm from the profile's own `inputs`.
- `CIP2020` codes match `^\d{2}(\.\d{2}(\d{2})?)?$`; `SOC2018` and `ONET-SOC` codes match `^\d{2}-\d{4}(\.\d{2})?$`. When the reference files in `config/reference/manifest.yaml` are present, codes must exist in them; when absent, the build logs a warning and the profile cannot support a certified release.
- Certifications for Axis 10 must derive from a hub arm; for Axis 11 from a mesh.
- No human names, honorifics or post-nominals (Dr., Mr., Ms., MD, JD, PhD after a name, and so on) anywhere in the profile.
- Text fields are ≤ 200 characters; a profile is a perspective, not a biography.

## 6. Axis 12 jurisdiction

- **Place:** `iso_3166_1` (required when specified), optional `iso_3166_2` (for example `US-CA`), `locality`, `site`.
- **Legal nexus:** one or more entries, each with `kind` (federal_agency, state_agency, local_government, tribal_government, contract, buyer, site_owner, foreign_authority), `name`, optional `identifier`, a `basis` saying why it applies, and evidence.
- **State:** `specified` requires place and at least one nexus; `unknown` and `unscoped` carry no place. Unknown on a binding question opens a dependency; unscoped is allowed for engineering comparisons (white paper §03).
- **Resolution:** extract place mentions from the question and the Axis 5 records; take nexus from hub arm `jurisdiction` fields, contract records and the buyer. Never infer jurisdiction from the user's location alone.
- **Effect:** Axis 10 and 11 may only apply hub arms and mesh requirements whose `jurisdiction` matches or contains the run's Axis 12 record, and whose Axis 13 interval covers the as-of date.
- IDs `[JUR:12.<n>]` are ordinals in `config/registry/axis12_jurisdictions.jsonl` (empty until D4).

## 7. Tests

`tests/unit/registry/test_axes_8_to_12.py` (T-UNIT-REG-16..22) runs against `tests/fixtures/registry/personas.jsonl` and `axis12_jurisdictions.jsonl`: schemas compile; fixtures validate; role-axis pairing and required inputs; every `derived_from` is within the profile's inputs; Axis 10 certifications come from hub arms; no human names; conduct file covers all four roles and has no activation keys.
