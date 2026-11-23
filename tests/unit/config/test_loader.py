"""Unit tests for configuration loader and JCS policy digest (P1-03, FR-FN-03)."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from dle.config import compute_policy_digest, load_config
from dle.errors import ConfigError, KernelNotOptional

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"


def _reverse_dict_keys(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: _reverse_dict_keys(v) for k, v in reversed(list(obj.items()))}
    if isinstance(obj, list):
        return [_reverse_dict_keys(item) for item in obj]
    return obj


def test_load_repo_config_validates_all_sections_and_profile_inheritance():
    """T-UNIT-CFG-01: loads repository config/, resolves extends: strict, checks model pins."""
    cfg = load_config(CONFIG_DIR)
    assert len(cfg.functions.functions) == 26
    assert set(cfg.profiles) == {"advisory", "kernel_only", "kernel_plus_policy", "strict"}
    assert cfg.profiles["strict"].policy_functions["DVSS-P11"] == "tier3"
    assert cfg.profiles["strict"].policy_functions["DVSS-P05"] == "off"
    assert cfg.profiles["strict"].policy_functions["DVSS-P01"] == "on"

    # kernel_plus_policy inherits strict
    kpp = cfg.profiles["kernel_plus_policy"]
    assert kpp.extends == "strict"
    assert kpp.release == cfg.profiles["strict"].release
    assert kpp.policy_functions == cfg.profiles["strict"].policy_functions

    assert len(cfg.policy_sha256) == 64
    carbon_prices = cfg.model_pins.prices_usd_per_million_tokens["gemini-4-carbon"]
    assert carbon_prices[0].from_date == date(2026, 11, 10)
    assert carbon_prices[1].from_date == date(2026, 12, 1)
    assert carbon_prices[1].input == 4.0
    assert carbon_prices[1].output == 20.0


def test_policy_digest_is_invariant_under_yaml_key_reordering(tmp_path):
    """T-UNIT-CFG-02: identical configs with reversed key order yield identical policy_sha256."""
    baseline = load_config(CONFIG_DIR)
    copied = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, copied)

    for yaml_path in copied.rglob("*.yaml"):
        if yaml_path.parent.name == "reference":
            continue
        parsed = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        reordered = _reverse_dict_keys(parsed)
        yaml_path.write_text(yaml.safe_dump(reordered, sort_keys=False), encoding="utf-8")

    reloaded = load_config(copied)
    assert reloaded.policy_sha256 == baseline.policy_sha256
    assert compute_policy_digest({"b": 1, "a": {"y": 2, "x": 3}}) == compute_policy_digest(
        {"a": {"x": 3, "y": 2}, "b": 1}
    )


def test_policy_digest_changes_when_setting_changes(tmp_path):
    """T-UNIT-CFG-03: changing any governed config setting changes policy_sha256."""
    baseline = load_config(CONFIG_DIR)
    copied = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, copied)

    strict_path = copied / "profiles" / "strict.yaml"
    data = yaml.safe_load(strict_path.read_text(encoding="utf-8"))
    data["alpha"] = 0.10
    strict_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    mutated = load_config(copied)
    assert mutated.policy_sha256 != baseline.policy_sha256


def test_disabling_or_omitting_kernel_function_raises_kernel_not_optional(tmp_path):
    """T-UNIT-CFG-04: kernel functions can never be disabled in profiles or removed."""
    copied = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, copied)

    strict_path = copied / "profiles" / "strict.yaml"
    strict_doc = yaml.safe_load(strict_path.read_text(encoding="utf-8"))
    strict_doc["policy_functions"]["DVSS-K01"] = "off"
    strict_path.write_text(yaml.safe_dump(strict_doc), encoding="utf-8")
    with pytest.raises(KernelNotOptional, match="DVSS-K01"):
        load_config(copied)

    # Restore strict.yaml and try kernel_functions switch
    shutil.copyfile(CONFIG_DIR / "profiles" / "strict.yaml", strict_path)
    advisory_path = copied / "profiles" / "advisory.yaml"
    adv_doc = yaml.safe_load(advisory_path.read_text(encoding="utf-8"))
    adv_doc["kernel_functions"] = {"DVSS-K04": "off"}
    advisory_path.write_text(yaml.safe_dump(adv_doc), encoding="utf-8")
    with pytest.raises(KernelNotOptional, match="kernel_functions"):
        load_config(copied)

    # Restore advisory.yaml and drop DVSS-K12 from functions.yaml
    shutil.copyfile(CONFIG_DIR / "profiles" / "advisory.yaml", advisory_path)
    fn_path = copied / "functions.yaml"
    fn_doc = yaml.safe_load(fn_path.read_text(encoding="utf-8"))
    fn_doc["functions"] = [f for f in fn_doc["functions"] if f["id"] != "DVSS-K12"]
    fn_path.write_text(yaml.safe_dump(fn_doc), encoding="utf-8")
    with pytest.raises(KernelNotOptional, match="DVSS-K12"):
        load_config(copied)


def test_inheritance_cycle_and_unknown_policy_function_raise_config_error(tmp_path):
    """T-UNIT-CFG-05: profile extends cycles and unknown policy IDs fail with ConfigError."""
    copied = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, copied)

    strict_path = copied / "profiles" / "strict.yaml"
    strict_doc = yaml.safe_load(strict_path.read_text(encoding="utf-8"))
    strict_doc["extends"] = "kernel_plus_policy"
    strict_path.write_text(yaml.safe_dump(strict_doc), encoding="utf-8")
    with pytest.raises(ConfigError, match="cycle"):
        load_config(copied)

    shutil.copyfile(CONFIG_DIR / "profiles" / "strict.yaml", strict_path)
    strict_doc = yaml.safe_load(strict_path.read_text(encoding="utf-8"))
    strict_doc["policy_functions"]["DVSS-P99"] = "on"
    strict_path.write_text(yaml.safe_dump(strict_doc), encoding="utf-8")
    with pytest.raises(ConfigError, match="DVSS-P99"):
        load_config(copied)
