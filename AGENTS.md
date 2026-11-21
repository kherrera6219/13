# AGENTS.md — rules for coding agents in this repository

This file is written for AI coding agents (Codex, Claude) working in `dle-middleware`. Read it fully before your first change. Human contributors follow the same rules.

## What this repository is

The DataLogicEngine 13-axis middleware: a Gemini-compatible API that runs every request through the DVSS design (12-step refinement workflow, 10-layer FROST stack, Quad Persona engine, 26 bound functions) before releasing an answer with a signed receipt.

Authoritative sources, in order:
1. `docs/dle-dev-docs/` (exported snapshot of the Software Development Documentation Set; the live doc is the master copy): requirements (SRS), design (SDD), interfaces (ICD), tests (STP). If code and these disagree, the docs win until a reviewed change updates them.
2. `contracts/` (OpenAPI, JSON schemas): the machine-readable contracts. Code is generated from or validated against them.
3. The DataLogicEngine white paper v3.13: design intent. Do not re-derive behavior from older versions or from the 17-axis enterprise product.

## Commands

```bash
uv sync                                # install
uv run ruff format --check . && uv run ruff check .
uv run mypy --strict dle
uv run pytest -q                       # unit, contract, engines, fixtures (fake model)
uv run pytest -q tests/gemini_compat   # official SDKs against a running middleware
uv run pytest -q -m live               # real Gemini calls; needs GEMINI_API_KEY; nightly only
uv run python -m dle.tools.validate_contracts   # OpenAPI + JSON schemas + functions.yaml
npm --prefix ui run lint && npm --prefix ui run test-storybook
```

CI runs on Linux and Windows and fails on errors as well as failures.

## Hard rules

1. **Trace every change.** Each behavior change names the requirement IDs (FR-*, NFR-*, IR-*) it implements, in the docstring and the PR body. Update `docs/traceability/rtm.csv` in the same PR.
2. **Never edit frozen fixtures.** `tests/fixtures/` holds the §18 conformance cases with frozen expected outcomes. A fixture change is its own PR, labeled `fixture-change`, and needs human approval.
3. **Never approve your own PR.** Agent-authored PRs need a reviewer who did not write them.
4. **Functions are dispatched by DVSS ID only.** Call `functions.invoke("DVSS-K05", ctx)`. Never select, import or authorize behavior by a KA number. KA numbers are catalog references (see `config/catalog/`).
5. **Kernel functions are never optional.** Do not add a config switch that disables DVSS-K01–K12.
6. **Only K04, K11 and K12 may produce a hold.** No other code path sets `mode = held`.
7. **One way out.** All outbound HTTP goes through `dle.models.egress.EgressClient`. Importing `httpx`, `requests`, `urllib` or sockets anywhere else fails CI.
8. **No content in logs.** Never log prompt text, response text, passages or keys. Log IDs and hashes.
9. **Append, never overwrite.** Run state, objection ledger and receipts are append-only. No UPDATE or DELETE on those tables outside retention purge.
10. **Do not touch the release rule without the AI risk owner.** Changes to u weights, the cutoff logic, CUSUM parameters, tier table or model pins are major configuration changes (see SDD §9).
11. **Fail closed.** On any unexpected exception in the governed path, return a hold with a receipt. Never return a default score.
12. **Do not block tools.** Client tool and function declarations pass to Gemini unchanged; `functionCall` parts return to the client unchanged (ADR-002).

## Layout

See `README.md`. In short: `dle/edge` (Gemini façade), `dle/host/workflow` (12 steps), `dle/host/frost` (10 layers), `dle/host/quad` (personas), `dle/host/functions` (H16 registry, kernel/, policy/), `dle/host/services` (shared services), `dle/models` (ports and adapters), `dle/store` (SQLite).

## How to pick up work

1. Read `HANDOFF.md` for current state and the active phase.
2. Take the lowest-numbered open ticket in `docs/backlog/` for the active phase whose dependencies are done.
3. Write or extend the test first, then the code.
4. Update `HANDOFF.md` with what you changed, what you learned and what is next.

## Naming and numbering

Follow `docs/standards/naming_and_numbering_conventions.md` (DLE-STD-001) for every identifier, file name, module name, schema field, metric, branch and commit. Never reuse or renumber an ID.

## Style

Python 3.12, full type annotations, Google-style docstrings that name requirement IDs, typed exceptions from `dle.errors`. Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`) with requirement or story IDs in the body. See the style guide (documentation set §14).
