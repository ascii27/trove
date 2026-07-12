"""Data operations over the SQLite schema: items, jobs, and their transitions."""
from __future__ import annotations

import sqlite3

from . import topics as topics_mod
from .enrich import EnrichResult
from .extract import Extracted

MAX_ATTEMPTS = 3

# Columns returned in list views (no heavy content).
_LIST_COLS = (
    "id, url_canonical, lane, title, author, source, publish_date, word_count, "
    "reading_minutes, original_url, date_saved, read_state, extraction_status, "
    "enrichment_status, summary, category, source_type, error_message"
)


# ---------------------------------------------------------------- capture ----
def get_item_by_url(conn: sqlite3.Connection, url_canonical: str) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT {_LIST_COLS} FROM items WHERE url_canonical = ?", (url_canonical,)
    ).fetchone()


def create_item(conn: sqlite3.Connection, url_canonical: str, original_url: str) -> int:
    """Insert a pending item and enqueue its extract job. Caller dedupes first."""
    cur = conn.execute(
        "INSERT INTO items (url_canonical, original_url) VALUES (?, ?)",
        (url_canonical, original_url),
    )
    item_id = cur.lastrowid
    enqueue_job(conn, item_id, "extract")
    return item_id


# ------------------------------------------------------------------ reads ----
def _item_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def get_item(conn: sqlite3.Connection, item_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {_LIST_COLS}, content_text FROM items WHERE id = ?", (item_id,)
    ).fetchone()
    if row is None:
        return None
    item = _item_dict(row)
    item["topics"] = [
        r["name"]
        for r in conn.execute(
            "SELECT t.name FROM topics t JOIN item_topics it ON it.topic_id = t.id "
            "WHERE it.item_id = ? ORDER BY t.name",
            (item_id,),
        )
    ]
    item["claims"] = [
        r["text"]
        for r in conn.execute(
            "SELECT text FROM claims WHERE item_id = ? ORDER BY position", (item_id,)
        )
    ]
    return item


def list_items(conn: sqlite3.Connection, view: str = "all") -> list[dict]:
    where = "WHERE lane = 'saved'"
    if view == "unread":
        where += " AND read_state = 'unread'"
    rows = conn.execute(
        f"SELECT {_LIST_COLS} FROM items {where} ORDER BY date_saved DESC, id DESC"
    ).fetchall()
    return [_item_dict(r) for r in rows]


def unread_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM items WHERE lane = 'saved' AND read_state = 'unread'"
    ).fetchone()["c"]


# ------------------------------------------------------------ read state ----
def set_read_state(conn: sqlite3.Connection, item_id: int, state: str) -> bool:
    cur = conn.execute("UPDATE items SET read_state = ? WHERE id = ?", (state, item_id))
    return cur.rowcount > 0


# ------------------------------------------------------------------ jobs ----
def enqueue_job(conn: sqlite3.Connection, item_id: int, kind: str) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (item_id, kind) VALUES (?, ?)", (item_id, kind)
    )
    return cur.lastrowid


def claim_next_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Atomically claim the oldest pending job, marking it running + bumping attempts."""
    row = conn.execute(
        "SELECT * FROM jobs WHERE status = 'pending' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    cur = conn.execute(
        "UPDATE jobs SET status = 'running', attempts = attempts + 1, "
        "updated_at = datetime('now') WHERE id = ? AND status = 'pending'",
        (row["id"],),
    )
    if cur.rowcount == 0:
        return None
    # reflect the incremented attempt/status
    if row["kind"] == "extract":
        conn.execute("UPDATE items SET extraction_status = 'extracting' WHERE id = ?", (row["item_id"],))
    elif row["kind"] == "enrich":
        conn.execute("UPDATE items SET enrichment_status = 'enriching' WHERE id = ?", (row["item_id"],))
    conn.commit()
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()


def complete_job(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'done', last_error = NULL, updated_at = datetime('now') WHERE id = ?",
        (job_id,),
    )


def fail_job(conn: sqlite3.Connection, job: sqlite3.Row, error: str) -> None:
    """Requeue for retry while under the attempt cap, else mark the job failed."""
    if job["attempts"] < MAX_ATTEMPTS:
        conn.execute(
            "UPDATE jobs SET status = 'pending', last_error = ?, updated_at = datetime('now') WHERE id = ?",
            (error, job["id"]),
        )
    else:
        conn.execute(
            "UPDATE jobs SET status = 'failed', last_error = ?, updated_at = datetime('now') WHERE id = ?",
            (error, job["id"]),
        )
        # surface a terminal state on the item
        if job["kind"] == "extract":
            conn.execute(
                "UPDATE items SET extraction_status = 'failed', error_message = ? WHERE id = ?",
                (error, job["item_id"]),
            )
        elif job["kind"] == "enrich":
            conn.execute(
                "UPDATE items SET enrichment_status = 'failed' WHERE id = ?", (job["item_id"],)
            )


def retry_extract(conn: sqlite3.Connection, item_id: int) -> bool:
    """Reset a failed extraction and enqueue a fresh extract job."""
    row = conn.execute("SELECT extraction_status FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE items SET extraction_status = 'pending', error_message = NULL WHERE id = ?",
        (item_id,),
    )
    enqueue_job(conn, item_id, "extract")
    return True


# ------------------------------------------------------- apply results ----
def apply_extraction(conn: sqlite3.Connection, item_id: int, result: Extracted) -> None:
    conn.execute(
        "UPDATE items SET title = ?, author = ?, source = ?, publish_date = ?, "
        "content_text = ?, word_count = ?, reading_minutes = ?, "
        "extraction_status = ?, error_message = ? WHERE id = ?",
        (
            result.title,
            result.author,
            result.source,
            result.publish_date,
            result.content_text,
            result.word_count,
            result.reading_minutes,
            result.status,
            result.error,
            item_id,
        ),
    )
    if result.status in ("extracted", "partial"):
        enqueue_job(conn, item_id, "enrich")


def apply_enrichment(conn: sqlite3.Connection, item_id: int, result: EnrichResult) -> None:
    conn.execute(
        "UPDATE items SET summary = ?, category = ?, source_type = ?, enrichment_status = 'done' WHERE id = ?",
        (result.summary, result.category, result.source_type, item_id),
    )
    topics_mod.set_item_topics(conn, item_id, result.topics)
    conn.execute("DELETE FROM claims WHERE item_id = ?", (item_id,))
    for pos, claim in enumerate(result.claims):
        conn.execute(
            "INSERT INTO claims (item_id, text, position) VALUES (?, ?, ?)",
            (item_id, claim, pos),
        )
