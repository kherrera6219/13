"""AST check ensuring all outbound HTTP/socket imports live only in ``dle/models/egress.py``.

Implements NFR-SEC-03 and AGENTS.md rule 7.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ALLOWED_EGRESS_RELPATH = "dle/models/egress.py"

FORBIDDEN_ROOT_MODULES: frozenset[str] = frozenset(
    {
        "httpx",
        "requests",
        "urllib",
        "urllib3",
        "aiohttp",
        "socket",
        "websockets",
        "grpc",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
    }
)

FORBIDDEN_DOTTED_MODULES: frozenset[str] = frozenset({"http.client"})


@dataclass(frozen=True)
class ImportViolation:
    """Single disallowed network import found under ``dle/``."""

    file: str
    line: int
    module: str

    def format(self) -> str:
        """Return ``<file>:<line>: forbidden egress import '<module>'`` diagnostic string."""
        return (
            f"{self.file}:{self.line}: forbidden egress import {self.module!r} "
            "(use dle.models.egress.EgressClient)"
        )


def _is_forbidden(module_name: str) -> bool:
    root = module_name.split(".", 1)[0]
    if root in FORBIDDEN_ROOT_MODULES:
        return True
    return any(
        module_name == dotted or module_name.startswith(f"{dotted}.")
        for dotted in FORBIDDEN_DOTTED_MODULES
    )


def scan_file(path: Path, rel_path: str) -> list[ImportViolation]:
    """Parse ``path`` as Python AST and return any forbidden network imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)
    violations: list[ImportViolation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden(alias.name):
                    violations.append(ImportViolation(rel_path, node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or not node.module:
                continue
            if _is_forbidden(node.module):
                violations.append(ImportViolation(rel_path, node.lineno, node.module))
                continue
            for alias in node.names:
                dotted = f"{node.module}.{alias.name}"
                if _is_forbidden(dotted):
                    violations.append(ImportViolation(rel_path, node.lineno, dotted))
        elif isinstance(node, ast.Call):
            fn_name = _call_name(node.func)
            if (
                fn_name in {"__import__", "import_module", "importlib.import_module"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and _is_forbidden(node.args[0].value)
            ):
                violations.append(ImportViolation(rel_path, node.lineno, node.args[0].value))

    return violations


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return None


def check_egress_imports(root: Path) -> list[ImportViolation]:
    """Scan ``root/dle/**/*.py`` for disallowed network imports outside ``dle/models/egress.py``."""
    dle_dir = root / "dle"
    if not dle_dir.is_dir():
        return []

    violations: list[ImportViolation] = []
    for py_path in sorted(dle_dir.rglob("*.py")):
        rel_path = py_path.relative_to(root).as_posix()
        if rel_path == ALLOWED_EGRESS_RELPATH:
            continue
        violations.extend(scan_file(py_path, rel_path))
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for ``python -m dle.tools.check_egress_imports``."""
    parser = argparse.ArgumentParser(
        prog="dle.tools.check_egress_imports",
        description="Verify only dle/models/egress.py imports outbound HTTP/socket libraries.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root directory (defaults to package root)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.root.resolve()

    violations = check_egress_imports(root)
    if violations:
        for violation in violations:
            print(violation.format(), file=sys.stderr)
        return 1

    print(f"Egress import check passed for {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
