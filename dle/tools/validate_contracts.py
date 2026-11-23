"""Validate OpenAPI, JSON schemas, function bindings, and release profiles.

Implements IR-01..IR-07, FR-FN-01, and FR-FN-05. Exits non-zero on any failure,
printing each affected file path and RFC 6901 JSON pointer.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import yaml
from openapi_spec_validator import OpenAPIV31SpecValidator

EXPECTED_KERNEL_IDS: frozenset[str] = frozenset(f"DVSS-K{i:02d}" for i in range(1, 13))
HOLD_ALLOWED_IDS: frozenset[str] = frozenset({"DVSS-K04", "DVSS-K11", "DVSS-K12"})


@dataclass(frozen=True)
class ValidationFailure:
    """Single contract validation failure with file path and JSON pointer."""

    file: str
    pointer: str
    message: str

    def format(self) -> str:
        """Return ``<file> <pointer>: <message>`` diagnostic string."""
        return f"{self.file} {self.pointer}: {self.message}"


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _escape_token(token: str | int) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _json_pointer(path: Iterable[str | int]) -> str:
    parts = [_escape_token(part) for part in path]
    return "/" + "/".join(parts) if parts else "/"


def _load_yaml_file(root: Path, path: Path) -> tuple[object | None, list[ValidationFailure]]:
    rel_path = _rel(root, path)
    if not path.exists():
        return None, [ValidationFailure(rel_path, "/", "required file does not exist")]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        pointer = f"/line:{mark.line + 1}:col:{mark.column + 1}" if mark is not None else "/"
        return None, [ValidationFailure(rel_path, pointer, f"YAML parse error: {exc}")]
    return data, []


def validate_json_schemas(root: Path) -> list[ValidationFailure]:
    """Validate every JSON Schema under ``contracts/`` against Draft 2020-12."""
    failures: list[ValidationFailure] = []
    contracts_dir = root / "contracts"
    if not contracts_dir.is_dir():
        return [ValidationFailure("contracts", "/", "contracts directory is missing")]

    for schema_path in sorted(contracts_dir.rglob("*.json")):
        rel_path = _rel(root, schema_path)
        try:
            doc = json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(
                ValidationFailure(
                    rel_path,
                    f"/line:{exc.lineno}:col:{exc.colno}",
                    f"invalid JSON: {exc.msg}",
                )
            )
            continue

        if not isinstance(doc, dict):
            failures.append(
                ValidationFailure(rel_path, "/", "JSON Schema root must be a JSON object")
            )
            continue

        try:
            jsonschema.Draft202012Validator.check_schema(doc)
        except jsonschema.SchemaError as exc:
            pointer = _json_pointer(list(exc.absolute_path or exc.path))
            failures.append(ValidationFailure(rel_path, pointer, exc.message))

    return failures


def validate_openapi(root: Path) -> list[ValidationFailure]:
    """Validate ``contracts/openapi.yaml`` as OpenAPI 3.1 including relative ``$ref``s."""
    openapi_path = root / "contracts" / "openapi.yaml"
    rel_path = _rel(root, openapi_path)
    spec, load_failures = _load_yaml_file(root, openapi_path)
    if load_failures:
        return load_failures
    if not isinstance(spec, dict):
        return [ValidationFailure(rel_path, "/", "OpenAPI document root must be a mapping")]

    failures: list[ValidationFailure] = []
    try:
        validator = OpenAPIV31SpecValidator(spec, base_uri=openapi_path.resolve().as_uri())
        for err in validator.iter_errors():
            raw_path = getattr(err, "absolute_path", None) or getattr(err, "path", ())
            path_tokens = (
                [tok for tok in raw_path if isinstance(tok, str | int)]
                if isinstance(raw_path, Iterable)
                else []
            )
            pointer = _json_pointer(path_tokens)
            msg = str(getattr(err, "message", "") or str(err).splitlines()[0])
            failures.append(ValidationFailure(rel_path, pointer, msg))
    except Exception as exc:
        raw_path = getattr(exc, "absolute_path", None) or getattr(exc, "path", ())
        path_tokens = (
            [tok for tok in raw_path if isinstance(tok, str | int)]
            if isinstance(raw_path, Iterable)
            else []
        )
        pointer = _json_pointer(path_tokens) if path_tokens else "/"
        failures.append(ValidationFailure(rel_path, pointer, str(exc)))
    return failures


def validate_functions_yaml(root: Path) -> list[ValidationFailure]:
    """Validate ``config/functions.yaml`` against schema and kernel/hold invariants."""
    schema_path = root / "contracts" / "functions.schema.json"
    functions_path = root / "config" / "functions.yaml"
    schema_rel = _rel(root, schema_path)
    functions_rel = _rel(root, functions_path)

    if not schema_path.is_file():
        return [ValidationFailure(schema_rel, "/", "functions schema file does not exist")]
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            ValidationFailure(
                schema_rel,
                f"/line:{exc.lineno}:col:{exc.colno}",
                f"invalid JSON: {exc.msg}",
            )
        ]

    doc, load_failures = _load_yaml_file(root, functions_path)
    if load_failures:
        return load_failures
    if not isinstance(doc, dict):
        return [ValidationFailure(functions_rel, "/", "functions.yaml root must be a mapping")]

    failures: list[ValidationFailure] = []
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        failures.append(
            ValidationFailure(functions_rel, _json_pointer(list(err.absolute_path)), err.message)
        )

    raw_functions = doc.get("functions")
    if isinstance(raw_functions, list):
        seen_ids: set[str] = set()
        for idx, item in enumerate(raw_functions):
            if not isinstance(item, dict):
                continue
            fn_id = item.get("id")
            if isinstance(fn_id, str):
                if fn_id in seen_ids:
                    failures.append(
                        ValidationFailure(
                            functions_rel,
                            f"/functions/{idx}/id",
                            f"duplicate function ID {fn_id!r}",
                        )
                    )
                seen_ids.add(fn_id)

                level = item.get("level")
                if fn_id.startswith("DVSS-K") and level != "kernel":
                    failures.append(
                        ValidationFailure(
                            functions_rel,
                            f"/functions/{idx}/level",
                            f"{fn_id} must have level 'kernel', got {level!r}",
                        )
                    )
                elif fn_id.startswith("DVSS-P") and level != "policy":
                    failures.append(
                        ValidationFailure(
                            functions_rel,
                            f"/functions/{idx}/level",
                            f"{fn_id} must have level 'policy', got {level!r}",
                        )
                    )

                if item.get("can_hold") is True and fn_id not in HOLD_ALLOWED_IDS:
                    failures.append(
                        ValidationFailure(
                            functions_rel,
                            f"/functions/{idx}/can_hold",
                            "only DVSS-K04, DVSS-K11, DVSS-K12 may hold; "
                            f"{fn_id} cannot set can_hold=true",
                        )
                    )

        missing_kernel = sorted(EXPECTED_KERNEL_IDS - seen_ids)
        if missing_kernel:
            failures.append(
                ValidationFailure(
                    functions_rel,
                    "/functions",
                    f"missing mandatory kernel binding(s): {', '.join(missing_kernel)}",
                )
            )

    return failures


def validate_function_io_pairs(root: Path) -> list[ValidationFailure]:
    """Ensure every bound function I/O schema under ``contracts/functions/`` is paired."""
    fn_dir = root / "contracts" / "functions"
    if not fn_dir.is_dir():
        return []

    failures: list[ValidationFailure] = []
    in_stems = {p.name[: -len(".in.json")] for p in sorted(fn_dir.glob("*.in.json"))}
    out_stems = {p.name[: -len(".out.json")] for p in sorted(fn_dir.glob("*.out.json"))}

    for stem in sorted(in_stems - out_stems):
        failures.append(
            ValidationFailure(
                f"contracts/functions/{stem}.in.json",
                "/",
                f"missing sibling output schema '{stem}.out.json'",
            )
        )
    for stem in sorted(out_stems - in_stems):
        failures.append(
            ValidationFailure(
                f"contracts/functions/{stem}.out.json",
                "/",
                f"missing sibling input schema '{stem}.in.json'",
            )
        )
    return failures


def validate_profiles(root: Path) -> list[ValidationFailure]:
    """Verify release profiles use valid OpenAPI ReleaseMode values and never disable kernel."""
    openapi_path = root / "contracts" / "openapi.yaml"
    spec, spec_failures = _load_yaml_file(root, openapi_path)
    valid_modes: set[str] = set()
    if not spec_failures and isinstance(spec, dict):
        components = spec.get("components")
        if isinstance(components, dict):
            headers = components.get("headers")
            if isinstance(headers, dict):
                rel_mode = headers.get("ReleaseMode")
                if isinstance(rel_mode, dict):
                    schema = rel_mode.get("schema")
                    if isinstance(schema, dict) and isinstance(schema.get("enum"), list):
                        valid_modes = {str(v) for v in schema["enum"]}

    profiles_dir = root / "config" / "profiles"
    if not profiles_dir.is_dir():
        return [ValidationFailure("config/profiles", "/", "profiles directory is missing")]

    failures: list[ValidationFailure] = []
    for profile_path in sorted(profiles_dir.glob("*.yaml")):
        rel_path = _rel(root, profile_path)
        doc, load_failures = _load_yaml_file(root, profile_path)
        if load_failures:
            failures.extend(load_failures)
            continue
        if not isinstance(doc, dict):
            failures.append(ValidationFailure(rel_path, "/", "profile root must be a mapping"))
            continue

        if "kernel_functions" in doc:
            failures.append(
                ValidationFailure(
                    rel_path,
                    "/kernel_functions",
                    "kernel functions cannot be configured or disabled in profiles",
                )
            )

        policy_fns = doc.get("policy_functions")
        if isinstance(policy_fns, dict):
            for fn_id in policy_fns:
                if str(fn_id).startswith("DVSS-K"):
                    failures.append(
                        ValidationFailure(
                            rel_path,
                            _json_pointer(["policy_functions", str(fn_id)]),
                            f"kernel function {fn_id} cannot be toggled in policy_functions",
                        )
                    )

        release = doc.get("release")
        if isinstance(release, dict) and valid_modes:
            for key, mode in release.items():
                if mode not in valid_modes:
                    failures.append(
                        ValidationFailure(
                            rel_path,
                            _json_pointer(["release", str(key)]),
                            f"invalid release mode {mode!r}; expected one of {sorted(valid_modes)}",
                        )
                    )

    return failures


def validate_all(root: Path) -> list[ValidationFailure]:
    """Run all contract, schema, function binding, and profile validators."""
    failures: list[ValidationFailure] = []
    failures.extend(validate_json_schemas(root))
    failures.extend(validate_openapi(root))
    failures.extend(validate_functions_yaml(root))
    failures.extend(validate_function_io_pairs(root))
    failures.extend(validate_profiles(root))
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for ``python -m dle.tools.validate_contracts``."""
    parser = argparse.ArgumentParser(
        prog="dle.tools.validate_contracts",
        description="Validate OpenAPI, JSON schemas, function bindings, and release profiles.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root directory (defaults to package root)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.root.resolve()

    failures = validate_all(root)
    if failures:
        for failure in failures:
            print(failure.format(), file=sys.stderr)
        return 1

    print(f"Contract validation passed for {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
