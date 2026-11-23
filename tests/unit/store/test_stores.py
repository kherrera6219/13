"""Unit tests for SQLite migrations, append-only triggers, FTS5, sqlite-vec, and repos."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dle.observability import sha256_text
from dle.store import (
    DATABASE_NAMES,
    EvidenceRepository,
    OpsRepository,
    ReceiptRepository,
    SessionRepository,
    apply_migrations,
    open_stores,
)


def test_open_stores_migrates_all_five_dbs_idempotently(tmp_path: Path) -> None:
    """All 5 SQLite DBs migrate cleanly and re-running migrations is a no-op."""
    bundle = open_stores(tmp_path / "stores", enable_vec=True)
    try:
        assert bundle.vec_enabled is True
        for name in DATABASE_NAMES:
            assert (tmp_path / "stores" / f"{name}.db").is_file()
            conn = getattr(bundle, name)
            assert apply_migrations(conn, database=name) == []
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            assert str(mode).lower() == "wal"
    finally:
        bundle.close()


def test_append_only_triggers_and_check_constraints() -> None:
    """passages, ledger_entries, receipts, and function_records enforce immutability & CHECKs."""
    bundle = open_stores(None, enable_vec=True)
    try:
        ev = EvidenceRepository(bundle.evidence, vec_enabled=bundle.vec_enabled)
        ev.register_source(
            source_id="src-1",
            title="Policy",
            authority_class="binding_instrument",
            jurisdiction="US-TX",
            is_retainable=True,
            registered_utc="2026-11-22T00:00:00Z",
        )
        ev.insert_passage(
            passage_id="src-1@rev-1#p001",
            source_id="src-1",
            revision="rev-1",
            locator="p001",
            content_sha256=sha256_text("approved cold chain substitution"),
            body_text="approved cold chain substitution",
            valid_from="2026-01-01",
            valid_to=None,
            retrieved_utc="2026-11-22T00:00:00Z",
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            bundle.evidence.execute(
                "UPDATE passages SET text = 'tampered' WHERE passage_id = 'src-1@rev-1#p001'"
            )

        sess = SessionRepository(bundle.sessions)
        sess.touch_session(
            session_id="a" * 64,
            tenant="t1",
            model="dle-13axis-strict",
            now_utc="2026-11-22T00:00:00Z",
            expires_utc="2026-11-23T00:00:00Z",
        )
        sess.park_run(
            run_id="run-1",
            session_id="a" * 64,
            pending_calls=[{"name": "tool_a"}],
            run_state={"step": 4},
            parked_utc="2026-11-22T00:00:00Z",
        )
        popped = sess.pop_parked_run("a" * 64)
        assert popped is not None and popped["run_id"] == "run-1"

        sess.append_ledger_entry(
            run_id="run-1",
            attempt_id="att-0",
            objection_id="obj-1",
            role_axis=10,
            blocking=True,
            predicate="requires_cold_chain_signoff",
            state="open",
            closed_by=None,
            evidence_ids=[],
            created_utc="2026-11-22T00:00:00Z",
        )
        assert len(sess.get_ledger_entries("run-1")) == 1

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            bundle.sessions.execute("UPDATE ledger_entries SET state = 'closed'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            bundle.sessions.execute("DELETE FROM ledger_entries")
        with pytest.raises(sqlite3.IntegrityError):
            sess.append_ledger_entry(
                run_id="run-1",
                attempt_id="att-0",
                objection_id="obj-bad",
                role_axis=10,
                blocking=True,
                predicate="closure_without_evidence",
                state="closed",
                closed_by="verifier",
                evidence_ids=[],
                created_utc="2026-11-22T00:00:00Z",
            )

        rcpt = ReceiptRepository(bundle.receipts)
        rcpt.register_signing_key(
            key_id="k1",
            public_key_b64="pub-b64",
            valid_from_utc="2026-11-22T00:00:00Z",
        )
        assert rcpt.last_chain_tip("main") == (0, "GENESIS")
        rcpt.insert_receipt(
            receipt_id="11111111-1111-4111-8111-111111111111",
            chain_id="main",
            chain_seq=1,
            previous_hash="GENESIS",
            receipt_sha256="b" * 64,
            response_sha256="c" * 64,
            release_mode="released",
            profile="strict",
            key_id="k1",
            receipt_jcs='{"ok":true}',
            signature_b64="sig",
            anchoring_profile="local_worm_merkle",
            sealed_utc="2026-11-22T00:00:00Z",
            function_records=[
                {
                    "seq": 0,
                    "dvss_id": "DVSS-K04",
                    "version": "1.0.0",
                    "level": "kernel",
                    "implementation": "host",
                    "outcome": "ok",
                    "duration_ms": 1.2,
                }
            ],
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            bundle.receipts.execute("UPDATE receipts SET release_mode = 'held' WHERE chain_seq = 1")
        with pytest.raises(sqlite3.IntegrityError):
            rcpt.insert_receipt(
                receipt_id="22222222-2222-4222-8222-222222222222",
                chain_id="main",
                chain_seq=2,
                previous_hash="b" * 64,
                receipt_sha256="d" * 64,
                response_sha256="e" * 64,
                release_mode="held",
                profile="strict",
                key_id="k1",
                receipt_jcs='{"ok":false}',
                signature_b64="sig2",
                anchoring_profile="local_worm_merkle",
                sealed_utc="2026-11-22T00:01:00Z",
                function_records=[
                    {
                        "seq": 0,
                        "dvss_id": "DVSS-K01",
                        "version": "1.0.0",
                        "level": "kernel",
                        "implementation": "host",
                        "outcome": "hold",
                        "duration_ms": 0.5,
                    }
                ],
            )
    finally:
        bundle.close()


def test_evidence_fts5_sqlite_vec_and_ops_repository() -> None:
    """FTS5, sqlite-vec KNN search, source pagination, and OpsRepository work cleanly."""
    bundle = open_stores(None, enable_vec=True)
    try:
        ev = EvidenceRepository(bundle.evidence, vec_enabled=True)
        for i in range(3):
            sid = f"src-{i}"
            ev.register_source(
                source_id=sid,
                title=f"Doc {i}",
                authority_class="primary_text",
                jurisdiction="US-TX",
                is_retainable=True,
                registered_utc=f"2026-11-2{i}T00:00:00Z",
            )
            vec = [1.0, 0.0, 0.0, 0.0] if i == 0 else [0.0, 1.0, 0.0, 0.0]
            ev.insert_passage(
                passage_id=f"{sid}@rev-1#p001",
                source_id=sid,
                revision="rev-1",
                locator="p001",
                content_sha256=sha256_text(f"passage body {i}"),
                body_text="cold chain warehouse substitution rule"
                if i == 0
                else f"other topic {i}",
                valid_from="2026-01-01",
                valid_to=None,
                retrieved_utc="2026-11-22T00:00:00Z",
                embedding=vec,
            )

        page1, next_tok = ev.list_sources(limit=2, offset=0)
        assert len(page1) == 2 and next_tok == "2"
        page2, end_tok = ev.list_sources(limit=2, offset=2)
        assert len(page2) == 1 and end_tok is None

        fts_hits = ev.search_fts("warehouse! substitution?", limit=5)
        assert len(fts_hits) == 1
        assert fts_hits[0][0]["source_id"] == "src-0"

        vec_hits = ev.search_vec([0.99, 0.01, 0.0, 0.0], limit=2)
        assert len(vec_hits) == 2
        assert vec_hits[0][0]["source_id"] == "src-0"

        ops = OpsRepository(bundle.ops)
        ops.record_model_call(
            call_id="c1",
            run_id="r1",
            job="writer",
            model_id="gemini-4-carbon",
            model_version="gemini-4-carbon-001",
            input_tokens=100,
            output_tokens=50,
            thought_tokens=0,
            cost_usd=0.001,
            duration_ms=12.3,
            attempts=1,
            status="ok",
            called_utc="2026-11-22T00:00:00Z",
        )
        ops.upsert_drift_state(
            c_t=0.05,
            mu0=0.04,
            delta=0.02,
            lambda_val=0.5,
            is_latched=False,
            latch_reason=None,
            updated_utc="2026-11-22T00:00:00Z",
        )
        state = ops.get_drift_state()
        assert (
            state is not None
            and state["is_latched"] is False
            and state["c_t"] == pytest.approx(0.05)
        )
    finally:
        bundle.close()
