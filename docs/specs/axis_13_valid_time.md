# DLE-SPC-005 — Axis 13: valid time

Status: Accepted 2026-11-20 · Owner: architect · Audience: coding agents
Contract: `contracts/registry/axis13_interval.schema.json` (full record); `contracts/coordinate.schema.json` `axis_13_temporal` (3.7.1 atom) · Code: `dle/temporal/` · White paper: v3.13 §03, §07 · Depends on: DLE-SPC-003, DLE-SPC-004

## 1. Decisions

| # | Decision | Effect on code |
| --- | --- | --- |
| T1 | Every interval is half-open `[start, end)`. `end: null` means open (in force, no known end). | Use `contains()` and `overlaps()` from `dle.temporal`; never hand-write comparisons. |
| T2 | Inclusive source dates ("through December 31") are converted once, on ingest, to an exclusive end. | Store `source_text` and `source_end_inclusive: true`; never convert twice. |
| T3 | Legacy forms are converted on ingest and kept only as `legacy_form`. | `parse_legacy()` handles `13.YYYY.Q`, `[13.YYYY.Q, 13.YYYY.Q]` (end quarter inclusive), `YYYY-MM-DD/YYYY-MM-DD` (end day inclusive), the v3.0 `{effective_start, effective_end, is_active}` shape, and the open sentinels `9999-12-31`, `9999.4`, `13.9999.4`. Anything ambiguous raises `LegacyFormatError`. |
| T4 | Two granularities: `date` (civil dates read in the record's IANA `time_zone`) and `instant` (UTC, ending in `Z`). One interval never mixes them. | Date records need `time_zone`; take it from the Axis 12 place when the source gives none. |
| T5 | Three kinds: `effective` (a rule, contract or edition is in force), `applicability` (an obligation reaches a scope, such as awards after a date), `observation` (a measurement or fact was true from a time). | The Regulator and Harmonizer use `effective` and `applicability`; the Scholar and Practitioner mostly `observation`. |
| T6 | Versions chain with `supersedes` / `superseded_by`. A successor starts exactly where its predecessor ends; versions of one subject never overlap. | A superseded version still governs questions whose as-of date falls in its interval. |
| T7 | Unknown valid time is recorded, not guessed: `determination: unknown`, `start` and `end` null. | It cannot be projected into a coordinate; on a binding claim it opens a dependency (white paper §03). |
| T8 | Each record carries `recorded_at` (when the system learned it), separate from valid time. | Replays can ask "what did we know at time R about time T". |

## 2. Record fields

`interval_id` `[TIME:13.n]` (stored versions only) · `subject` (atom, hub arm or evidence ID) · `claim_scope` · `kind` · `granularity` · `start` · `end` · `time_zone` · `determination` (stated, converted, derived, unknown) · `source_text` · `source_end_inclusive` · `legacy_form` · `supersedes` · `superseded_by` · `recorded_at` · `evidence` (required unless unknown) · `status` (proposed, verified, retired, fixture). The schema is authoritative.

## 3. Coordinate projection

The 3.7.1 coordinate atom is `{claim_scope, effective_start, effective_end, as_of}` with dates only. `project(record, as_of)`:

- copies a date record directly;
- refuses an instant record unless `allow_widen=True`, then floors the start and ceils the end to whole UTC days, never narrowing;
- refuses an unknown record.

Instant precision stays in the full record and in the evidence. Allowing instants in the coordinate is a contract change for a later version, not part of 3.7.1.

## 4. Evaluation rules

1. **As-of date.** Taken from the question when stated ("in 2025", "on the renewal date"); otherwise the run date. Always recorded in the atom and the receipt.
2. **Applicability.** A source applies to a claim only if its `effective` (and, where present, `applicability`) interval contains the as-of date, and its Axis 12 jurisdiction matches (DLE-SPC-004 §6).
3. **Historical and prospective scope** are evaluated separately: a question about last year uses the version in force last year even if it has since been superseded.
4. **Conflicting versions** with overlapping intervals for one subject are a data error: hold the claim and raise a review item.
5. **Source age** is not valid time. Freshness checks use `recorded_at` and source publication data, not the interval.

## 5. Where Axis 13 appears

- Coordinate: one or more atoms per run (per claim scope).
- Axes 3, 6, 7 and 12 records: `valid_from` / `valid_to` follow the same half-open rule (DLE-SPC-003 §3).
- Hub arms: `valid_from` / `valid_to` per arm, so a clause edition can expire while its hub stays.
- Receipts: the as-of date and the interval IDs used.

## 6. Tests

`tests/unit/temporal/test_axis13_intervals.py` (T-UNIT-TMP-01..10): schema and fixtures; rejection of bad records; half-open containment; overlap; inclusive conversion; every legacy form; refusal to guess; version chains; projection validates against the coordinate contract; projection refusals.
