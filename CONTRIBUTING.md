# Contributing

Applies to people and coding agents. Agents also follow `AGENTS.md`.

## Workflow

1. Trunk-based: branch from `main` as `<type>/<ticket-id>-<slug>` (for example `feat/P1-08-session-resolver`).
2. One ticket per pull request; keep PRs under about 400 changed lines excluding generated files.
3. Write or extend the test first. Every behavior change names its requirement IDs.
4. Open the PR with the template filled in. CI must be green on Linux and Windows.
5. One approving review from someone who did not author the change. Changes to `contracts/`, `config/profiles/`, `config/tiers.yaml`, `config/model_pins.yaml` or the release path also need the owner listed in `CODEOWNERS`.
6. Squash-merge with a Conventional Commit message.

## Naming and numbering

All identifiers, file names and IDs follow `docs/standards/naming_and_numbering_conventions.md` (DLE-STD-001).

## Commit messages

[Conventional Commits 1.0](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `build:`, `ci:`, `chore:`. Breaking changes use `!` and a `BREAKING CHANGE:` footer. Put requirement or story IDs in the body: `Implements: FR-SES-01, FR-SES-03`.

## Versioning and changelog

[Semantic Versioning 2.0](https://semver.org/). A change to the wire contract, receipt schema or release rule is a major version. Record every user-visible change in `CHANGELOG.md` under `Unreleased`, following [Keep a Changelog](https://keepachangelog.com/).

## Architecture decisions

Significant decisions get an ADR in `docs/adr/`, copied from `docs/adr/000-template.md` (MADR format), named `docs/adr/<nnn>-<kebab-title>.md`, numbered in sequence and never deleted; a reversed decision is marked `Superseded by ADR-nnn`.

## Definition of done

See the Software Development Plan (documentation set §2). In short: tests on both OSes, lint and strict types clean, no new SAST/SCA/secret findings, fixtures untouched, docs and RTM updated, independent review.

## Code of conduct

Be direct, specific and kind in review. Review the change, not the author.
