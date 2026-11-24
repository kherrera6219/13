"""CLI entrypoint for executing the pre-registered §17 evaluation study (``O3``)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from dle.errors import CalibrationError
from dle.host.services.evaluation import (
    render_study_report_markdown,
    render_system_card,
    run_preregistered_study,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``DLE-EVL-003`` evaluation study, write report artifacts, and populate System Card."""
    parser = argparse.ArgumentParser(
        prog="dle-evaluate",
        description="Execute pre-registered §17 evaluation study (O3) and generate System Card.",
    )
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=Path("offline/study/heldout_eval_150.jsonl"),
    )
    parser.add_argument(
        "--challenge-set",
        type=Path,
        default=Path("offline/study/heldout_challenge_100.jsonl"),
    )
    parser.add_argument(
        "--extractor-set",
        type=Path,
        default=Path("offline/dev_sets/extractor_labeled_200.jsonl"),
    )
    parser.add_argument(
        "--heldout-registry",
        type=Path,
        default=Path("offline/registry/heldout_hashes.json"),
    )
    parser.add_argument(
        "--calibration",
        type=Path,
        default=Path("config/calibration/cal-phase6-v1.json"),
    )
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument(
        "--system-card-template",
        type=Path,
        default=Path("docs/templates/system_card_template.md"),
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=Path("reports/evaluation_study_report.md"),
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("reports/evaluation_study_results.json"),
    )
    parser.add_argument(
        "--system-card",
        type=Path,
        default=Path("reports/system_card.md"),
    )
    parser.add_argument("--protocol-commit", type=str, default="f09d6eb")
    parser.add_argument("--seed", type=int, default=20261123)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        results, cfg, cal = run_preregistered_study(
            eval_path=args.eval_set,
            challenge_path=args.challenge_set,
            extractor_path=args.extractor_set,
            heldout_registry_path=args.heldout_registry,
            calibration_path=args.calibration,
            config_dir=args.config_dir,
            protocol_commit=args.protocol_commit,
            seed=args.seed,
        )
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        results_json = json.dumps(results, indent=2, sort_keys=True) + "\n"
        args.json_out.write_text(results_json, encoding="utf-8")
        report_md = render_study_report_markdown(results)
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(report_md, encoding="utf-8")
        card_md = render_system_card(
            results,
            config=cfg,
            calibration=cal,
            template_path=args.system_card_template,
            protocol_commit=args.protocol_commit,
        )
        args.system_card.parent.mkdir(parents=True, exist_ok=True)
        args.system_card.write_text(card_md, encoding="utf-8")

        summary = {
            "hypotheses": results["hypotheses"],
            "report": str(args.report_out),
            "system_card": str(args.system_card),
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    except CalibrationError as exc:
        print(f"ERROR [{exc.code}]: {exc.message}", file=sys.stderr)
        return 2


__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
