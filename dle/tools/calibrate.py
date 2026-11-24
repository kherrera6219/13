"""CLI for offline CRC + CUSUM calibration and artifact verification (``O1``, ``DVSS-P14``)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from dle.config import load_config
from dle.errors import CalibrationError, ContaminationError
from dle.host.services.calibration import (
    load_calibration_artifact,
    run_offline_calibration,
)


def _default_model_versions(config_dir: Path) -> dict[str, str]:
    config = load_config(config_dir)
    versions: dict[str, str] = {}
    for model_id in config.model_pins.jobs.values():
        canonical = model_id.removeprefix("models/")
        if canonical not in versions:
            versions[canonical] = f"{canonical}-001"
    return versions


def _parse_model_version_overrides(raw_items: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in raw_items:
        if "=" not in item:
            raise CalibrationError(f"invalid --model-version {item!r}; expected model=version")
        model_id, version = item.split("=", 1)
        clean_id = model_id.strip().removeprefix("models/")
        clean_ver = version.strip()
        if not clean_id or not clean_ver:
            raise CalibrationError(f"invalid --model-version {item!r}; empty key or value")
        parsed[clean_id] = clean_ver
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    """Execute ``O1`` calibration or verify an existing calibration artifact."""
    parser = argparse.ArgumentParser(
        prog="dle-calibrate",
        description="Run offline CRC + CUSUM calibration (O1 / DVSS-P14) or verify an artifact.",
    )
    parser.add_argument(
        "--verify-only",
        type=Path,
        default=None,
        help="Verify schema, JCS digest, approval, and kappa on an existing calibration JSON.",
    )
    parser.add_argument(
        "--pilot",
        type=Path,
        default=None,
        help="Path to graded calibration JSONL file.",
    )
    parser.add_argument(
        "--heldout-registry",
        type=Path,
        default=Path("offline/registry/heldout_hashes.json"),
        help="Path to sealed heldout_hashes.json.",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path("config"),
        help="Path to middleware configuration directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for the calibration artifact JSON.",
    )
    parser.add_argument(
        "--p14-output",
        type=Path,
        default=None,
        help="Optional output path for the DVSS-P14 structured output JSON.",
    )
    parser.add_argument(
        "--artifact-id",
        type=str,
        default="cal-phase6-v1",
        help="Identifier recorded in the calibration artifact.",
    )
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--grid-step", type=float, default=0.005)
    parser.add_argument("--drift-delta", type=float, default=0.02)
    parser.add_argument("--target-arl", type=int, default=1000)
    parser.add_argument("--min-kappa", type=float, default=0.6)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument(
        "--model-version",
        action="append",
        default=[],
        help="Pin expected modelVersion baseline as model_id=version (repeatable).",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Mark the emitted calibration artifact status='approved'.",
    )
    parser.add_argument("--approved-by", type=str, default="ai-risk-owner")
    parser.add_argument("--notes", type=str, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if args.verify_only is not None:
            cal = load_calibration_artifact(
                args.verify_only,
                require_approved=True,
                min_kappa=args.min_kappa,
            )
            print(
                json.dumps(
                    {
                        "verified": True,
                        "artifact_id": cal.artifact_id,
                        "artifact_sha256": cal.artifact_sha256,
                        "status": cal.status,
                        "threshold": cal.threshold,
                        "mu_0": cal.mu_0,
                        "drift_delta": cal.drift_delta,
                        "drift_lambda": cal.drift_lambda,
                        "cohen_kappa": cal.cohen_kappa,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.pilot is None or args.output is None:
            parser.error("--pilot and --output are required unless --verify-only is specified")

        config = load_config(args.config_dir)
        model_versions = _default_model_versions(args.config_dir)
        model_versions.update(_parse_model_version_overrides(args.model_version))

        artifact_doc, p14_out = run_offline_calibration(
            pilot_path=args.pilot,
            heldout_registry_path=args.heldout_registry,
            artifact_id=args.artifact_id,
            policy_sha256=config.policy_sha256,
            model_versions=model_versions,
            alpha=args.alpha,
            grid_step=args.grid_step,
            drift_delta=args.drift_delta,
            target_arl=args.target_arl,
            min_kappa=args.min_kappa,
            seed=args.seed,
            approve=bool(args.approve),
            approved_by=args.approved_by,
            notes=args.notes,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(artifact_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if args.p14_output is not None:
            args.p14_output.parent.mkdir(parents=True, exist_ok=True)
            args.p14_output.write_text(
                json.dumps(p14_out, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        print(json.dumps(p14_out, indent=2, sort_keys=True))
        return 0
    except ContaminationError as exc:
        print(f"ERROR [{exc.code}]: {exc.message}", file=sys.stderr)
        return 2
    except CalibrationError as exc:
        print(f"ERROR [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1


__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
