"""Official ``@google/genai`` JavaScript SDK runner invoked via pytest when Node is available."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.gemini_compat.conftest import COMPAT_ADMIN_KEY, COMPAT_TEST_KEY, _LiveMiddlewareServer


def test_js_sdk_compatibility_suite(compat_server: _LiveMiddlewareServer) -> None:
    """GC-01..GC-26 on @google/genai JavaScript SDK (skips cleanly if no Node UI deps)."""
    node_bin = shutil.which("node")
    genai_dir = Path("ui/node_modules/@google/genai")
    if node_bin is None or not genai_dir.exists():
        pytest.skip("Node or ui/node_modules/@google/genai unavailable in this environment")

    env = dict(os.environ)
    env["DLE_BASE_URL"] = compat_server.base_url
    env["DLE_API_KEY"] = COMPAT_TEST_KEY
    env["DLE_ADMIN_KEY"] = COMPAT_ADMIN_KEY

    proc = subprocess.run(  # noqa: S603
        [node_bin, "tests/gemini_compat/js_sdk_compat.mjs"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, (
        f"JS SDK compat failed:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert "GC-01" in payload["passedCases"]
    assert "GC-12" in payload["passedCases"]
    assert "GC-13" in payload["passedCases"]
    assert "GC-26" in payload["passedCases"]
