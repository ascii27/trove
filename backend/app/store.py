"""Data operations over the SQLite schema: items, jobs, and their transitions."""
from __future__ import annotations

import sqlite3

from . import lens as lens_mod
from . import topics as topics_mod
from .enrich import EnrichResult
from .extract import BookmarkMeta, Extracted
from .feedfetch import Entry
from .urls import canonicalize

MAX_ATTEMPTS = 3
# Newest N new items per poll get the full fetch/extract/enrich; the rest are
# 'deferred' and load on first open (bounds enrichment token spend).
EAGER_PER_POLL = 10

# Columns returned in list views (no heavy content).
_LIST_COLS = (
    "id, url_canonical, lane, feed_id, title, author, source, publish_date, word_count, "
    "reading_minutes, original_url, date_saved, read_state, extraction_status, "
    "enrichment_status, summary, category, source_type, error_message"
)


# ---------------------------------------------------------------- capture ----
def get_item_by_url(conn: sqlite3.Connection, url_canonical: str) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT {_LIST_COLS} FROM items WHERE url_canonical = ?", (url_canonical,)
    ).fetchone()


def create_item(
    conn: sqlite3.Connection,
    url_canonical: str,
    original_url: str,
    lane: str = "saved",
    job_kind: str = "extract",
) -> int:
    """Insert a pending item and enqueue its processing job. Caller dedupes first.

    Bookmarks pass lane='bookmark', job_kind='bookmark' (light metadata + tags,
    no stored content, no reader)."""
    cur = conn.execute(
        "INSERT INTO items (url_canonical, original_url, lane) VALUES (?, ?, ?)",
        (url_canonical, original_url, lane),
    )
    item_id = cur.lastrowid
    enqueue_job(conn, item_id, job_kind)
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
    item["collection_ids"] = [
        r["collection_id"]
        for r in conn.execute(
            "SELECT collection_id FROM item_collections WHERE item_id = ?", (item_id,)
        )
    ]
    item["highlights"] = highlights_for_item(conn, item_id)
    return item


def list_items(conn: sqlite3.Connection, view: str = "all", feed_id: int | None = None) -> list[dict]:
    if view == "feed":
        # Feed items list newest-first by the entry's own publish time (NULLs last).
        where, params = "WHERE lane = 'feed' AND feed_id = ? AND read_state != 'archived'", (feed_id,)
        order = "ORDER BY (published_at IS NULL), published_at DESC, id DESC"
    elif view == "unread":
        where, params = "WHERE lane = 'saved' AND read_state = 'unread'", ()
        order = "ORDER BY date_saved DESC, id DESC"
    else:  # 'all' — Saved lane only (lanes stay strictly separate)
        where, params = "WHERE lane = 'saved'", ()
        order = "ORDER BY date_saved DESC, id DESC"
    rows = conn.execute(f"SELECT {_LIST_COLS} FROM items {where} {order}", params).fetchall()
    return [_item_dict(r) for r in rows]


def lens_search(conn: sqlite3.Connection, query: str) -> dict:
    """Rank items across both lanes for an interest query. Each result carries a
    `matched_topics` list; results are sorted by score, then recency."""
    terms = lens_mod.expand(query)
    if not terms:
        return {"items": [], "saved_count": 0, "feed_count": 0}

    rows = conn.execute(
        f"SELECT {_LIST_COLS} FROM items WHERE read_state != 'archived' AND lane IN ('saved', 'feed')"
    ).fetchall()
    topics_map: dict[int, list[str]] = {}
    for r in conn.execute(
        "SELECT it.item_id AS iid, t.name AS name FROM item_topics it JOIN topics t ON t.id = it.topic_id"
    ):
        topics_map.setdefault(r["iid"], []).append(r["name"])
    claims_map: dict[int, list[str]] = {}
    for r in conn.execute("SELECT item_id, text FROM claims ORDER BY position"):
        claims_map.setdefault(r["item_id"], []).append(r["text"])

    scored: list[tuple[int, dict]] = []
    for r in rows:
        its = topics_map.get(r["id"], [])
        score, matched = lens_mod.score_item(
            title=r["title"], summary=r["summary"], category=r["category"],
            claims=claims_map.get(r["id"], []), item_topics=its, terms=terms,
        )
        if score > 0:
            d = _item_dict(r)
            d["matched_topics"] = matched
            scored.append((score, d))
    scored.sort(key=lambda pair: (pair[0], pair[1]["date_saved"]), reverse=True)
    items = [d for _, d in scored]
    saved = sum(1 for d in items if d["lane"] == "saved")
    return {"items": items, "saved_count": saved, "feed_count": len(items) - saved}


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
    if row["kind"] in ("extract", "bookmark"):
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


def delete_item(conn: sqlite3.Connection, item_id: int) -> bool:
    """Delete an item; FK ON DELETE CASCADE clears its topics/claims/jobs."""
    cur = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    return cur.rowcount > 0


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


# ------------------------------------------------------------------ feeds ----
_FEED_COLS = "id, url, site_url, title, last_polled_at, last_error, created_at"


def add_feed(conn: sqlite3.Connection, feed_url: str, site_url: str | None, title: str | None) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO feeds (url, site_url, title) VALUES (?, ?, ?)",
        (feed_url, site_url, title),
    )
    return conn.execute("SELECT id FROM feeds WHERE url = ?", (feed_url,)).fetchone()["id"]


def get_feed_by_url(conn: sqlite3.Connection, feed_url: str) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {_FEED_COLS} FROM feeds WHERE url = ?", (feed_url,)).fetchone()


def get_feed(conn: sqlite3.Connection, feed_id: int) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {_FEED_COLS} FROM feeds WHERE id = ?", (feed_id,)).fetchone()


def list_feeds(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        f"""SELECT {_FEED_COLS},
               (SELECT COUNT(*) FROM items i
                WHERE i.feed_id = feeds.id AND i.lane = 'feed'
                  AND i.read_state = 'unread') AS unread_count
            FROM feeds ORDER BY title COLLATE NOCASE, id"""
    ).fetchall()
    return [dict(r) for r in rows]


def delete_feed(conn: sqlite3.Connection, feed_id: int) -> bool:
    if conn.execute("SELECT 1 FROM feeds WHERE id = ?", (feed_id,)).fetchone() is None:
        return False
    # Drop the feed's streamed items; anything promoted to Saved survives.
    conn.execute("DELETE FROM items WHERE feed_id = ? AND lane = 'feed'", (feed_id,))
    # Release the FK on surviving (saved) items before removing the feed.
    conn.execute("UPDATE items SET feed_id = NULL WHERE feed_id = ?", (feed_id,))
    conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    return True


def mark_feed_polled(conn: sqlite3.Connection, feed_id: int, error: str | None = None) -> None:
    conn.execute(
        "UPDATE feeds SET last_polled_at = datetime('now'), last_error = ? WHERE id = ?",
        (error, feed_id),
    )


def feeds_due(conn: sqlite3.Connection, interval_seconds: int) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT {_FEED_COLS} FROM feeds "
        "WHERE last_polled_at IS NULL OR last_polled_at <= datetime('now', ?)",
        (f"-{interval_seconds} seconds",),
    ).fetchall()


def ingest_entries(
    conn: sqlite3.Connection,
    feed_id: int,
    feed_title: str | None,
    entries: list[Entry],
    *,
    eager_limit: int = EAGER_PER_POLL,
) -> dict:
    """Create items for new entries. Newest `eager_limit` get the full pipeline;
    the rest are 'deferred'. Dedupe on canonical URL across the whole library."""
    eager = deferred = 0
    for entry in entries:
        canon = canonicalize(entry.link)
        if conn.execute("SELECT 1 FROM items WHERE url_canonical = ?", (canon,)).fetchone():
            continue  # already saved or streamed (possibly from another feed)
        make_eager = eager < eager_limit
        status = "pending" if make_eager else "deferred"
        cur = conn.execute(
            "INSERT INTO items (url_canonical, original_url, lane, feed_id, title, source, "
            "publish_date, published_at, summary, extraction_status) "
            "VALUES (?, ?, 'feed', ?, ?, ?, ?, ?, ?, ?)",
            (canon, entry.link, feed_id, entry.title, feed_title, entry.published, entry.published_at, entry.summary, status),
        )
        if make_eager:
            enqueue_job(conn, cur.lastrowid, "extract")
            eager += 1
        else:
            deferred += 1
    return {"eager": eager, "deferred": deferred}


def age_feed_items(conn: sqlite3.Connection, days: int) -> int:
    cur = conn.execute(
        "UPDATE items SET read_state = 'archived' "
        "WHERE lane = 'feed' AND read_state = 'unread' AND date_saved <= datetime('now', ?)",
        (f"-{days} days",),
    )
    return cur.rowcount


def promote_to_saved(conn: sqlite3.Connection, item_id: int) -> bool:
    row = conn.execute("SELECT lane, extraction_status FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        return False
    conn.execute("UPDATE items SET lane = 'saved', read_state = CASE WHEN read_state='archived' THEN 'unread' ELSE read_state END WHERE id = ?", (item_id,))
    if row["extraction_status"] == "deferred":
        _load_deferred(conn, item_id)
    return True


def load_if_deferred(conn: sqlite3.Connection, item_id: int) -> None:
    row = conn.execute("SELECT extraction_status FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is not None and row["extraction_status"] == "deferred":
        _load_deferred(conn, item_id)


def _load_deferred(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("UPDATE items SET extraction_status = 'pending' WHERE id = ?", (item_id,))
    enqueue_job(conn, item_id, "extract")


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


# ------------------------------------------------------------ collections ----
def create_collection(
    conn: sqlite3.Connection, name: str, query: str | None = None, item_ids: list[int] | None = None
) -> int:
    cur = conn.execute("INSERT INTO collections (name, query) VALUES (?, ?)", (name, query))
    cid = cur.lastrowid
    for item_id in item_ids or []:
        add_item_to_collection(conn, cid, item_id)
    return cid


def get_collection(conn: sqlite3.Connection, cid: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, name, query, created_at FROM collections WHERE id = ?", (cid,)
    ).fetchone()


def list_collections(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, query, created_at, "
        "(SELECT COUNT(*) FROM item_collections ic WHERE ic.collection_id = collections.id) AS item_count "
        "FROM collections ORDER BY created_at DESC, id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_collection(conn: sqlite3.Connection, cid: int) -> bool:
    cur = conn.execute("DELETE FROM collections WHERE id = ?", (cid,))
    return cur.rowcount > 0


def add_item_to_collection(conn: sqlite3.Connection, cid: int, item_id: int) -> bool:
    if conn.execute("SELECT 1 FROM collections WHERE id = ?", (cid,)).fetchone() is None:
        return False
    if conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is None:
        return False
    conn.execute(
        "INSERT OR IGNORE INTO item_collections (collection_id, item_id) VALUES (?, ?)", (cid, item_id)
    )
    return True


def remove_item_from_collection(conn: sqlite3.Connection, cid: int, item_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM item_collections WHERE collection_id = ? AND item_id = ?", (cid, item_id)
    )
    return cur.rowcount > 0


def collection_items(conn: sqlite3.Connection, cid: int) -> list[dict]:
    """Member items (cross-lane), most-recently-added first."""
    rows = conn.execute(
        f"SELECT {_LIST_COLS} FROM items i "
        "JOIN item_collections ic ON ic.item_id = i.id "
        "WHERE ic.collection_id = ? ORDER BY ic.added_at DESC, i.id DESC",
        (cid,),
    ).fetchall()
    return [_item_dict(r) for r in rows]


# ------------------------------------------------------------- highlights ----
_HL_COLS = "id, quote, start_offset, end_offset, created_at"


def create_highlight(
    conn: sqlite3.Connection, item_id: int, quote: str, start: int, end: int
) -> dict | None:
    """Save a highlight anchored by char offsets into the item's rendered text.

    Returns the new highlight dict, or None if the item does not exist.
    """
    if conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is None:
        return None
    cur = conn.execute(
        "INSERT INTO highlights (item_id, quote, start_offset, end_offset) VALUES (?, ?, ?, ?)",
        (item_id, quote, start, end),
    )
    row = conn.execute(
        f"SELECT {_HL_COLS} FROM highlights WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return dict(row)


def highlights_for_item(conn: sqlite3.Connection, item_id: int) -> list[dict]:
    """An item's highlights, in document order (by start offset)."""
    rows = conn.execute(
        f"SELECT {_HL_COLS} FROM highlights WHERE item_id = ? ORDER BY start_offset, id",
        (item_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_highlights(conn: sqlite3.Connection) -> list[dict]:
    """Global archive: every highlight with its source item, newest first."""
    rows = conn.execute(
        "SELECT h.id, h.quote, h.start_offset, h.end_offset, h.created_at, "
        "h.item_id, i.title, i.original_url "
        "FROM highlights h JOIN items i ON i.id = h.item_id "
        "ORDER BY h.created_at DESC, h.id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_highlight(conn: sqlite3.Connection, hid: int) -> bool:
    cur = conn.execute("DELETE FROM highlights WHERE id = ?", (hid,))
    return cur.rowcount > 0


# -------------------------------------------------------------- bookmarks ----
_BOOKMARK_COLS = (
    "id, lane, title, source, original_url, date_saved, publish_date, favicon_url, "
    "summary, extraction_status, enrichment_status"
)


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).netloc or url


def apply_bookmark(
    conn: sqlite3.Connection, item_id: int, meta: BookmarkMeta, enriched: EnrichResult | None
) -> None:
    """Store a bookmark's light metadata + optional AI summary/tags. The page body
    is never persisted. A bookmark stays usable even if the fetch or AI failed."""
    url = conn.execute("SELECT original_url FROM items WHERE id = ?", (item_id,)).fetchone()["original_url"]
    title = meta.title or _host(url)
    summary = enriched.summary if enriched else meta.description
    conn.execute(
        "UPDATE items SET title = ?, source = ?, publish_date = ?, favicon_url = ?, summary = ?, "
        "extraction_status = ?, enrichment_status = ? WHERE id = ?",
        (
            title,
            meta.source,
            meta.publish_date,
            meta.favicon_url,
            summary,
            meta.status,  # 'extracted' | 'failed'
            "done" if enriched else "failed",
            item_id,
        ),
    )
    if enriched:
        topics_mod.set_item_topics(conn, item_id, enriched.topics)


def _item_topics(conn: sqlite3.Connection, item_id: int) -> list[str]:
    return [
        r["name"]
        for r in conn.execute(
            "SELECT t.name FROM topics t JOIN item_topics it ON it.topic_id = t.id "
            "WHERE it.item_id = ? ORDER BY t.name",
            (item_id,),
        )
    ]


def list_bookmarks(conn: sqlite3.Connection) -> list[dict]:
    """All bookmarks, newest first, each carrying its tags (topics)."""
    rows = conn.execute(
        f"SELECT {_BOOKMARK_COLS} FROM items WHERE lane = 'bookmark' ORDER BY date_saved DESC, id DESC"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["topics"] = _item_topics(conn, r["id"])
        out.append(d)
    return out


def add_item_tag(conn: sqlite3.Connection, item_id: int, raw: str) -> list[str] | None:
    """Attach a normalized tag to an item; return its updated tag list (None if item missing)."""
    if conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is None:
        return None
    name = topics_mod.canonicalize(raw)
    if name:
        topic_id = topics_mod.upsert_topic(conn, name)
        conn.execute(
            "INSERT OR IGNORE INTO item_topics (item_id, topic_id) VALUES (?, ?)", (item_id, topic_id)
        )
    return _item_topics(conn, item_id)


def remove_item_tag(conn: sqlite3.Connection, item_id: int, raw: str) -> list[str] | None:
    """Detach a tag (matched by canonical name) from an item; return its updated tag list."""
    if conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is None:
        return None
    name = topics_mod.canonicalize(raw)
    if name:
        conn.execute(
            "DELETE FROM item_topics WHERE item_id = ? AND topic_id IN "
            "(SELECT id FROM topics WHERE name = ? COLLATE NOCASE)",
            (item_id, name),
        )
    return _item_topics(conn, item_id)
