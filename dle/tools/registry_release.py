"""CLI tool publishing validated 13-axis registries into ``registry.db`` (``O2``)."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from dle.host.services.registry import load_registry
from dle.store import RegistryRepository, open_stores


def main(argv: Sequence[str] | None = None) -> int:
    """Validate and publish 13-axis registry release into SQLite ``registry.db``."""
    parser = argparse.ArgumentParser(
        prog="dle-registry-release",
        description="Validate 13-axis registries, compute manifest SHA-256, and publish release.",
    )
    parser.add_argument(
        "--registry-dir",
        type=Path,
        default=Path("config/registry"),
        help="Path to base 13-axis CSV/JSONL registry directory.",
    )
    parser.add_argument(
        "--overlay-dir",
        type=Path,
        default=None,
        help="Optional domain pilot JSONL overlay directory.",
    )
    parser.add_argument(
        "--db-dir",
        type=Path,
        required=True,
        help="Directory holding SQLite stores (creates/migrates registry.db).",
    )
    parser.add_argument(
        "--release-id",
        type=str,
        default=None,
        help="Explicit release identifier (defaults to UTC timestamp + manifest prefix).",
    )
    parser.add_argument(
        "--approved-by",
        type=str,
        default="registry-owner",
        help="Approver identifier recorded on registry_releases row.",
    )
    parser.add_argument(
        "--allow-fixtures",
        action="store_true",
        help="Allow status='fixture' records (for test databases only).",
    )
    args = parser.parse_args(argv)

    snapshot = load_registry(
        args.registry_dir,
        overlay_dir=args.overlay_dir,
        allow_fixtures=bool(args.allow_fixtures),
    )
    utc_now = datetime.now(UTC)
    release_id = (
        args.release_id
        if args.release_id
        else f"rel-{utc_now.strftime('%Y%m%dT%H%M%SZ')}-{snapshot.manifest_sha256[:8]}"
    )
    atoms, edges, crosswalks = snapshot.to_db_rows()
    stores = open_stores(args.db_dir, enable_vec=False)
    try:
        repo = RegistryRepository(stores.registry)
        summary = repo.publish_release(
            release_id=release_id,
            manifest_sha256=snapshot.manifest_sha256,
            created_utc=utc_now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            approved_by=args.approved_by,
            atoms=atoms,
            spine_edges=edges,
            crosswalks=crosswalks,
            activate=True,
        )
    finally:
        stores.close()

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
