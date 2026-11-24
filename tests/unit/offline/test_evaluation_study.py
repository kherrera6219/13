"""Tests for Phase 7 Wave 7B ``O3`` evaluation study engine, System Card, and SBOM artifacts."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from dle.config import load_config
from dle.errors import CalibrationError
from dle.host.services.calibration import load_calibration_artifact
from dle.host.services.evaluation import (
    binom_lower_one_sided,
    binom_upper_one_sided,
    family_clustered_paired_bootstrap,
    render_study_report_markdown,
    render_system_card,
    verify_heldout_seal,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_SET = REPO_ROOT / "offline" / "study" / "heldout_eval_150.jsonl"
CHAL_SET = REPO_ROOT / "offline" / "study" / "heldout_challenge_100.jsonl"
REGISTRY = REPO_ROOT / "offline" / "registry" / "heldout_hashes.json"
RESULTS = REPO_ROOT / "reports" / "evaluation_study_results.json"
CARD = REPO_ROOT / "reports" / "system_card.md"
SBOM = REPO_ROOT / "reports" / "sbom.cdx.json"


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_clopper_pearson_bounds_match_preregistered_protocol_values() -> None:
    # study_protocol.md: H3 <= 2 errors of 150 -> ~4.1%; H4 >= 99/100 -> ~95.3%.
    assert binom_upper_one_sided(2, 150) == pytest.approx(0.0414, abs=5e-4)
    assert binom_lower_one_sided(99, 100) == pytest.approx(0.9534, abs=5e-4)
    assert binom_upper_one_sided(0, 150) == pytest.approx(1 - 0.05 ** (1 / 150), abs=1e-6)
    assert binom_lower_one_sided(0, 10) == 0.0
    assert binom_upper_one_sided(10, 10) == 1.0


@pytest.mark.parametrize(("k", "n"), [(-1, 10), (11, 10), (0, 0)])
def test_binomial_bounds_reject_invalid_counts(k: int, n: int) -> None:
    with pytest.raises(ValueError, match="invalid binomial counts"):
        binom_upper_one_sided(k, n)
    with pytest.raises(ValueError, match="invalid binomial counts"):
        binom_lower_one_sided(k, n)


def test_family_clustered_bootstrap_is_deterministic_and_directional() -> None:
    rng = random.Random(7)  # noqa: S311 - deterministic test fixture
    pairs = {
        f"fam-{i}": [(rng.random() * 0.2, 0.5 + rng.random() * 0.2) for _ in range(10)]
        for i in range(6)
    }
    first = family_clustered_paired_bootstrap(pairs, n_boot=500, seed=11)
    second = family_clustered_paired_bootstrap(pairs, n_boot=500, seed=11)
    assert first == second
    assert first.mean_diff < 0.0
    assert first.ci_high < 0.0
    assert first.spans_zero is False
    assert first.n_families == 6


def test_family_clustered_bootstrap_rejects_empty_or_small_runs() -> None:
    with pytest.raises(CalibrationError):
        family_clustered_paired_bootstrap({}, n_boot=500)
    with pytest.raises(CalibrationError):
        family_clustered_paired_bootstrap({"a": [(0.0, 1.0)]}, n_boot=10)


def test_heldout_seal_verifies_and_refuses_tampered_items() -> None:
    eval_items = _load_jsonl(EVAL_SET)
    chal_items = _load_jsonl(CHAL_SET)
    assert len(eval_items) == 150
    assert len(chal_items) == 100
    digest = verify_heldout_seal(
        eval_items=eval_items, challenge_items=chal_items, registry_path=REGISTRY
    )
    assert len(digest) == 64

    tampered = [dict(item) for item in eval_items]
    tampered[0]["question"] = str(tampered[0]["question"]) + " (edited)"
    with pytest.raises(CalibrationError, match="heldout_test seal mismatch"):
        verify_heldout_seal(eval_items=tampered, challenge_items=chal_items, registry_path=REGISTRY)


def test_committed_study_results_render_report_and_system_card() -> None:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    hyp = results["hypotheses"]
    assert set(hyp) == {
        "H1_addressing",
        "H2_roles",
        "H3_gate",
        "H4_routing",
        "M1_extractor",
        "M2_catalog",
    }
    assert results["arms"]["strict"]["n"] == 150
    assert hyp["H4_routing"]["n"] == 100

    report = render_study_report_markdown(results)
    assert "H3 · Gate" in report
    assert "{{" not in report

    cfg = load_config(REPO_ROOT / "config")
    cal = load_calibration_artifact(
        REPO_ROOT / "config" / "calibration" / "cal-phase6-v1.json",
        require_approved=True,
        min_kappa=0.6,
    )
    card = render_system_card(
        results,
        config=cfg,
        calibration=cal,
        template_path=REPO_ROOT / "docs" / "templates" / "system_card_template.md",
        protocol_commit=str(results["protocol_commit"]),
    )
    assert "{{" not in card
    assert card == CARD.read_text(encoding="utf-8")


def test_system_card_refuses_unresolved_placeholders(tmp_path: Path) -> None:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    tmpl = tmp_path / "card.md"
    tmpl.write_text("# Card {{version}} {{unknown_field}}\n", encoding="utf-8")
    cfg = load_config(REPO_ROOT / "config")
    cal = load_calibration_artifact(REPO_ROOT / "config" / "calibration" / "cal-phase6-v1.json")
    with pytest.raises(CalibrationError, match="unresolved template placeholders"):
        render_system_card(
            results, config=cfg, calibration=cal, template_path=tmpl, protocol_commit="x"
        )


def test_committed_sbom_is_cyclonedx_1_6_with_components() -> None:
    sbom = json.loads(SBOM.read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    names = {c["name"].lower() for c in sbom["components"]}
    assert {"fastapi", "httpx", "cryptography"} <= names
