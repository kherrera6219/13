"""Unit tests for AST egress import checker (P1-04, NFR-SEC-03)."""

from __future__ import annotations

from pathlib import Path

from dle.tools.check_egress_imports import check_egress_imports, main

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_real_repository_has_no_disallowed_egress_imports(capsys):
    """T-UNIT-SEC-05: no module outside dle/models/egress.py imports network libraries."""
    assert check_egress_imports(REPO_ROOT) == []
    exit_code = main(["--root", str(REPO_ROOT)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "passed" in captured.out.lower()


def test_checker_allows_egress_module_and_rejects_other_network_imports(tmp_path, capsys):
    """T-UNIT-SEC-06: temporary violations fail non-zero with exact file, line, and module."""
    (tmp_path / "dle" / "models").mkdir(parents=True)
    (tmp_path / "dle" / "models" / "egress.py").write_text("import httpx\n", encoding="utf-8")
    (tmp_path / "dle" / "safe.py").write_text(
        "from http import HTTPStatus\nSTATUS = HTTPStatus.OK\n", encoding="utf-8"
    )
    assert check_egress_imports(tmp_path) == []

    bad = tmp_path / "dle" / "bad.py"
    bad.write_text(
        "\n".join(
            [
                "import httpx",
                "from urllib import request",
                "import socket",
                "from http import client",
                "import importlib",
                "m = importlib.import_module('requests')",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "dle/bad.py:1: forbidden egress import 'httpx'" in captured.err
    assert "dle/bad.py:2: forbidden egress import 'urllib'" in captured.err
    assert "dle/bad.py:3: forbidden egress import 'socket'" in captured.err
    assert "dle/bad.py:4: forbidden egress import 'http.client'" in captured.err
    assert "dle/bad.py:6: forbidden egress import 'requests'" in captured.err
