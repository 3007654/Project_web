"""
Database layer: SQLite.

    verifier_users              (authorised checkers only - no self-registration)

    subcontractor_profiles
        |
        +-- verification_records     (CIPC, CIDB, or a future check type;
        |                              never overwritten - a re-check adds a
        |                              new row, so history including a lapse
        |                              stays intact)
        +-- subcontractor_references  (with optional evidence link + value)
        +-- subcontractor_skills
        +-- subcontractor_equipment
        +-- audit_events              (timestamped log: what happened, for whom)

Deliberately just the subcontractor-side slice of the bigger picture
discussed (tenders / awards / matches / contact_unlock come later) - shaped
so those attach later without a rewrite: audit_events already has a generic
subcontractor_id link and a free-text event_type.
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

    -- 'available' | 'engaged' | 'available_from'
    availability_status TEXT NOT NULL DEFAULT 'available',
    availability_date   TEXT,   -- only set (and only meaningful) when status = 'available_from'

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

-- One row per check performed. Never overwritten.
CREATE TABLE IF NOT EXISTS verification_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    subcontractor_id    INTEGER NOT NULL REFERENCES subcontractor_profiles(id),
    check_type          TEXT NOT NULL,    -- 'CIPC', 'CIDB', or a future check
    outcome             TEXT NOT NULL,    -- 'verified' | 'not_verified' | 'needs_review'
    reference_number    TEXT,             -- CIPC registration number / CIDB CRS number
    grade               INTEGER,          -- CIDB grade 1-9; NULL for other check types
    source              TEXT NOT NULL,    -- e.g. "CIPC eServices portal (eservices.cipc.co.za)"
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
    evidence_url         TEXT,             -- optional link to a photo/document hosted elsewhere
    project_value        TEXT,             -- optional, free text (e.g. "R450,000")
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subcontractor_skills (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    subcontractor_id    INTEGER NOT NULL REFERENCES subcontractor_profiles(id),
    skill_name          TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subcontractor_equipment (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    subcontractor_id    INTEGER NOT NULL REFERENCES subcontractor_profiles(id),
    equipment_name      TEXT NOT NULL,
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