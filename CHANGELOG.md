# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `docs/adr/011-docker-browser-and-gemini-cloud.md` (ADR-011), `docs/plans/multi_phase_build_plan.md` (`DLE-PLN-002`), `Dockerfile`, `docker-compose.yml`, `.dockerignore`, and `.env.example`.
- `gemini-4-neon` and `gemini-embedding-001` model pins and pricing in `config/model_pins.yaml` and `docs/vendor/gemini_4_carbon_verification.md`, verified by `T-UNIT-REG-29`.
- `.gitattributes`, `.python-version` (`3.12`), Hatchling build config in `pyproject.toml`, and v3.13 white paper copies under `docs/whitepaper/`.

### Fixed
- Scoped Ruff format and lint checks in `.github/workflows/ci.yml` to `dle tests`.
- Flattened nested `dle-middleware/dle-middleware` directory into a single repository root and initialized Git on `main`.
- Added `pytest-cov` and Windows environment marker for `mutmut` in `pyproject.toml`, raised `.pre-commit-config.yaml` file size ceiling to `2500` KB, and gated Phase 1+ steps in `.github/workflows/ci.yml` so scaffold CI runs green.
- Removed unused `pytest` import in `tests/unit/registry/test_contracts_and_config.py`.
- Separated `tests/fixtures/coordinate_warehouse.json` (white paper §04b warehouse case) and `tests/fixtures/coordinate_storage_procurement.json` (2027 energy storage case).
- Reconciled `contracts/receipt.schema.json` 3.8.0 (`decision.profile` and `cancelled`), `dle/store/migrations/0001_init.sql` (`cancelled`), `config/profiles/advisory.yaml` (`drift_latched`), and documented the canonical `DVSS-K11` release-mode mapping in `docs/specs/function_specs.md`.
- Added `distance_weights` (`w3`, `w67`) to `config/tiers.yaml` per DLE-SPC-003 §5.
- Aligned `docs/eval/study_protocol.md` hypotheses H1–H4 with white paper §17 and separated middleware endpoints M1–M2.
- Verified ISCED-F 2013 codes for `PL109` (`0413; 0417`) and `PL114` (`0314`) in `config/registry/axis1_pillars.csv`.
- Synced Markdown design docs (`DLE_Application_Blueprint.md`, `DLE_Software_Development_Documentation_Set.md`), `docs/backlog/phase1_backlog.md` (`P1-20`), `README.md`, `docs/INDEX.md`, and `docs/standards/naming_and_numbering_conventions.md` to v3.13.
- Added `tests/unit/registry/test_contracts_and_config.py` (`T-UNIT-REG-23..28`) and updated `docs/traceability/rtm.csv`.

### Added
- Axis 1 pillar register `config/registry/axis1_pillars.csv` (DLE-REG-001): 114 approved top-level pillars, 4 aliases resolved to their earlier IDs.
- Axis 2 sector register `config/registry/axis2_sectors.csv` and crosswalk `axis2_crosswalk.csv` (DLE-REG-002), NAICS 2022 authority.
- Naming conventions: `PL<nnn>` pillar and `SC<nn>` sector IDs.
- Registry integrity tests `tests/unit/registry/test_axis_registries.py` (T-UNIT-REG-01..08).
- Axes 3–7 spec `docs/specs/axes_3_to_7.md` (DLE-SPC-003), record schemas `contracts/registry/`, empty production registries, warehouse fixtures and tests T-UNIT-REG-09..15.
- Axes 8–12 spec `docs/specs/axes_8_to_12.md` (DLE-SPC-004), persona profile and jurisdiction schemas, `config/personas/conduct.yaml`, `config/reference/manifest.yaml`, fixtures and tests T-UNIT-REG-16..22.
- Axis 13 spec `docs/specs/axis_13_valid_time.md` (DLE-SPC-005), `contracts/registry/axis13_interval.schema.json`, interval library `dle/temporal/`, fixtures and tests T-UNIT-TMP-01..10.

### Added
- Repository scaffold, agent rules, contribution guide, CI with SAST, SCA, secret scan and SBOM.
- `contracts/openapi.yaml` (dle-api 1.0), `contracts/receipt.schema.json` 3.8.0 with `profile` and `function_invocations`.
- `config/functions.yaml` with 26 DVSS bindings; release profiles strict, advisory, kernel_only, kernel_plus_policy.
- Database migration `0001_init.sql`.
- Specifications, plans, guides and policies listed in `README.md`.
