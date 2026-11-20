"""Data operations for the Newspaper: candidates, editions, settings.

An edition's layout is stored as self-contained JSON (headlines, summaries,
source, link, image), so back issues still read correctly after the
underlying items age out or are deleted. `edition_items` records every item
ever printed; candidates exclude them, so no story runs twice.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

SCHEDULES = ("off", "daily", "weekdays", "weekends")
FIRST_WINDOW_DAYS = 3  # the very first edition looks back this far
MAX_WINDOW_DAYS = 7  # "since the last edition", but never further back than this
SHELF_DAYS = 30  # unread saved items stay eligible this long

_EDITION_COLS = (
    "id, number, status, trigger, error, window_start, story_count, input_tokens, output_tokens, "
    "created_at, finished_at"
)


@dataclass
class Candidate:
    id: int
    lane: str  # 'feed' | 'x' | 'saved'
    title: str | None
    source: str | None
    author: str | None
    text: str  # what the editor reads: feed summary, article opening or post text
    url: str
    image: str | None
    published_at: str | None
    feed_id: int | None
    topics: list[str]


# ------------------------------------------------------------ candidates ----
def window_start(conn: sqlite3.Connection) -> str:
    """UTC timestamp: since the last printed edition, capped at MAX_WINDOW_DAYS back."""
    last = conn.execute("SELECT MAX(created_at) AS t FROM editions WHERE number IS NOT NULL").fetchone()["t"]
    if last is None:
        return conn.execute("SELECT datetime('now', ?) AS w", (f"-{FIRST_WINDOW_DAYS} days",)).fetchone()["w"]
    return conn.execute(
        "SELECT MAX(datetime(?), datetime('now', ?)) AS w", (last, f"-{MAX_WINDOW_DAYS} days")
    ).fetchone()["w"]


def _plain(md: str | None, limit: int) -> str:
    """Rough Markdown → text for the editor's eyes (links, images, emphasis stripped)."""
    import re

    if not md:
        return ""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[#>*_`|]+", " ", t)
    t = t.replace("\\", "")
    return " ".join(t.split())[:limit]


def candidates(
    conn: sqlite3.Connection,
    since: str,
    *,
    per_feed: int = 8,
    max_feed: int = 120,
    max_x: int = 40,
    max_shelf: int = 15,
) -> list[Candidate]:
    """Unread, never-printed items: feed stories and X posts since `since`, plus recent unread saves."""
    rows = conn.execute(
        """
        SELECT i.id, i.lane, i.title, i.source, i.author, i.summary, i.content_text, i.original_url,
               i.image_url, i.published_at, i.date_saved, i.feed_id
        FROM items i
        WHERE i.read_state = 'unread'
          AND NOT EXISTS (SELECT 1 FROM edition_items e WHERE e.item_id = i.id)
          AND (
                (i.lane IN ('feed', 'x') AND datetime(COALESCE(i.published_at, i.date_saved)) >= datetime(?))
             OR (i.lane = 'saved' AND i.extraction_status IN ('extracted', 'partial')
                 AND datetime(i.date_saved) >= datetime('now', ?))
          )
        ORDER BY datetime(COALESCE(i.published_at, i.date_saved)) DESC, i.id DESC
        """,
        (since, f"-{SHELF_DAYS} days"),
    ).fetchall()
    topics: dict[int, list[str]] = {}
    for r in conn.execute(
        "SELECT it.item_id, t.name FROM item_topics it JOIN topics t ON t.id = it.topic_id"
    ):
        topics.setdefault(r["item_id"], []).append(r["name"])

    out: list[Candidate] = []
    per: dict[int, int] = {}
    counts = {"feed": 0, "x": 0, "saved": 0}
    caps = {"feed": max_feed, "x": max_x, "saved": max_shelf}
    for r in rows:
        lane = r["lane"]
        if counts[lane] >= caps[lane]:
            continue
        if lane == "feed":
            fid = r["feed_id"] or 0
            if per.get(fid, 0) >= per_feed:
                continue  # one prolific feed shouldn't crowd out the rest
            per[fid] = per.get(fid, 0) + 1
        if lane == "x":
            text = _plain(r["content_text"], 400)
        else:
            text = _plain(r["summary"], 500) or _plain(r["content_text"], 500)
        counts[lane] += 1
        out.append(
            Candidate(
                id=r["id"],
                lane=lane,
                title=r["title"],
                source=r["source"],
                author=r["author"],
                text=text,
                url=r["original_url"],
                image=r["image_url"],
                published_at=r["published_at"] or r["date_saved"],
                feed_id=r["feed_id"],
                topics=topics.get(r["id"], [])[:4],
            )
        )
    return out


def set_item_image(conn: sqlite3.Connection, item_id: int, url: str) -> None:
    conn.execute("UPDATE items SET image_url = COALESCE(image_url, ?) WHERE id = ?", (url, item_id))


# --------------------------------------------------------------- editions ----
def create_edition(conn: sqlite3.Connection, trigger: str, since: str) -> int:
    cur = conn.execute("INSERT INTO editions (trigger, window_start) VALUES (?, ?)", (trigger, since))
    return int(cur.lastrowid)


def running_edition(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(f"SELECT {_EDITION_COLS} FROM editions WHERE status = 'running' LIMIT 1").fetchone()
    return dict(row) if row else None


def get_edition(conn: sqlite3.Connection, eid: int) -> dict | None:
    row = conn.execute(f"SELECT {_EDITION_COLS}, layout FROM editions WHERE id = ?", (eid,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["layout"] = json.loads(d["layout"]) if d["layout"] else None
    return d


def latest_done(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT id FROM editions WHERE status = 'done' ORDER BY id DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def list_editions(conn: sqlite3.Connection, limit: int = 60) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            f"SELECT {_EDITION_COLS} FROM editions WHERE status != 'deleted' ORDER BY id DESC LIMIT ?", (limit,)
        )
    ]


def finish_edition(
    conn: sqlite3.Connection,
    eid: int,
    layout: dict,
    item_ids: list[int],
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    number = conn.execute("SELECT COALESCE(MAX(number), 0) + 1 AS n FROM editions").fetchone()["n"]
    conn.execute(
        "UPDATE editions SET status = 'done', number = ?, layout = ?, story_count = ?, input_tokens = ?, "
        "output_tokens = ?, finished_at = datetime('now') WHERE id = ?",
        (number, json.dumps(layout, ensure_ascii=False), len(item_ids), input_tokens, output_tokens, eid),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO edition_items (edition_id, item_id) VALUES (?, ?)", [(eid, i) for i in item_ids]
    )


def fail_edition(conn: sqlite3.Connection, eid: int, error: str) -> None:
    conn.execute(
        "UPDATE editions SET status = 'failed', error = ?, finished_at = datetime('now') WHERE id = ?",
        (error, eid),
    )


def fail_interrupted(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "UPDATE editions SET status = 'failed', error = 'Interrupted by a restart. Try again.', "
        "finished_at = datetime('now') WHERE status = 'running'"
    ).rowcount


def delete_edition(conn: sqlite3.Connection, eid: int) -> bool:
    """Remove a back issue. Its stories stay marked as printed, so they still won't repeat."""
    return conn.execute("UPDATE editions SET layout = NULL, status = 'deleted' WHERE id = ?", (eid,)).rowcount > 0


# --------------------------------------------------------------- settings ----
def get_settings(conn: sqlite3.Connection) -> dict:
    conn.execute("INSERT OR IGNORE INTO newspaper_settings (id) VALUES (1)")
    row = conn.execute("SELECT schedule, hour, tz, last_scheduled FROM newspaper_settings WHERE id = 1").fetchone()
    return dict(row)


def save_settings(conn: sqlite3.Connection, schedule: str, hour: int, tz: str) -> dict:
    get_settings(conn)
    conn.execute(
        "UPDATE newspaper_settings SET schedule = ?, hour = ?, tz = ? WHERE id = 1", (schedule, hour, tz)
    )
    return get_settings(conn)


def mark_scheduled(conn: sqlite3.Connection, local_date: str) -> None:
    conn.execute("UPDATE newspaper_settings SET last_scheduled = ? WHERE id = 1", (local_date,))
