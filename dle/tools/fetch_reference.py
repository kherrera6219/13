"""Build-time reference taxonomy staging and SHA-256 pinning CLI (``H8``).

Implements DLE-SPC-004 §5 and FR-QP-02 without performing direct network I/O
outside ``dle.models.egress.EgressClient``: stages local taxonomy tables into
``--out-dir``, verifies any pinned SHA-256 digests against ``manifest.yaml``,
and emits deterministic JSON checksum metadata for build reproducibility.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Sequence
from pathlib import Path

from dle.errors import ConfigError
from dle.host.services.reference import (
    compute_file_sha256,
    load_reference_catalog,
    parse_reference_manifest,
)


def stage_reference_files(
    *,
    manifest_path: Path,
    source_dir: Path | None,
    out_dir: Path,
    verify_only: bool = False,
) -> dict[str, object]:
    """Copy or verify staged reference files against ``manifest.yaml``."""
    version, sources = parse_reference_manifest(manifest_path)
    if not verify_only:
        out_dir.mkdir(parents=True, exist_ok=True)
        if source_dir is not None:
            for entry in sources:
                candidates = [source_dir / entry.file]
                if entry.file.lower().endswith(".xlsx"):
                    candidates.append((source_dir / entry.file).with_suffix(".csv"))
                for src in candidates:
                    if src.is_file():
                        dest = out_dir / src.name
                        shutil.copy2(src, dest)
                        actual = compute_file_sha256(dest)
                        if entry.sha256 is not None and actual != entry.sha256:
                            raise ConfigError(
                                f"staged checksum mismatch for {entry.source_id!r}: "
                                f"expected {entry.sha256}, got {actual}"
                            )
                        break

    catalog = load_reference_catalog(manifest_path, ref_dir=out_dir)
    if verify_only and catalog.missing_sources:
        raise ConfigError(
            "reference verification failed; missing sources: " + ", ".join(catalog.missing_sources)
        )
    return {
        "version": version,
        "manifest_sha256": catalog.manifest_sha256,
        "present_sources": list(catalog.present_sources),
        "missing_sources": list(catalog.missing_sources),
        "certified_eligible": catalog.certified_eligible,
        "file_digests": dict(catalog.file_digests),
        "cip_count": len(catalog.cip_codes),
        "soc_count": len(catalog.soc_codes),
        "onet_count": len(catalog.onet_codes),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for build-time staging and verifying CIP/SOC/O*NET references."""
    parser = argparse.ArgumentParser(
        prog="dle-fetch-reference",
        description="Stage and SHA-256 verify Quad Persona CIP/SOC/O*NET reference files.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("config/reference/manifest.yaml"),
        help="Path to config/reference/manifest.yaml.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help="Local cache directory containing downloaded CIP/SOC/O*NET files.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("config/reference"),
        help="Target directory where verified reference files live.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Fail non-zero if any manifest source is missing or fails checksum verification.",
    )
    args = parser.parse_args(argv)

    try:
        summary = stage_reference_files(
            manifest_path=args.manifest,
            source_dir=args.source_dir,
            out_dir=args.out_dir,
            verify_only=bool(args.verify_only),
        )
    except ConfigError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 1

    print(json.dumps({"ok": True, **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
