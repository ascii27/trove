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
    lane              TEXT NOT NULL DEFAULT 'saved',      -- 'saved' | 'feed' | 'bookmark' | 'x'
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
    enrichment_status TEXT NOT NULL DEFAULT 'pending',    -- pending|enriching|done|failed|deferred|skipped
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

CREATE TABLE IF NOT EXISTS collections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,                             -- the research question
    query      TEXT,                                      -- the lens it was saved from (nullable)
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS item_collections (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    item_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    added_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (collection_id, item_id)
);

CREATE TABLE IF NOT EXISTS x_accounts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    handle         TEXT NOT NULL,                          -- without the leading @
    user_id        TEXT,                                   -- X user id (API mode)
    name           TEXT,
    avatar_url     TEXT,
    last_seen_id   TEXT,                                   -- newest post id ingested (since_id)
    last_polled_at TEXT,
    last_error     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_x_accounts_handle ON x_accounts (handle COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    context     TEXT,                                      -- optional "I'm interested in wine"
    kinds       TEXT NOT NULL DEFAULT 'all',               -- 'all' | 'blogs' | 'x'
    status      TEXT NOT NULL DEFAULT 'running',           -- running|done|failed
    error       TEXT,
    found       INTEGER NOT NULL DEFAULT 0,                -- new suggestions this run added
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS suggestions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER REFERENCES discovery_runs(id) ON DELETE SET NULL,
    kind        TEXT NOT NULL,                             -- 'blog' | 'x'
    key         TEXT NOT NULL,                             -- feed URL (blog) or lowercased handle (x)
    name        TEXT NOT NULL,
    url         TEXT,                                      -- site homepage / profile link
    feed_url    TEXT,                                      -- verified RSS/Atom URL (blogs)
    handle      TEXT,                                      -- without @ (x)
    description TEXT,
    reason      TEXT,                                      -- why it fits you
    topics      TEXT NOT NULL DEFAULT '[]',                -- JSON list
    status      TEXT NOT NULL DEFAULT 'new',               -- new|followed|dismissed
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    acted_at    TEXT
);
-- One row per source ever suggested, so dismissed ones never come back.
CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestions_key ON suggestions (kind, key);

CREATE TABLE IF NOT EXISTS highlights (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    quote        TEXT NOT NULL,                             -- the selected passage
    start_offset INTEGER NOT NULL,                          -- char offset into rendered .prose text
    end_offset   INTEGER NOT NULL,                          -- half-open end offset
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Additive migrations applied after the base schema (safe on an existing DB).
MIGRATIONS = [
    # Phase 2a: associate streamed items with their feed.
    ("items", "feed_id", "ALTER TABLE items ADD COLUMN feed_id INTEGER REFERENCES feeds(id)"),
    # Sortable publish timestamp (ISO) so feed items list newest-first.
    ("items", "published_at", "ALTER TABLE items ADD COLUMN published_at TEXT"),
    # Bookmarks lane: the site's favicon URL, shown on bookmark cards.
    ("items", "favicon_url", "ALTER TABLE items ADD COLUMN favicon_url TEXT"),
    # X lane: posts from followed accounts. A self-thread is stored as one item
    # keyed by its conversation (root post) id; theme is an AI-assigned group.
    ("items", "x_account_id", "ALTER TABLE items ADD COLUMN x_account_id INTEGER REFERENCES x_accounts(id)"),
    ("items", "post_id", "ALTER TABLE items ADD COLUMN post_id TEXT"),
    ("items", "thread_len", "ALTER TABLE items ADD COLUMN thread_len INTEGER"),
    ("items", "theme", "ALTER TABLE items ADD COLUMN theme TEXT"),
    # Discover: what each run did, so the history can say why it found nothing.
    ("discovery_runs", "proposed", "ALTER TABLE discovery_runs ADD COLUMN proposed INTEGER"),
    ("discovery_runs", "passed", "ALTER TABLE discovery_runs ADD COLUMN passed INTEGER"),
    ("discovery_runs", "input_tokens", "ALTER TABLE discovery_runs ADD COLUMN input_tokens INTEGER"),
    ("discovery_runs", "output_tokens", "ALTER TABLE discovery_runs ADD COLUMN output_tokens INTEGER"),
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_x_account ON items (x_account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_highlights_item ON highlights (item_id)")
        conn.commit()


@contextmanager
def cursor(path: str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
