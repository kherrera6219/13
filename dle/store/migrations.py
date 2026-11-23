"""SQLite migration runner and multi-database store bundle (ADR-005).

Implements NFR-PRIV-01, FR-RCPT-01, and FR-SES-01 by applying section-scoped
migrations (``-- @database <name>``) idempotently across the five SQLite stores
and loading ``sqlite-vec`` for vector indexing when enabled.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import sqlite_vec

DatabaseName = Literal["registry", "evidence", "sessions", "receipts", "ops"]
DATABASE_NAMES: tuple[DatabaseName, ...] = (
    "registry",
    "evidence",
    "sessions",
    "receipts",
    "ops",
)

_DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def parse_migration_sections(sql_text: str) -> dict[str, str]:
    """Split a migration SQL script by ``-- @database <name>`` markers."""
    sections: dict[str, list[str]] = {}
    current_db: str | None = None
    for line in sql_text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("-- @database "):
            name = stripped.removeprefix("-- @database ").strip()
            if name not in DATABASE_NAMES:
                raise ValueError(f"unknown migration @database section {name!r}")
            current_db = name
            sections.setdefault(name, [])
            continue
        if current_db is not None:
            sections[current_db].append(line)
    return {
        name: "".join(lines).strip() for name, lines in sections.items() if "".join(lines).strip()
    }


def load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    """Load the ``sqlite-vec`` extension onto ``conn`` safely."""
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)
    return True


def ensure_vector_table(conn: sqlite3.Connection, *, dim: int) -> None:
    """Create ``passages_vec`` virtual table for embeddings of dimension ``dim``."""
    if not isinstance(dim, int) or isinstance(dim, bool) or dim < 1 or dim > 4096:
        raise ValueError(f"embedding dimension must be an integer in [1, 4096], got {dim!r}")
    ddl = (
        "CREATE VIRTUAL TABLE IF NOT EXISTS passages_vec USING vec0 ("
        "passage_rowid INTEGER PRIMARY KEY, "
        "embedding FLOAT[" + str(dim) + "]"
        ");"
    )
    conn.execute(ddl)
    conn.commit()


def apply_migrations(
    conn: sqlite3.Connection,
    *,
    database: DatabaseName,
    migrations_dir: Path | None = None,
) -> list[str]:
    """Apply unapplied SQL migration sections for ``database`` in sorted order."""
    if database not in DATABASE_NAMES:
        raise ValueError(f"unknown database {database!r}")

    target_dir = migrations_dir if migrations_dir is not None else _DEFAULT_MIGRATIONS_DIR
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _schema_migrations (
            version TEXT PRIMARY KEY,
            applied_utc TEXT NOT NULL
        );
        """
    )
    conn.commit()

    already = {
        str(row[0])
        for row in conn.execute("SELECT version FROM _schema_migrations ORDER BY version")
    }
    applied_now: list[str] = []

    for sql_file in sorted(target_dir.glob("*.sql")):
        version = sql_file.name
        if version in already:
            continue
        sections = parse_migration_sections(sql_file.read_text(encoding="utf-8"))
        section_sql = sections.get(database)
        if not section_sql:
            continue
        conn.executescript(section_sql)
        conn.execute(
            "INSERT INTO _schema_migrations (version, applied_utc) VALUES (?, ?)",
            (version, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        conn.commit()
        applied_now.append(version)

    return applied_now


def _connect_sqlite(path: Path | None) -> sqlite3.Connection:
    target = ":memory:" if path is None else str(path)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@dataclass
class StoreBundle:
    """Migrated SQLite connections for all five DLE stores (`ADR-005`)."""

    registry: sqlite3.Connection
    evidence: sqlite3.Connection
    sessions: sqlite3.Connection
    receipts: sqlite3.Connection
    ops: sqlite3.Connection
    data_dir: Path | None
    vec_enabled: bool

    def close(self) -> None:
        """Close all five SQLite store connections cleanly."""
        for conn in (self.registry, self.evidence, self.sessions, self.receipts, self.ops):
            conn.close()


def open_stores(
    data_dir: Path | None = None,
    *,
    enable_vec: bool = True,
    migrations_dir: Path | None = None,
) -> StoreBundle:
    """Open or create and migrate all five SQLite databases."""
    if data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)

    conns: dict[DatabaseName, sqlite3.Connection] = {}
    vec_loaded = False
    try:
        for db_name in DATABASE_NAMES:
            db_path = (data_dir / f"{db_name}.db") if data_dir is not None else None
            conn = _connect_sqlite(db_path)
            if db_name == "evidence" and enable_vec:
                vec_loaded = load_sqlite_vec(conn)
            apply_migrations(conn, database=db_name, migrations_dir=migrations_dir)
            conns[db_name] = conn
    except Exception:
        for conn in conns.values():
            conn.close()
        raise

    return StoreBundle(
        registry=conns["registry"],
        evidence=conns["evidence"],
        sessions=conns["sessions"],
        receipts=conns["receipts"],
        ops=conns["ops"],
        data_dir=data_dir,
        vec_enabled=vec_loaded,
    )


__all__ = [
    "DATABASE_NAMES",
    "DatabaseName",
    "StoreBundle",
    "apply_migrations",
    "ensure_vector_table",
    "load_sqlite_vec",
    "open_stores",
    "parse_migration_sections",
]
