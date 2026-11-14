"""Data operations for Discover: the interest profile, runs, and suggestions.

The profile is read straight from what's already in the library — topics you
keep (weighted toward saved, read, highlighted and collected items), the feeds
and X accounts you follow, X themes, and collection names. No new tracking.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

_RUN_COLS = "id, context, kinds, status, error, found, created_at, finished_at"
_SUGGESTION_COLS = (
    "id, run_id, kind, name, url, feed_url, handle, description, reason, topics, status, created_at"
)
KINDS = ("all", "blogs", "x")


# --------------------------------------------------------------- profile ----
@dataclass
class Profile:
    topics: list[str] = field(default_factory=list)
    feeds: list[dict] = field(default_factory=list)  # {title, site_url, url}
    x_accounts: list[dict] = field(default_factory=list)  # {handle, name}
    x_themes: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    recent_titles: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.topics or self.feeds or self.x_accounts or self.x_themes or self.collections)

    def summary(self) -> dict:
        return {
            "topics": self.topics[:12],
            "feed_count": len(self.feeds),
            "x_count": len(self.x_accounts),
            "collections": self.collections[:6],
        }


# A topic's weight sums, per item, a base of 1 plus signals that you cared about it.
_TOPIC_WEIGHT_SQL = """
SELECT t.name AS name,
       SUM(1
           + CASE WHEN i.lane = 'saved' THEN 2 ELSE 0 END
           + CASE WHEN i.read_state = 'read' THEN 1 ELSE 0 END
           + CASE WHEN EXISTS (SELECT 1 FROM highlights h WHERE h.item_id = i.id) THEN 2 ELSE 0 END
           + CASE WHEN EXISTS (SELECT 1 FROM item_collections c WHERE c.item_id = i.id) THEN 2 ELSE 0 END
       ) AS weight
FROM item_topics it
JOIN topics t ON t.id = it.topic_id
JOIN items i ON i.id = it.item_id
WHERE i.read_state != 'archived' OR i.lane = 'saved'
GROUP BY t.id
ORDER BY weight DESC, t.name
LIMIT ?
"""


def build_profile(conn: sqlite3.Connection, *, topic_limit: int = 30) -> Profile:
    topics = [r["name"] for r in conn.execute(_TOPIC_WEIGHT_SQL, (topic_limit,))]
    feeds = [
        {"title": r["title"], "site_url": r["site_url"], "url": r["url"]}
        for r in conn.execute("SELECT title, site_url, url FROM feeds ORDER BY id")
    ]
    x_accounts = [
        {"handle": r["handle"], "name": r["name"]}
        for r in conn.execute("SELECT handle, name FROM x_accounts ORDER BY id")
    ]
    x_themes = [
        r["theme"]
        for r in conn.execute(
            "SELECT theme, COUNT(*) AS n FROM items WHERE lane = 'x' AND theme IS NOT NULL "
            "AND theme != 'Misc' GROUP BY theme ORDER BY n DESC LIMIT 15"
        )
    ]
    collections = [r["name"] for r in conn.execute("SELECT name FROM collections ORDER BY id DESC LIMIT 15")]
    recent_titles = [
        r["title"]
        for r in conn.execute(
            "SELECT title FROM items WHERE lane = 'saved' AND title IS NOT NULL "
            "ORDER BY date_saved DESC, id DESC LIMIT 15"
        )
    ]
    return Profile(topics, feeds, x_accounts, x_themes, collections, recent_titles)


def followed_keys(conn: sqlite3.Connection) -> tuple[set[str], set[str]]:
    """(feed URLs and site hosts you follow, lowercased X handles you follow)."""
    from .urls import canonicalize

    feeds: set[str] = set()
    for r in conn.execute("SELECT url, site_url FROM feeds"):
        for u in (r["url"], r["site_url"]):
            if u:
                feeds.add(canonicalize(u))
    handles = {r["handle"].lower() for r in conn.execute("SELECT handle FROM x_accounts")}
    return feeds, handles


def known_suggestions(conn: sqlite3.Connection, limit: int = 80) -> list[str]:
    """Names already suggested (any status) — passed to the model so it looks further afield."""
    return [
        (f"@{r['handle']}" if r["kind"] == "x" else r["name"])
        for r in conn.execute(
            "SELECT kind, name, handle FROM suggestions ORDER BY id DESC LIMIT ?", (limit,)
        )
    ]


# ------------------------------------------------------------------ runs ----
def create_run(conn: sqlite3.Connection, context: str | None, kinds: str) -> int:
    cur = conn.execute("INSERT INTO discovery_runs (context, kinds) VALUES (?, ?)", (context, kinds))
    return int(cur.lastrowid)


def get_run(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute(f"SELECT {_RUN_COLS} FROM discovery_runs WHERE id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def latest_run(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(f"SELECT {_RUN_COLS} FROM discovery_runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def running_run(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        f"SELECT {_RUN_COLS} FROM discovery_runs WHERE status = 'running' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def finish_run(conn: sqlite3.Connection, run_id: int, *, found: int = 0, error: str | None = None) -> None:
    conn.execute(
        "UPDATE discovery_runs SET status = ?, error = ?, found = ?, finished_at = datetime('now') WHERE id = ?",
        ("failed" if error else "done", error, found, run_id),
    )


def fail_interrupted_runs(conn: sqlite3.Connection) -> int:
    """A run lives in a background thread; a restart kills it, so don't leave it 'running'."""
    cur = conn.execute(
        "UPDATE discovery_runs SET status = 'failed', error = 'Interrupted by a restart. Try again.', "
        "finished_at = datetime('now') WHERE status = 'running'"
    )
    return cur.rowcount


# ----------------------------------------------------------- suggestions ----
def _suggestion_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["topics"] = json.loads(d.get("topics") or "[]")
    except ValueError:
        d["topics"] = []
    return d


def add_suggestion(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    kind: str,
    key: str,
    name: str,
    url: str | None = None,
    feed_url: str | None = None,
    handle: str | None = None,
    description: str | None = None,
    reason: str | None = None,
    topics: list[str] | None = None,
) -> bool:
    """Insert a suggestion. Returns False if this source was suggested before (any status)."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO suggestions "
        "(run_id, kind, key, name, url, feed_url, handle, description, reason, topics) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            kind,
            key,
            name,
            url,
            feed_url,
            handle,
            description,
            reason,
            json.dumps(list(topics or [])[:5], ensure_ascii=False),
        ),
    )
    return cur.rowcount > 0


def get_suggestion(conn: sqlite3.Connection, sid: int) -> dict | None:
    row = conn.execute(f"SELECT {_SUGGESTION_COLS} FROM suggestions WHERE id = ?", (sid,)).fetchone()
    return _suggestion_dict(row) if row else None


def list_suggestions(conn: sqlite3.Connection, status: str = "new") -> list[dict]:
    """Newest run first; within a run, the model's order."""
    return [
        _suggestion_dict(r)
        for r in conn.execute(
            f"SELECT {_SUGGESTION_COLS} FROM suggestions WHERE status = ? "
            "ORDER BY COALESCE(run_id, 0) DESC, id",
            (status,),
        )
    ]


def set_status(conn: sqlite3.Connection, sid: int, status: str) -> bool:
    cur = conn.execute(
        "UPDATE suggestions SET status = ?, acted_at = datetime('now') WHERE id = ?", (status, sid)
    )
    return cur.rowcount > 0


def reconcile_followed(conn: sqlite3.Connection) -> None:
    """Mark 'new' suggestions you've since followed by hand as followed."""
    feeds, handles = followed_keys(conn)
    for s in list_suggestions(conn, "new"):
        if (s["kind"] == "x" and (s["handle"] or "").lower() in handles) or (
            s["kind"] == "blog" and _blog_followed(s, feeds)
        ):
            set_status(conn, s["id"], "followed")


def _blog_followed(s: dict, feeds: set[str]) -> bool:
    from .urls import canonicalize

    return any(u and canonicalize(u) in feeds for u in (s.get("feed_url"), s.get("url")))
