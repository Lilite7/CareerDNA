"""Database access for the AI package. Uses the same SQLite file as the rest of CareerDNA.
Set CAREERDNA_DB to point somewhere else (used by tests). All queries elsewhere are parameterised."""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def db_path() -> str:
    return os.getenv("CAREERDNA_DB") or os.path.join(BASE_DIR, "careerdna.db")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


AI_LOG_DDL = """
CREATE TABLE IF NOT EXISTS ai_eval_log (
    log_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    test_case_id      TEXT,
    candidate_ref     TEXT,      -- salted hash, not the real id
    intent            TEXT,
    question_chars    INTEGER,   -- length only; the question text is NOT stored
    model_name        TEXT,
    model_digest      TEXT,
    evidence_refs     TEXT,      -- JSON list of record refs such as project:3
    backend_numbers   TEXT,      -- JSON of official numbers supplied to the model
    verification      TEXT,      -- passed | qualified | regenerated | fallback | skipped
    unsupported_flags TEXT,      -- JSON list of issue codes
    regenerated       INTEGER DEFAULT 0,
    latency_ms        INTEGER,
    error_code        TEXT
);
"""


EMBEDDING_DDL = """
CREATE TABLE IF NOT EXISTS ai_embedding (
    candidate_id INTEGER NOT NULL,   -- owner. 0 = shared job-catalogue documents (type 'job') ONLY
    ref          TEXT    NOT NULL,   -- record reference, e.g. project:3
    model        TEXT    NOT NULL,   -- embedding model name; vectors from different models are never mixed
    text_hash    TEXT    NOT NULL,   -- sha256 of the embedded text; a different hash means the vector is stale
    dim          INTEGER NOT NULL,
    vector       BLOB    NOT NULL,   -- little-endian float32
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (candidate_id, ref, model)
);
CREATE INDEX IF NOT EXISTS idx_ai_embedding_owner ON ai_embedding(candidate_id, model);
"""


def ensure_ai_tables() -> None:
    """Additive, backward-compatible migration: creates the evaluation log table if missing."""
    conn = connect()
    try:
        conn.executescript(AI_LOG_DDL)
        conn.executescript(EMBEDDING_DDL)
        conn.commit()
    finally:
        conn.close()
