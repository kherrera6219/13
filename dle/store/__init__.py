"""Persistent SQLite stores and repositories for DLE middleware (ADR-005)."""

from dle.store.migrations import (
    DATABASE_NAMES,
    DatabaseName,
    StoreBundle,
    apply_migrations,
    ensure_vector_table,
    load_sqlite_vec,
    open_stores,
    parse_migration_sections,
)
from dle.store.repositories import (
    EvidenceRepository,
    OpsRepository,
    ReceiptRepository,
    SessionRepository,
)

__all__ = [
    "DATABASE_NAMES",
    "DatabaseName",
    "EvidenceRepository",
    "OpsRepository",
    "ReceiptRepository",
    "SessionRepository",
    "StoreBundle",
    "apply_migrations",
    "ensure_vector_table",
    "load_sqlite_vec",
    "open_stores",
    "parse_migration_sections",
]
