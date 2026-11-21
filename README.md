# dle-middleware

Gemini-compatible middleware that runs the DataLogicEngine 13-axis DVSS design on every request. Applications point an unmodified Gemini SDK at it; it returns governed answers with grounding metadata and a signed receipt, or a held answer with the reason.

Status: pre-phase-1 scaffold. Contracts, specs and plans are in place; code is not yet written. See `HANDOFF.md`.

## Quick look

```python
from google import genai
client = genai.Client(api_key="DLE_CLIENT_KEY", http_options={"base_url": "http://127.0.0.1:8740"})
r = client.models.generate_content(model="dle-13axis-strict", contents="Can we substitute model B on bank 4?")
print(r.text)   # released answer, or a hold notice
```

Response headers carry `X-DLE-Release-Mode`, `X-DLE-Receipt` and `X-DLE-Tier`. Full guide: `docs/guides/developer_quickstart.md`.

## Repository layout

```
contracts/          openapi.yaml, receipt.schema.json (3.8.0), role_artifact.schema.json,
                    functions/ (I/O schemas), prompts/ (model output schemas)
config/             functions.yaml (26 bindings), profiles/, tiers.yaml, notices.yaml,
                    catalog/ (ka100.csv, enterprise_ka114.json: inventory only)
dle/                edge/, host/{workflow,frost,quad,functions,services}, models/, store/
dle/store/migrations/0001_init.sql
offline/            calibrate (O1), registry_release (O2), evaluate (O3)
tests/              unit/, contract/, engines/, gemini_compat/, fixtures/ (frozen), security/, perf/
ui/                 chat test UI (React, Vite, @google/genai) and Storybook
docs/               backlog/, specs/, eval/, guides/, ops/, security/, legal/, plans/, vendor/, templates/
```

## Documents in `docs/`

| Path | What it is | Gap ID |
| --- | --- | --- |
| `backlog/phase1_backlog.md` | Ticketed phase 1 work | G3 |
| `test/gemini_compat_test_plan.md` | Gemini SDK compatibility tests | G4 |
| `vendor/gemini_4_carbon_verification.md` | Verified model facts and prices | G5 |
| `specs/function_specs.md` | DVSS-K01–K12, P01–P14 specifications | G6 |
| `specs/prompts/claim_extractor.md` | Extractor prompt and output contract | G7 |
| `specs/prompts/personas_and_writer.md` | Role and writer prompt contracts | G11 |
| `specs/intake_scoring.md` | How S, R, B, Z are computed | G12 |
| `plans/pilot_migration.md` | Pilot 3.7.1 → 3.8.0 and DVSS IDs | G16 |
| `eval/` | Data plan, rubric, protocol, budget | G17–G20 |
| `guides/` | Developer quick start, admin and hardening guide | G21–G22 |
| `templates/system_card_template.md` | System card, filled after the study | G23 |
| `security/product_security_package.md` | Data flow, egress, SSDF, responsibility matrix | G24 |
| `ops/runbook_and_incident_response.md` | Operations and AI incident playbooks | G25 |
| `legal/third_party_licenses.md` | Dependency license inventory | G26 |

`SECURITY.md` (G26), `AGENTS.md` and `HANDOFF.md` (G2) are at the root. Database DDL (G8) is in `dle/store/migrations/`, the receipt schema (G9) in `contracts/`, notices (G10) in `config/`.
