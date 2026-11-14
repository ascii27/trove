"""Data operations for the X lane: followed accounts and their posts.

Posts are ordinary `items` rows with lane='x', so the existing tag
(`/api/items/{id}/tags`) and highlight endpoints work on them unchanged. A
self-thread is one item keyed by its conversation id (`post_id`); later parts
that arrive on a subsequent poll are appended, which keeps earlier highlight
offsets valid. Posts are never per-item enriched (`enrichment_status='skipped'`);
they get a batched `theme` instead (xthemes.py).
"""
from __future__ import annotations

import sqlite3

from . import store
from .urls import canonicalize
from .xsource import XProfile, XThread, post_url

_ACCOUNT_COLS = "id, handle, user_id, name, avatar_url, last_seen_id, last_polled_at, last_error, created_at"
_POST_COLS = (
    "i.id, i.lane, i.x_account_id, i.post_id, i.thread_len, i.theme, i.title, i.author, i.source, "
    "i.original_url, i.published_at, i.date_saved, i.read_state, i.content_text, i.word_count"
)
_TITLE_CHARS = 90


# ------------------------------------------------------------- accounts ----
def get_account(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {_ACCOUNT_COLS} FROM x_accounts WHERE id = ?", (account_id,)).fetchone()


def get_account_by_handle(conn: sqlite3.Connection, handle: str) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT {_ACCOUNT_COLS} FROM x_accounts WHERE handle = ? COLLATE NOCASE", (handle,)
    ).fetchone()


def add_account(conn: sqlite3.Connection, profile: XProfile) -> int:
    existing = get_account_by_handle(conn, profile.handle)
    if existing is not None:
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO x_accounts (handle, user_id, name, avatar_url) VALUES (?, ?, ?, ?)",
        (profile.handle, profile.user_id, profile.name, profile.avatar_url),
    )
    return cur.lastrowid


def list_accounts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        f"""SELECT {_ACCOUNT_COLS},
               (SELECT COUNT(*) FROM items i WHERE i.x_account_id = x_accounts.id
                  AND i.lane = 'x' AND i.read_state = 'unread') AS unread_count
            FROM x_accounts ORDER BY COALESCE(name, handle) COLLATE NOCASE, id"""
    ).fetchall()
    return [dict(r) for r in rows]


def account_dict(conn: sqlite3.Connection, account_id: int) -> dict | None:
    return next((a for a in list_accounts(conn) if a["id"] == account_id), None)


def _kept_clause() -> str:
    """Posts you've invested in (tagged or highlighted) — never dropped or aged out."""
    return (
        "(EXISTS (SELECT 1 FROM item_topics it WHERE it.item_id = items.id) "
        "OR EXISTS (SELECT 1 FROM highlights h WHERE h.item_id = items.id))"
    )


def delete_account(conn: sqlite3.Connection, account_id: int) -> bool:
    """Unfollow. Untouched posts go; tagged or highlighted posts stay (author kept on the item)."""
    if get_account(conn, account_id) is None:
        return False
    conn.execute(
        f"DELETE FROM items WHERE x_account_id = ? AND lane = 'x' AND NOT {_kept_clause()}",
        (account_id,),
    )
    conn.execute("UPDATE items SET x_account_id = NULL WHERE x_account_id = ?", (account_id,))
    conn.execute("DELETE FROM x_accounts WHERE id = ?", (account_id,))
    return True


def accounts_due(conn: sqlite3.Connection, interval_seconds: int) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT {_ACCOUNT_COLS} FROM x_accounts "
        "WHERE last_polled_at IS NULL OR last_polled_at <= datetime('now', ?)",
        (f"-{interval_seconds} seconds",),
    ).fetchall()


def mark_polled(conn: sqlite3.Connection, account_id: int, error: str | None = None) -> None:
    conn.execute(
        "UPDATE x_accounts SET last_polled_at = datetime('now'), last_error = ? WHERE id = ?",
        (error, account_id),
    )


def update_profile(conn: sqlite3.Connection, account_id: int, profile: XProfile) -> None:
    conn.execute(
        "UPDATE x_accounts SET user_id = COALESCE(?, user_id), name = COALESCE(?, name), "
        "avatar_url = COALESCE(?, avatar_url) WHERE id = ?",
        (profile.user_id, profile.name, profile.avatar_url, account_id),
    )


# ---------------------------------------------------------------- ingest ----
def _title(plain: str) -> str:
    first = next((ln.strip() for ln in plain.splitlines() if ln.strip()), "") or "Post"
    return first if len(first) <= _TITLE_CHARS else first[: _TITLE_CHARS - 1].rstrip() + "…"


def ingest_threads(conn: sqlite3.Connection, account: sqlite3.Row, threads: list[XThread]) -> dict:
    """Store new threads; append later parts to a thread already stored."""
    created = appended = 0
    newest = account["last_seen_id"]
    for th in threads:
        for p in th.posts:
            if p.id.isdigit() and (newest is None or not newest.isdigit() or int(p.id) > int(newest)):
                newest = p.id
        existing = conn.execute(
            "SELECT id, content_text, thread_len, word_count FROM items "
            "WHERE x_account_id = ? AND post_id = ?",
            (account["id"], th.root_id),
        ).fetchone()
        if existing is not None:
            # Polls use since_id, so these are genuinely new parts of the thread.
            content = (existing["content_text"] or "") + "\n\n" + th.markdown
            conn.execute(
                "UPDATE items SET content_text = ?, thread_len = ?, word_count = ?, "
                "read_state = CASE WHEN read_state = 'archived' THEN read_state ELSE 'unread' END "
                "WHERE id = ?",
                (
                    content,
                    (existing["thread_len"] or 1) + len(th.posts),
                    (existing["word_count"] or 0) + len(th.plain.split()),
                    existing["id"],
                ),
            )
            appended += 1
            continue
        url = post_url(account["handle"], th.root_id)
        canon = canonicalize(url)
        if conn.execute("SELECT 1 FROM items WHERE url_canonical = ?", (canon,)).fetchone():
            continue
        conn.execute(
            "INSERT INTO items (url_canonical, original_url, lane, x_account_id, post_id, thread_len, "
            "title, author, source, published_at, content_text, word_count, "
            "extraction_status, enrichment_status) "
            "VALUES (?, ?, 'x', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted', 'skipped')",
            (
                canon,
                url,
                account["id"],
                th.root_id,
                len(th.posts),
                _title(th.plain),
                account["name"] or f"@{account['handle']}",
                f"@{account['handle']}",
                th.created_at,
                th.markdown,
                len(th.plain.split()),
            ),
        )
        created += 1
    if newest != account["last_seen_id"]:
        conn.execute("UPDATE x_accounts SET last_seen_id = ? WHERE id = ?", (newest, account["id"]))
    return {"created": created, "appended": appended}


# ----------------------------------------------------------------- reads ----
def list_posts(
    conn: sqlite3.Connection,
    account_id: int | None = None,
    unread_only: bool = False,
    limit: int = 400,
) -> list[dict]:
    """Posts newest-first, each with its account, tags, and highlights."""
    where = ["i.lane = 'x'", "i.read_state != 'archived'"]
    params: list = []
    if account_id is not None:
        where.append("i.x_account_id = ?")
        params.append(account_id)
    if unread_only:
        where.append("i.read_state = 'unread'")
    rows = conn.execute(
        f"SELECT {_POST_COLS}, a.handle AS handle, a.avatar_url AS avatar_url "
        "FROM items i LEFT JOIN x_accounts a ON a.id = i.x_account_id "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY (i.published_at IS NULL), i.published_at DESC, i.id DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    ids = [r["id"] for r in rows]
    topics: dict[int, list[str]] = {}
    hls: dict[int, list[dict]] = {}
    if ids:
        marks = ",".join("?" * len(ids))
        for r in conn.execute(
            "SELECT it.item_id AS iid, t.name AS name FROM item_topics it "
            f"JOIN topics t ON t.id = it.topic_id WHERE it.item_id IN ({marks}) ORDER BY t.name",
            ids,
        ):
            topics.setdefault(r["iid"], []).append(r["name"])
        for r in conn.execute(
            "SELECT id, item_id, quote, start_offset, end_offset, created_at FROM highlights "
            f"WHERE item_id IN ({marks}) ORDER BY start_offset, id",
            ids,
        ):
            d = dict(r)
            hls.setdefault(d.pop("item_id"), []).append(d)
    out = []
    for r in rows:
        d = dict(r)
        if d["handle"] is None and d["source"]:
            d["handle"] = d["source"].lstrip("@")  # unfollowed author, kept post
        d["topics"] = topics.get(d["id"], [])
        d["highlights"] = hls.get(d["id"], [])
        out.append(d)
    return out


def get_post(conn: sqlite3.Connection, item_id: int) -> dict | None:
    row = conn.execute("SELECT x_account_id FROM items WHERE id = ? AND lane = 'x'", (item_id,)).fetchone()
    if row is None:
        return None
    # Small and indexed; reuse the list shaping for one post.
    rows = conn.execute(
        f"SELECT {_POST_COLS}, a.handle AS handle, a.avatar_url AS avatar_url "
        "FROM items i LEFT JOIN x_accounts a ON a.id = i.x_account_id WHERE i.id = ?",
        (item_id,),
    ).fetchone()
    d = dict(rows)
    if d["handle"] is None and d["source"]:
        d["handle"] = d["source"].lstrip("@")
    d["topics"] = store._item_topics(conn, item_id)
    d["highlights"] = store.highlights_for_item(conn, item_id)
    return d


def mark_posts(conn: sqlite3.Connection, ids: list[int], state: str) -> int:
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    cur = conn.execute(
        f"UPDATE items SET read_state = ? WHERE lane = 'x' AND id IN ({marks})", (state, *ids)
    )
    return cur.rowcount


def set_theme(conn: sqlite3.Connection, item_id: int, theme: str | None) -> bool:
    cur = conn.execute("UPDATE items SET theme = ? WHERE id = ? AND lane = 'x'", (theme, item_id))
    return cur.rowcount > 0


def unread_total(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM items WHERE lane = 'x' AND read_state = 'unread'"
    ).fetchone()["c"]


# ---------------------------------------------------------------- themes ----
def existing_themes(conn: sqlite3.Connection, limit: int = 60) -> list[str]:
    """Most-used themes first, so the classifier reuses the established ones."""
    return [
        r["theme"]
        for r in conn.execute(
            "SELECT theme, COUNT(*) AS n FROM items WHERE lane = 'x' AND theme IS NOT NULL "
            "GROUP BY theme ORDER BY n DESC, theme LIMIT ?",
            (limit,),
        )
    ]


def unthemed_posts(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, author, content_text, title FROM items "
        "WHERE lane = 'x' AND theme IS NULL AND read_state != 'archived' "
        "ORDER BY (published_at IS NULL), published_at DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def apply_themes(conn: sqlite3.Connection, themes: dict[int, str]) -> None:
    for item_id, theme in themes.items():
        conn.execute(
            "UPDATE items SET theme = ? WHERE id = ? AND lane = 'x' AND theme IS NULL", (theme, item_id)
        )


# ----------------------------------------------------------------- aging ----
def age_posts(conn: sqlite3.Connection, days: int) -> int:
    """Archive unread posts older than `days` — unless you tagged or highlighted them."""
    cur = conn.execute(
        "UPDATE items SET read_state = 'archived' "
        "WHERE lane = 'x' AND read_state = 'unread' "
        f"AND datetime(COALESCE(published_at, date_saved)) <= datetime('now', ?) AND NOT {_kept_clause()}",
        (f"-{days} days",),
    )
    return cur.rowcount
