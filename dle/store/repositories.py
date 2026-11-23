"""Thread-safe SQLite repositories over the migrated DLE stores (ADR-005).

Implements persistent CRUD, FTS5 and ``sqlite-vec`` evidence search, append-only
ledger and receipt storage, and operational telemetry persistence for Phase 2+.
"""

from __future__ import annotations

import json
import re
import sqlite3
import struct
import threading
from collections.abc import Sequence

from dle.store.migrations import ensure_vector_table

_FTS_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _pack_vector(values: Sequence[float]) -> bytes:
    if not values:
        raise ValueError("embedding vector must be non-empty")
    return struct.pack(f"{len(values)}f", *[float(v) for v in values])


def _sanitize_fts_query(query: str) -> str:
    tokens = _FTS_TOKEN_RE.findall(query)
    if not tokens:
        return ""
    return " OR ".join(tokens[:16])


class EvidenceRepository:
    """Repository for ``evidence.db`` sources, passages, FTS5, and ``sqlite-vec``."""

    def __init__(self, conn: sqlite3.Connection, *, vec_enabled: bool = True) -> None:
        """Bind repository to migrated ``evidence`` SQLite connection."""
        self._conn = conn
        self._vec_enabled = vec_enabled
        self._vec_dim: int | None = None
        self._lock = threading.RLock()

    def register_source(
        self,
        *,
        source_id: str,
        title: str,
        authority_class: str,
        jurisdiction: str | None,
        is_retainable: bool,
        registered_utc: str,
    ) -> dict[str, object]:
        """Insert a new evidence source record."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sources (
                    source_id, title, authority_class, jurisdiction,
                    is_retainable, registered_utc, retired_utc
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    source_id,
                    title,
                    authority_class,
                    jurisdiction,
                    1 if is_retainable else 0,
                    registered_utc,
                ),
            )
            self._conn.commit()
        return {
            "sourceId": source_id,
            "title": title,
            "authorityClass": authority_class,
            "jurisdiction": jurisdiction,
            "retainable": is_retainable,
            "registeredUtc": registered_utc,
        }

    def get_source(self, source_id: str) -> dict[str, object] | None:
        """Fetch one source descriptor by ``source_id``."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT source_id, title, authority_class, jurisdiction,
                       is_retainable, registered_utc, retired_utc
                FROM sources WHERE source_id = ?
                """,
                (source_id,),
            ).fetchone()
            if row is None:
                return None
            latest = self._conn.execute(
                """
                SELECT revision, valid_from, valid_to
                FROM passages WHERE source_id = ?
                ORDER BY rowid DESC LIMIT 1
                """,
                (source_id,),
            ).fetchone()
        return {
            "sourceId": str(row["source_id"]),
            "title": str(row["title"]),
            "authorityClass": str(row["authority_class"]),
            "revision": str(latest["revision"]) if latest is not None else "rev-1",
            "validFrom": latest["valid_from"] if latest is not None else row["registered_utc"][:10],
            "validTo": latest["valid_to"] if latest is not None else None,
            "retainable": bool(row["is_retainable"]),
        }

    def list_sources(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, object]], str | None]:
        """Return paginated OpenAPI-shaped ``Source`` records plus optional ``nextPageToken``."""
        if limit < 1 or offset < 0:
            raise ValueError("limit must be >= 1 and offset >= 0")
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT s.source_id, s.title, s.authority_class, s.is_retainable, s.registered_utc,
                       (
                           SELECT p.revision FROM passages p
                           WHERE p.source_id = s.source_id ORDER BY p.rowid DESC LIMIT 1
                       ) AS revision,
                       (
                           SELECT p.valid_from FROM passages p
                           WHERE p.source_id = s.source_id ORDER BY p.rowid DESC LIMIT 1
                       ) AS valid_from,
                       (
                           SELECT p.valid_to FROM passages p
                           WHERE p.source_id = s.source_id ORDER BY p.rowid DESC LIMIT 1
                       ) AS valid_to
                FROM sources s
                ORDER BY s.registered_utc DESC, s.source_id ASC
                LIMIT ? OFFSET ?
                """,
                (limit + 1, offset),
            ).fetchall()

        has_more = len(rows) > limit
        page_rows = rows[:limit]
        out: list[dict[str, object]] = []
        for row in page_rows:
            out.append(
                {
                    "sourceId": str(row["source_id"]),
                    "title": str(row["title"]),
                    "authorityClass": str(row["authority_class"]),
                    "revision": str(row["revision"] or "rev-1"),
                    "validFrom": str(row["valid_from"] or row["registered_utc"][:10]),
                    "validTo": row["valid_to"],
                    "retainable": bool(row["is_retainable"]),
                }
            )
        next_token = str(offset + limit) if has_more else None
        return out, next_token

    def insert_passage(
        self,
        *,
        passage_id: str,
        source_id: str,
        revision: str,
        locator: str,
        content_sha256: str,
        body_text: str,
        valid_from: str | None,
        valid_to: str | None,
        retrieved_utc: str,
        access_scope: str = "tenant",
        embedding: Sequence[float] | None = None,
    ) -> int:
        """Append a passage row, update FTS5, and index embedding into ``passages_vec``."""
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO passages (
                    passage_id, source_id, revision, locator, content_sha256,
                    text, valid_from, valid_to, retrieved_utc, access_scope
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    passage_id,
                    source_id,
                    revision,
                    locator,
                    content_sha256,
                    body_text,
                    valid_from,
                    valid_to,
                    retrieved_utc,
                    access_scope,
                ),
            )
            rowid = int(cur.lastrowid or 0)
            self._conn.execute(
                "INSERT INTO passages_fts (rowid, text) VALUES (?, ?)",
                (rowid, body_text),
            )
            if self._vec_enabled and embedding is not None:
                dim = len(embedding)
                if self._vec_dim is None:
                    ensure_vector_table(self._conn, dim=dim)
                    self._vec_dim = dim
                elif dim != self._vec_dim:
                    raise ValueError(
                        f"embedding dimension mismatch: expected {self._vec_dim}, got {dim}"
                    )
                self._conn.execute(
                    "INSERT INTO passages_vec (passage_rowid, embedding) VALUES (?, ?)",
                    (rowid, _pack_vector(embedding)),
                )
            self._conn.commit()
            return rowid

    def get_passage(self, passage_id: str) -> dict[str, object] | None:
        """Fetch a passage joined with its parent source metadata."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT p.rowid AS row_id, p.passage_id, p.source_id, s.title, s.authority_class,
                       s.jurisdiction, s.is_retainable, p.revision, p.locator, p.content_sha256,
                       p.text, p.valid_from, p.valid_to, p.retrieved_utc, p.access_scope
                FROM passages p
                JOIN sources s ON s.source_id = p.source_id
                WHERE p.passage_id = ?
                """,
                (passage_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_passages_for_source(self, source_id: str) -> list[dict[str, object]]:
        """List all passages belonging to ``source_id`` in insert order."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT p.rowid AS row_id, p.passage_id, p.source_id, s.title, s.authority_class,
                       s.jurisdiction, s.is_retainable, p.revision, p.locator, p.content_sha256,
                       p.text, p.valid_from, p.valid_to, p.retrieved_utc, p.access_scope
                FROM passages p
                JOIN sources s ON s.source_id = p.source_id
                WHERE p.source_id = ?
                ORDER BY p.rowid ASC
                """,
                (source_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def search_fts(self, query: str, *, limit: int = 20) -> list[tuple[dict[str, object], float]]:
        """Run sanitized FTS5 search over ``passages_fts`` ordered by BM25 rank."""
        fts_expr = _sanitize_fts_query(query)
        if not fts_expr:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT p.rowid AS row_id, p.passage_id, p.source_id, s.title, s.authority_class,
                       s.jurisdiction, s.is_retainable, p.revision, p.locator, p.content_sha256,
                       p.text, p.valid_from, p.valid_to, p.retrieved_utc, p.access_scope,
                       bm25(passages_fts) AS rank_score
                FROM passages_fts
                JOIN passages p ON p.rowid = passages_fts.rowid
                JOIN sources s ON s.source_id = p.source_id
                WHERE passages_fts MATCH ?
                ORDER BY rank_score ASC
                LIMIT ?
                """,
                (fts_expr, limit),
            ).fetchall()
            return [(dict(r), float(r["rank_score"])) for r in rows]

    def search_vec(
        self, embedding: Sequence[float], *, limit: int = 20
    ) -> list[tuple[dict[str, object], float]]:
        """Run nearest-neighbor vector search over ``passages_vec`` when available."""
        if not self._vec_enabled:
            return []
        with self._lock:
            if self._vec_dim is None:
                exists = self._conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='passages_vec'"
                ).fetchone()
                if exists is None:
                    return []
            if self._vec_dim is not None and len(embedding) != self._vec_dim:
                raise ValueError(
                    f"query vector dim mismatch: expected {self._vec_dim}, got {len(embedding)}"
                )
            rows = self._conn.execute(
                """
                SELECT p.rowid AS row_id, p.passage_id, p.source_id, s.title, s.authority_class,
                       s.jurisdiction, s.is_retainable, p.revision, p.locator, p.content_sha256,
                       p.text, p.valid_from, p.valid_to, p.retrieved_utc, p.access_scope,
                       v.distance AS vec_distance
                FROM passages_vec v
                JOIN passages p ON p.rowid = v.passage_rowid
                JOIN sources s ON s.source_id = p.source_id
                WHERE v.embedding MATCH ? AND k = ?
                ORDER BY v.distance ASC
                """,
                (_pack_vector(embedding), limit),
            ).fetchall()
            return [(dict(r), float(r["vec_distance"])) for r in rows]


class SessionRepository:
    """Repository for ``sessions.db`` sessions, parked tool runs, and append-only ledger."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Bind repository to migrated ``sessions`` SQLite connection."""
        self._conn = conn
        self._lock = threading.RLock()

    def touch_session(
        self,
        *,
        session_id: str,
        tenant: str,
        model: str,
        now_utc: str,
        expires_utc: str,
    ) -> None:
        """Insert or refresh session timestamps in ``sessions``."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (
                    session_id, tenant, model, created_utc, last_seen_utc, expires_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_seen_utc = excluded.last_seen_utc,
                    expires_utc = excluded.expires_utc
                """,
                (session_id, tenant, model, now_utc, now_utc, expires_utc),
            )
            self._conn.commit()

    def get_session(self, session_id: str) -> dict[str, object] | None:
        """Fetch session row by 64-char SHA-256 ``session_id``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def park_run(
        self,
        *,
        run_id: str,
        session_id: str,
        pending_calls: Sequence[dict[str, object]],
        run_state: dict[str, object],
        parked_utc: str,
    ) -> None:
        """Persist a parked tool-call run awaiting client ``functionResponse``."""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO parked_runs (
                    run_id, session_id, pending_calls, run_state_json, parked_utc
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    session_id,
                    json.dumps(list(pending_calls)),
                    json.dumps(run_state),
                    parked_utc,
                ),
            )
            self._conn.commit()

    def pop_parked_run(self, session_id: str) -> dict[str, object] | None:
        """Remove and return the most recent parked run for ``session_id``."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT run_id, session_id, pending_calls, run_state_json, parked_utc
                FROM parked_runs WHERE session_id = ?
                ORDER BY parked_utc DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM parked_runs WHERE run_id = ?", (row["run_id"],))
            self._conn.commit()
            return {
                "run_id": str(row["run_id"]),
                "session_id": str(row["session_id"]),
                "pending_calls": json.loads(str(row["pending_calls"])),
                "run_state": json.loads(str(row["run_state_json"])),
                "parked_utc": str(row["parked_utc"]),
            }

    def append_ledger_entry(
        self,
        *,
        run_id: str,
        attempt_id: str,
        objection_id: str,
        role_axis: int,
        blocking: bool,
        predicate: str,
        state: str,
        closed_by: str | None,
        evidence_ids: Sequence[str],
        created_utc: str,
    ) -> int:
        """Append a ledger entry to the immutable objection log."""
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO ledger_entries (
                    run_id, attempt_id, objection_id, role_axis, blocking,
                    predicate, state, closed_by, evidence_json, created_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    attempt_id,
                    objection_id,
                    role_axis,
                    1 if blocking else 0,
                    predicate,
                    state,
                    closed_by,
                    json.dumps(list(evidence_ids)),
                    created_utc,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def get_ledger_entries(self, run_id: str) -> list[dict[str, object]]:
        """List append-only ledger rows for ``run_id`` in sequence order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM ledger_entries WHERE run_id = ? ORDER BY seq ASC",
                (run_id,),
            ).fetchall()
            out: list[dict[str, object]] = []
            for row in rows:
                item = dict(row)
                item["blocking"] = bool(item["blocking"])
                item["evidence"] = json.loads(str(item["evidence_json"]))
                out.append(item)
            return out


class ReceiptRepository:
    """Repository for ``receipts.db`` signing keys, receipts, function records, and Merkle."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Bind repository to migrated ``receipts`` SQLite connection."""
        self._conn = conn
        self._lock = threading.RLock()

    def register_signing_key(
        self,
        *,
        key_id: str,
        public_key_b64: str,
        valid_from_utc: str,
    ) -> None:
        """Store a new public signing key descriptor."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO signing_keys (
                    key_id, public_key_b64, valid_from_utc, valid_to_utc, revoked_utc
                ) VALUES (?, ?, ?, NULL, NULL)
                """,
                (key_id, public_key_b64, valid_from_utc),
            )
            self._conn.commit()

    def retire_signing_key(self, key_id: str, *, valid_to_utc: str) -> None:
        """Mark an existing key with ``valid_to_utc`` (keeping public key verifiable)."""
        with self._lock:
            self._conn.execute(
                "UPDATE signing_keys SET valid_to_utc = ? WHERE key_id = ?",
                (valid_to_utc, key_id),
            )
            self._conn.commit()

    def get_signing_key(self, key_id: str) -> dict[str, object] | None:
        """Look up a public key record by ``key_id``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM signing_keys WHERE key_id = ?",
                (key_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_active_signing_key(self) -> dict[str, object] | None:
        """Return the latest non-revoked signing key with open validity."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM signing_keys
                WHERE valid_to_utc IS NULL AND revoked_utc IS NULL
                ORDER BY valid_from_utc DESC LIMIT 1
                """
            ).fetchone()
            return dict(row) if row is not None else None

    def list_signing_keys(self) -> list[dict[str, object]]:
        """List all registered public signing key descriptors."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM signing_keys ORDER BY valid_from_utc ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def list_chain_receipts(self, chain_id: str) -> list[dict[str, object]]:
        """Return ordered ``(receipt_id, chain_seq, receipt_sha256)`` records for ``chain_id``."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT receipt_id, chain_seq, receipt_sha256
                FROM receipts WHERE chain_id = ?
                ORDER BY chain_seq ASC
                """,
                (chain_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def last_chain_tip(self, chain_id: str) -> tuple[int, str]:
        """Return ``(chain_seq, previous_hash)`` tip for ``chain_id``."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT chain_seq, receipt_sha256
                FROM receipts WHERE chain_id = ?
                ORDER BY chain_seq DESC LIMIT 1
                """,
                (chain_id,),
            ).fetchone()
            if row is None:
                return (0, "GENESIS")
            return (int(row["chain_seq"]), str(row["receipt_sha256"]))

    def insert_receipt(
        self,
        *,
        receipt_id: str,
        chain_id: str,
        chain_seq: int,
        previous_hash: str,
        receipt_sha256: str,
        response_sha256: str,
        release_mode: str,
        profile: str,
        key_id: str,
        receipt_jcs: str,
        signature_b64: str,
        anchoring_profile: str,
        sealed_utc: str,
        function_records: Sequence[dict[str, object]] = (),
    ) -> None:
        """Atomically insert an immutable receipt and its function invocation records."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO receipts (
                    receipt_id, chain_id, chain_seq, previous_hash, receipt_sha256,
                    response_sha256, release_mode, profile, key_id, receipt_jcs,
                    signature_b64, anchoring_profile, sealed_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    chain_id,
                    chain_seq,
                    previous_hash,
                    receipt_sha256,
                    response_sha256,
                    release_mode,
                    profile,
                    key_id,
                    receipt_jcs,
                    signature_b64,
                    anchoring_profile,
                    sealed_utc,
                ),
            )
            for rec in function_records:
                self._conn.execute(
                    """
                    INSERT INTO function_records (
                        receipt_id, seq, dvss_id, version, level,
                        implementation, outcome, duration_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt_id,
                        int(str(rec["seq"])),
                        str(rec["dvss_id"]),
                        str(rec["version"]),
                        str(rec["level"]),
                        str(rec["implementation"]),
                        str(rec["outcome"]),
                        float(str(rec["duration_ms"])),
                    ),
                )
            self._conn.commit()

    def get_receipt(self, receipt_id: str) -> dict[str, object] | None:
        """Return stored receipt envelope + metadata by ``receipt_id``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_receipts_between(self, from_utc: str, to_utc: str) -> list[dict[str, object]]:
        """Return sealed receipts in half-open ``[from_utc, to_utc)`` order by chain sequence."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM receipts
                WHERE sealed_utc >= ? AND sealed_utc < ?
                ORDER BY chain_seq ASC
                """,
                (from_utc, to_utc),
            ).fetchall()
            return [dict(r) for r in rows]

    def insert_merkle_checkpoint(
        self,
        *,
        root_sha256: str,
        first_receipt: str,
        last_receipt: str,
        anchored_utc: str,
        anchor_ref: str,
    ) -> int:
        """Record a local WORM Merkle root checkpoint."""
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO merkle_checkpoints (
                    root_sha256, first_receipt, last_receipt, anchored_utc, anchor_ref
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (root_sha256, first_receipt, last_receipt, anchored_utc, anchor_ref),
            )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def list_merkle_checkpoints(self) -> list[dict[str, object]]:
        """List Merkle checkpoints in ascending order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM merkle_checkpoints ORDER BY checkpoint_id ASC"
            ).fetchall()
            return [dict(r) for r in rows]


class OpsRepository:
    """Repository for ``ops.db`` model calls, run metrics, drift state, and egress logs."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Bind repository to migrated ``ops`` SQLite connection."""
        self._conn = conn
        self._lock = threading.RLock()

    def record_model_call(
        self,
        *,
        call_id: str,
        run_id: str,
        job: str,
        model_id: str,
        model_version: str | None,
        input_tokens: int,
        output_tokens: int,
        thought_tokens: int,
        cost_usd: float,
        duration_ms: float,
        attempts: int,
        status: str,
        called_utc: str,
    ) -> None:
        """Persist one model call telemetry record."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO model_calls (
                    call_id, run_id, job, model_id, model_version,
                    input_tokens, output_tokens, thought_tokens, cost_usd,
                    duration_ms, attempts, status, called_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    run_id,
                    job,
                    model_id,
                    model_version,
                    input_tokens,
                    output_tokens,
                    thought_tokens,
                    cost_usd,
                    duration_ms,
                    attempts,
                    status,
                    called_utc,
                ),
            )
            self._conn.commit()

    def record_run_metrics(
        self,
        *,
        run_id: str,
        tier: int,
        profile: str,
        release_mode: str,
        retries: int,
        escalated: bool,
        u: float | None,
        duration_ms: float,
        cost_usd: float,
        finished_utc: str,
    ) -> None:
        """Persist aggregated per-run verification metrics."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO run_metrics (
                    run_id, tier, profile, release_mode, retries,
                    escalated, u, duration_ms, cost_usd, finished_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    tier,
                    profile,
                    release_mode,
                    retries,
                    1 if escalated else 0,
                    u,
                    duration_ms,
                    cost_usd,
                    finished_utc,
                ),
            )
            self._conn.commit()

    def get_drift_state(self) -> dict[str, object] | None:
        """Return singleton CUSUM drift state row if initialized."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM drift_state WHERE id = 1").fetchone()
            if row is None:
                return None
            out = dict(row)
            out["is_latched"] = bool(out["is_latched"])
            return out

    def upsert_drift_state(
        self,
        *,
        c_t: float,
        mu0: float,
        delta: float,
        lambda_val: float,
        is_latched: bool,
        latch_reason: str | None,
        updated_utc: str,
    ) -> None:
        """Insert or update the singleton CUSUM drift state (``id = 1``)."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO drift_state (
                    id, c_t, mu0, delta, lambda, is_latched, latch_reason, updated_utc
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    c_t = excluded.c_t,
                    mu0 = excluded.mu0,
                    delta = excluded.delta,
                    lambda = excluded.lambda,
                    is_latched = excluded.is_latched,
                    latch_reason = excluded.latch_reason,
                    updated_utc = excluded.updated_utc
                """,
                (
                    c_t,
                    mu0,
                    delta,
                    lambda_val,
                    1 if is_latched else 0,
                    latch_reason,
                    updated_utc,
                ),
            )
            self._conn.commit()

    def record_egress(
        self,
        *,
        host: str,
        bytes_out: int,
        bytes_in: int,
        is_allowed: bool,
        logged_utc: str,
    ) -> None:
        """Append one egress audit log entry."""
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO egress_log (host, bytes_out, bytes_in, is_allowed, logged_utc)
                VALUES (?, ?, ?, ?, ?)
                """,
                (host, bytes_out, bytes_in, 1 if is_allowed else 0, logged_utc),
            )
            self._conn.commit()


__all__ = [
    "EvidenceRepository",
    "OpsRepository",
    "ReceiptRepository",
    "SessionRepository",
]
