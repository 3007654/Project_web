"""
Database layer: SQLite, normalized around the model discussed for the
platform's trust/audit layer -

    subcontractor_profiles
        |
        +-- verification_records   (CIPC, CIDB, and any future check type)
        +-- subcontractor_references
        +-- audit_events           (a timestamped log of what happened, for whom)

This is deliberately just the subcontractor-side slice of the bigger picture
(tenders / awards / matches / contact_unlock come later) - narrow enough to
build and test now, shaped so those tables slot in later without a rewrite:
audit_events already has a generic subcontractor_id link and an event_type,
so a future tender_id / match_id column is an additive change, not a redesign.
"""

import sqlite3
from datetime import datetime, timezone

SCHEMA = """
-- Authorised verifiers. Only someone with a row here (and the right
-- password) can ever record a verification check - a subcontractor
-- submitting their own profile has no way to mark themselves verified.
CREATE TABLE IF NOT EXISTS verifier_users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    email               TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,
    role                TEXT NOT NULL DEFAULT 'VERIFIER',  -- 'ADMIN' or 'VERIFIER'
    active              INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subcontractor_profiles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name        TEXT NOT NULL,
    contact_name        TEXT NOT NULL,
    phone               TEXT NOT NULL,
    email               TEXT NOT NULL,
    trade               TEXT NOT NULL,
    province            TEXT NOT NULL,
    years_active        INTEGER NOT NULL,
    tier                TEXT NOT NULL DEFAULT 'free',
    verification_score  INTEGER NOT NULL DEFAULT 0,
    verification_tier   TEXT NOT NULL DEFAULT 'Unverified',
    -- Workflow status, separate from the score/tier above:
    -- 'pending'      - submitted, no check has been performed yet
    -- 'verified'     - at least one check on file, none needing review,
    --                  not all of them lapsed/failed
    -- 'not_verified' - every check on file came back negative
    -- 'needs_review' - the latest of some check came back ambiguous
    profile_status      TEXT NOT NULL DEFAULT 'pending',
    created_at          TEXT NOT NULL
);

-- One row per check performed. Never overwritten - a re-check adds a new
-- row, so the history (including a check that later lapses) stays intact.
CREATE TABLE IF NOT EXISTS verification_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    subcontractor_id    INTEGER NOT NULL REFERENCES subcontractor_profiles(id),
    check_type          TEXT NOT NULL,   -- 'CIPC', 'CIDB', or a future check
    outcome             TEXT NOT NULL,   -- 'verified' | 'not_verified' | 'needs_review'
    reference_number    TEXT,             -- CIPC registration number / CIDB CRS number
    grade               INTEGER,          -- CIDB grade 1-9; NULL for other check types
    source              TEXT NOT NULL,    -- e.g. "CIPC eServices portal"
    notes               TEXT,             -- what the verifier actually observed
    checked_date        TEXT NOT NULL,
    verified_by_user_id INTEGER NOT NULL REFERENCES verifier_users(id),
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subcontractor_references (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    subcontractor_id    INTEGER NOT NULL REFERENCES subcontractor_profiles(id),
    client_name         TEXT NOT NULL,
    comment             TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    subcontractor_id    INTEGER REFERENCES subcontractor_profiles(id),
    event_type          TEXT NOT NULL,
    description         TEXT NOT NULL,
    created_at          TEXT NOT NULL
);
"""


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path):
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")