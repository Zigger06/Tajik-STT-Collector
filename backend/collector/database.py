from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS volunteers (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    region TEXT NOT NULL DEFAULT '',
    dialect TEXT NOT NULL DEFAULT '',
    consent_version TEXT NOT NULL DEFAULT 'v1',
    consent_active INTEGER NOT NULL DEFAULT 1 CHECK (consent_active IN (0, 1)),
    revoked_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS device_credentials (
    volunteer_id TEXT PRIMARY KEY REFERENCES volunteers(id) ON DELETE CASCADE,
    secret_salt TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS texts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    normalized TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT '',
    submitted_by TEXT REFERENCES volunteers(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending_review'
        CHECK (status IN ('pending_review', 'needs_admin', 'approved', 'rejected')),
    required_recordings INTEGER NOT NULL DEFAULT 5,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS text_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text_id INTEGER NOT NULL REFERENCES texts(id) ON DELETE CASCADE,
    volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
    verdict TEXT NOT NULL CHECK (verdict IN ('correct', 'correction', 'reject')),
    correction TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (text_id, volunteer_id)
);

CREATE TABLE IF NOT EXISTS recordings (
    id TEXT PRIMARY KEY,
    text_id INTEGER NOT NULL REFERENCES texts(id) ON DELETE RESTRICT,
    volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE RESTRICT,
    file_path TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    sample_rate INTEGER NOT NULL DEFAULT 16000,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS audio_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
    verdict TEXT NOT NULL CHECK (verdict IN ('approve', 'reject')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (recording_id, volunteer_id)
);

CREATE INDEX IF NOT EXISTS idx_texts_status ON texts(status);
CREATE INDEX IF NOT EXISTS idx_recordings_text_status ON recordings(text_id, status);
CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings(status);
CREATE INDEX IF NOT EXISTS idx_recordings_volunteer_created
    ON recordings(volunteer_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_text_reviews_text ON text_reviews(text_id);
CREATE INDEX IF NOT EXISTS idx_audio_reviews_recording ON audio_reviews(recording_id);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

            text_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(texts)")
            }
            if "submitted_by" not in text_columns:
                connection.execute("ALTER TABLE texts ADD COLUMN submitted_by TEXT")

            volunteer_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(volunteers)")
            }
            if "consent_active" not in volunteer_columns:
                connection.execute(
                    "ALTER TABLE volunteers ADD COLUMN consent_active INTEGER NOT NULL DEFAULT 1"
                )
            if "revoked_at" not in volunteer_columns:
                connection.execute("ALTER TABLE volunteers ADD COLUMN revoked_at TEXT")
