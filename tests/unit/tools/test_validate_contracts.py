"""Unit tests for dle.tools.validate_contracts (P1-02, IR-01..07)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from dle.tools.validate_contracts import main, validate_all

REPO_ROOT = Path(__file__).resolve().parents[3]


def _copy_contract_workspace(tmp_path: Path) -> Path:
    shutil.copytree(REPO_ROOT / "contracts", tmp_path / "contracts")
    shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
    return tmp_path


def test_real_repository_contracts_and_cli_pass(capsys):
    """T-UNIT-TOOL-01: repository contracts, OpenAPI, functions, and profiles validate clean."""
    assert validate_all(REPO_ROOT) == []
    exit_code = main(["--root", str(REPO_ROOT)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "passed" in captured.out.lower()


def test_malformed_json_schema_reports_file_and_pointer(tmp_path, capsys):
    """T-UNIT-TOOL-02: invalid JSON Schema fails non-zero naming file and JSON pointer."""
    root = _copy_contract_workspace(tmp_path)
    target = root / "contracts" / "receipt.schema.json"
    schema = json.loads(target.read_text(encoding="utf-8"))
    schema["properties"] = "not-an-object"
    target.write_text(json.dumps(schema), encoding="utf-8")

    exit_code = main(["--root", str(root)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "contracts/receipt.schema.json" in captured.err
    assert "/properties" in captured.err or "/" in captured.err


def test_malformed_json_syntax_reports_file_and_line(tmp_path, capsys):
    """T-UNIT-TOOL-03: broken JSON syntax names file and line/column pointer."""
    root = _copy_contract_workspace(tmp_path)
    target = root / "contracts" / "coordinate.schema.json"
    target.write_text('{"$schema": ', encoding="utf-8")

    exit_code = main(["--root", str(root)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "contracts/coordinate.schema.json" in captured.err
    assert "/line:1" in captured.err


def test_malformed_openapi_reports_file_and_pointer(tmp_path, capsys):
    """T-UNIT-TOOL-04: broken OpenAPI document names openapi.yaml and offending pointer."""
    root = _copy_contract_workspace(tmp_path)
    target = root / "contracts" / "openapi.yaml"
    spec = yaml.safe_load(target.read_text(encoding="utf-8"))
    del spec["info"]["version"]
    target.write_text(yaml.safe_dump(spec), encoding="utf-8")

    exit_code = main(["--root", str(root)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "contracts/openapi.yaml" in captured.err
    assert "/info" in captured.err


def test_invalid_functions_yaml_and_unpaired_io_fail(tmp_path, capsys):
    """T-UNIT-TOOL-05: illegal hold binding, missing kernel, and orphan I/O fail cleanly."""
    root = _copy_contract_workspace(tmp_path)
    fn_path = root / "config" / "functions.yaml"
    fn_doc = yaml.safe_load(fn_path.read_text(encoding="utf-8"))
    fn_doc["functions"] = [fn for fn in fn_doc["functions"] if fn["id"] != "DVSS-K01"]
    for fn in fn_doc["functions"]:
        if fn["id"] == "DVSS-P01":
            fn["can_hold"] = True
    fn_path.write_text(yaml.safe_dump(fn_doc), encoding="utf-8")

    orphan = root / "contracts" / "functions" / "k01.in.json"
    orphan.write_text('{"type": "object"}\n', encoding="utf-8")

    exit_code = main(["--root", str(root)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "config/functions.yaml /functions" in captured.err
    assert "can_hold" in captured.err
    assert "DVSS-K01" in captured.err
    assert "contracts/functions/k01.in.json" in captured.err
