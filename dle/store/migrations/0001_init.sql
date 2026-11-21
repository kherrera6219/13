-- 0001_init.sql (G8). Five SQLite databases; each section is applied to its own file.
-- Conventions: DLE-STD-001 §5. All timestamps ISO 8601 UTC text (*_utc). WAL mode. Append-only tables
-- are protected by triggers; retention purge runs as a privileged maintenance job that drops the triggers
-- inside a transaction, purges, and restores them, logging the event.

-- ============================================================ registry.db
-- @database registry
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE registry_releases (
    release_id        TEXT PRIMARY KEY,
    manifest_sha256   TEXT NOT NULL CHECK (length(manifest_sha256) = 64),
    created_utc       TEXT NOT NULL,
    approved_by       TEXT NOT NULL,
    is_active         INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1))
);
CREATE UNIQUE INDEX ux_registry_releases_active ON registry_releases (is_active) WHERE is_active = 1;

CREATE TABLE axis_atoms (
    release_id     TEXT NOT NULL REFERENCES registry_releases (release_id),
    axis_id        INTEGER NOT NULL CHECK (axis_id BETWEEN 1 AND 13),
    canonical_str  TEXT NOT NULL,
    meta_tag       TEXT NOT NULL,
    label          TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired', 'alias')),
    alias_of       TEXT,
    PRIMARY KEY (release_id, canonical_str)
);

CREATE TABLE spine_edges (
    release_id   TEXT NOT NULL REFERENCES registry_releases (release_id),
    src          TEXT NOT NULL,
    dst          TEXT NOT NULL,
    edge_type    TEXT NOT NULL,
    weight       REAL NOT NULL CHECK (weight >= 0),
    PRIMARY KEY (release_id, src, dst, edge_type)
);

CREATE TABLE crosswalks (
    release_id   TEXT NOT NULL REFERENCES registry_releases (release_id),
    axis_id      INTEGER NOT NULL CHECK (axis_id IN (3, 6, 7)),
    from_atom    TEXT NOT NULL,
    to_atom      TEXT NOT NULL,
    relation     TEXT NOT NULL,
    PRIMARY KEY (release_id, axis_id, from_atom, to_atom)
);

CREATE TABLE persona_profiles (
    profile_id     TEXT PRIMARY KEY,
    role_axis      INTEGER NOT NULL CHECK (role_axis BETWEEN 8 AND 11),
    version        TEXT NOT NULL,
    profile_json   TEXT NOT NULL CHECK (json_valid(profile_json)),
    status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired'))
);

CREATE TABLE ka_catalog (
    ka_id          TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    dvss_id        TEXT,
    binding_level  TEXT NOT NULL CHECK (binding_level IN ('kernel', 'policy', 'catalog_only', 'reserved', 'outside_branch')),
    row_json       TEXT NOT NULL CHECK (json_valid(row_json))
);

-- ============================================================ evidence.db
-- @database evidence
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE sources (
    source_id        TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    authority_class  TEXT NOT NULL CHECK (authority_class IN ('primary_text', 'binding_instrument', 'peer_reviewed',
                         'industry_practice', 'unhydrated_synthesis', 'app_tool', 'google_builtin_tool')),
    jurisdiction     TEXT,
    is_retainable    INTEGER NOT NULL DEFAULT 1 CHECK (is_retainable IN (0, 1)),
    registered_utc   TEXT NOT NULL,
    retired_utc      TEXT
);

CREATE TABLE passages (
    passage_id      TEXT PRIMARY KEY,               -- source_id@revision#locator
    source_id       TEXT NOT NULL REFERENCES sources (source_id),
    revision        TEXT NOT NULL,
    locator         TEXT NOT NULL,
    content_sha256  TEXT NOT NULL CHECK (length(content_sha256) = 64),
    text            TEXT NOT NULL,
    valid_from      TEXT,
    valid_to        TEXT,                           -- half-open; NULL = open end
    retrieved_utc   TEXT NOT NULL,
    access_scope    TEXT NOT NULL DEFAULT 'tenant'
);
CREATE INDEX ix_passages_source ON passages (source_id, revision);

CREATE VIRTUAL TABLE passages_fts USING fts5 (text, content = 'passages', content_rowid = 'rowid');
-- Vector index (sqlite-vec) is created at runtime once the extension is loaded:
--   CREATE VIRTUAL TABLE passages_vec USING vec0 (passage_rowid INTEGER PRIMARY KEY, embedding FLOAT[<dim>]);

CREATE TRIGGER tr_passages_no_update BEFORE UPDATE ON passages
BEGIN SELECT RAISE (ABORT, 'passages are append-only; add a new revision'); END;

-- ============================================================ sessions.db
-- @database sessions
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE sessions (
    session_id     TEXT PRIMARY KEY CHECK (length(session_id) = 64),
    tenant         TEXT NOT NULL,
    model          TEXT NOT NULL,
    created_utc    TEXT NOT NULL,
    last_seen_utc  TEXT NOT NULL,
    expires_utc    TEXT NOT NULL
);

CREATE TABLE parked_runs (
    run_id           TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES sessions (session_id),
    pending_calls    TEXT NOT NULL CHECK (json_valid(pending_calls)),
    run_state_json   TEXT NOT NULL CHECK (json_valid(run_state_json)),
    parked_utc       TEXT NOT NULL
);

CREATE TABLE overlay_nodes (
    session_id     TEXT NOT NULL REFERENCES sessions (session_id),
    node_id        TEXT NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('selected', 'temporary', 'hypothesis')),
    payload_json   TEXT NOT NULL CHECK (json_valid(payload_json)),
    created_utc    TEXT NOT NULL,
    PRIMARY KEY (session_id, node_id)
);

CREATE TABLE ledger_entries (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL,
    attempt_id     TEXT NOT NULL,
    objection_id   TEXT NOT NULL,
    role_axis      INTEGER NOT NULL CHECK (role_axis BETWEEN 8 AND 11),
    blocking       INTEGER NOT NULL CHECK (blocking IN (0, 1)),
    predicate      TEXT NOT NULL,
    state          TEXT NOT NULL CHECK (state IN ('open', 'closed')),
    closed_by      TEXT CHECK (closed_by IS NULL OR closed_by = 'verifier'),
    evidence_json  TEXT NOT NULL CHECK (json_valid(evidence_json)),
    created_utc    TEXT NOT NULL,
    CHECK (state = 'open' OR (closed_by = 'verifier' AND evidence_json <> '[]'))
);
CREATE INDEX ix_ledger_run ON ledger_entries (run_id, objection_id);
CREATE TRIGGER tr_ledger_no_update BEFORE UPDATE ON ledger_entries
BEGIN SELECT RAISE (ABORT, 'ledger is append-only'); END;
CREATE TRIGGER tr_ledger_no_delete BEFORE DELETE ON ledger_entries
BEGIN SELECT RAISE (ABORT, 'ledger is append-only'); END;

-- ============================================================ receipts.db
-- @database receipts
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE signing_keys (
    key_id          TEXT PRIMARY KEY,
    public_key_b64  TEXT NOT NULL,
    valid_from_utc  TEXT NOT NULL,
    valid_to_utc    TEXT,
    revoked_utc     TEXT
);

CREATE TABLE receipts (
    receipt_id        TEXT PRIMARY KEY,
    chain_id          TEXT NOT NULL,
    chain_seq         INTEGER NOT NULL,
    previous_hash     TEXT NOT NULL,
    receipt_sha256    TEXT NOT NULL UNIQUE CHECK (length(receipt_sha256) = 64),
    response_sha256   TEXT NOT NULL CHECK (length(response_sha256) = 64),
    release_mode      TEXT NOT NULL CHECK (release_mode IN ('released', 'released_advisory', 'held', 'passthrough', 'cancelled')),
    profile           TEXT NOT NULL,
    key_id            TEXT NOT NULL REFERENCES signing_keys (key_id),
    receipt_jcs       TEXT NOT NULL CHECK (json_valid(receipt_jcs)),
    signature_b64     TEXT NOT NULL,
    anchoring_profile TEXT NOT NULL CHECK (anchoring_profile IN ('external_transparency_log', 'customer_hosted_log', 'local_worm_merkle')),
    sealed_utc        TEXT NOT NULL,
    UNIQUE (chain_id, chain_seq)
);

CREATE TABLE function_records (
    receipt_id      TEXT NOT NULL REFERENCES receipts (receipt_id),
    seq             INTEGER NOT NULL,
    dvss_id         TEXT NOT NULL CHECK (dvss_id GLOB 'DVSS-[KP][0-9][0-9]'),
    version         TEXT NOT NULL,
    level           TEXT NOT NULL CHECK (level IN ('kernel', 'policy')),
    implementation  TEXT NOT NULL CHECK (implementation IN ('host', 'adapter', 'host_fallback')),
    outcome         TEXT NOT NULL CHECK (outcome IN ('ok', 'skipped', 'flag', 'objection', 'hold', 'error')),
    duration_ms     REAL NOT NULL CHECK (duration_ms >= 0),
    PRIMARY KEY (receipt_id, seq),
    CHECK (outcome <> 'hold' OR dvss_id IN ('DVSS-K04', 'DVSS-K11', 'DVSS-K12'))
);

CREATE TABLE merkle_checkpoints (
    checkpoint_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    root_sha256     TEXT NOT NULL CHECK (length(root_sha256) = 64),
    first_receipt   TEXT NOT NULL,
    last_receipt    TEXT NOT NULL,
    anchored_utc    TEXT,
    anchor_ref      TEXT
);

CREATE TRIGGER tr_receipts_no_update BEFORE UPDATE ON receipts
BEGIN SELECT RAISE (ABORT, 'receipts are append-only'); END;
CREATE TRIGGER tr_function_records_no_update BEFORE UPDATE ON function_records
BEGIN SELECT RAISE (ABORT, 'function records are append-only'); END;

-- ============================================================ ops.db
-- @database ops
PRAGMA journal_mode = WAL;

CREATE TABLE model_calls (
    call_id          TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL,
    job              TEXT NOT NULL,
    model_id         TEXT NOT NULL,
    model_version    TEXT,
    input_tokens     INTEGER NOT NULL DEFAULT 0,
    output_tokens    INTEGER NOT NULL DEFAULT 0,
    thought_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd         REAL NOT NULL DEFAULT 0,
    duration_ms      REAL NOT NULL,
    attempts         INTEGER NOT NULL DEFAULT 1,
    status           TEXT NOT NULL CHECK (status IN ('ok', 'retried', 'failed')),
    called_utc       TEXT NOT NULL
);
CREATE INDEX ix_model_calls_run ON model_calls (run_id);

CREATE TABLE run_metrics (
    run_id         TEXT PRIMARY KEY,
    tier           INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 3),
    profile        TEXT NOT NULL,
    release_mode   TEXT NOT NULL,
    retries        INTEGER NOT NULL CHECK (retries BETWEEN 0 AND 2),
    escalated      INTEGER NOT NULL CHECK (escalated IN (0, 1)),
    u              REAL,
    duration_ms    REAL NOT NULL,
    cost_usd       REAL NOT NULL,
    finished_utc   TEXT NOT NULL
);

CREATE TABLE drift_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    c_t            REAL NOT NULL DEFAULT 0,
    mu0            REAL NOT NULL,
    delta          REAL NOT NULL DEFAULT 0.02,
    lambda         REAL NOT NULL,
    is_latched     INTEGER NOT NULL DEFAULT 0 CHECK (is_latched IN (0, 1)),
    latch_reason   TEXT,
    updated_utc    TEXT NOT NULL
);

CREATE TABLE egress_log (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    host           TEXT NOT NULL,
    bytes_out      INTEGER NOT NULL,
    bytes_in       INTEGER NOT NULL,
    is_allowed     INTEGER NOT NULL CHECK (is_allowed IN (0, 1)),
    logged_utc     TEXT NOT NULL
);
