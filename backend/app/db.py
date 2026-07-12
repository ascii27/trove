"""SQLite access layer.

Plain stdlib sqlite3 (no ORM) — the app is single-user and the schema is small.
A fresh connection is opened per operation/request; SQLite handles this well and
it sidesteps thread-affinity between the request threadpool and the worker thread.
WAL mode lets the background worker write while the API reads.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    url_canonical     TEXT NOT NULL UNIQUE,
    lane              TEXT NOT NULL DEFAULT 'saved',      -- 'saved' | 'feed' (P1: always 'saved')
    title             TEXT,
    author            TEXT,
    source            TEXT,
    publish_date      TEXT,
    word_count        INTEGER,
    reading_minutes   INTEGER,
    content_html      TEXT,
    content_text      TEXT,
    original_url      TEXT NOT NULL,
    date_saved        TEXT NOT NULL DEFAULT (datetime('now')),
    read_state        TEXT NOT NULL DEFAULT 'unread',     -- unread|reading|read|archived
    extraction_status TEXT NOT NULL DEFAULT 'pending',    -- pending|extracting|extracted|partial|failed
    enrichment_status TEXT NOT NULL DEFAULT 'pending',    -- pending|enriching|done|failed
    summary           TEXT,
    category          TEXT,
    source_type       TEXT,                               -- primary|secondary|analysis
    error_message     TEXT
);

CREATE TABLE IF NOT EXISTS topics (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_topics_name_nocase ON topics (name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS item_topics (
    item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, topic_id)
);

CREATE TABLE IF NOT EXISTS claims (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    text     TEXT NOT NULL,
    position INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,                              -- 'extract' | 'enrich'
    status     TEXT NOT NULL DEFAULT 'pending',            -- pending|running|done|failed
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);

CREATE TABLE IF NOT EXISTS feeds (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    url            TEXT NOT NULL UNIQUE,                   -- resolved RSS/Atom URL
    site_url       TEXT,
    title          TEXT,
    last_polled_at TEXT,
    last_error     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Additive migrations applied after the base schema (safe on an existing DB).
MIGRATIONS = [
    # Phase 2a: associate streamed items with their feed.
    ("items", "feed_id", "ALTER TABLE items ADD COLUMN feed_id INTEGER REFERENCES feeds(id)"),
    # Sortable publish timestamp (ISO) so feed items list newest-first.
    ("items", "published_at", "ALTER TABLE items ADD COLUMN published_at TEXT"),
]


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r["name"] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def init_db(path: str | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            if not _column_exists(conn, table, column):
                conn.execute(ddl)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_feed ON items (feed_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_lane ON items (lane)")
        conn.commit()


@contextmanager
def cursor(path: str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
