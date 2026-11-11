"""Background job worker + feed scheduler.

`process_job` and `poll_feed` are pure-ish units (inject extract/enrich/resolve)
so tests drive them directly. `Worker` runs them in a daemon thread that polls
the durable jobs table and, on a cadence, polls due feeds and ages old feed
items. Single thread => the worker is a singleton, matching single-user load.
"""
from __future__ import annotations

import sqlite3
import threading
import time

from . import config, db, store
from . import enrich as enrich_mod
from . import extract as extract_mod
from . import feedfetch, xsource, xstore, xthemes


def process_job(
    conn: sqlite3.Connection,
    job: sqlite3.Row,
    *,
    fetch_and_extract=extract_mod.fetch_and_extract,
    fetch_metadata=extract_mod.fetch_metadata,
    enrich=enrich_mod.enrich,
) -> None:
    """Run one claimed job to completion (or record failure for retry)."""
    try:
        if job["kind"] == "extract":
            item = conn.execute(
                "SELECT original_url FROM items WHERE id = ?", (job["item_id"],)
            ).fetchone()
            result = fetch_and_extract(item["original_url"])
            store.apply_extraction(conn, job["item_id"], result)
            store.complete_job(conn, job["id"])
        elif job["kind"] == "enrich":
            item = conn.execute(
                "SELECT title, content_text FROM items WHERE id = ?", (job["item_id"],)
            ).fetchone()
            result = enrich(item["title"], item["content_text"] or "")
            store.apply_enrichment(conn, job["item_id"], result)
            store.complete_job(conn, job["id"])
        elif job["kind"] == "bookmark":
            item = conn.execute(
                "SELECT original_url FROM items WHERE id = ?", (job["item_id"],)
            ).fetchone()
            meta = fetch_metadata(item["original_url"])
            enriched = None
            if meta.body_text:
                # AI is optional for a bookmark — a failure here still leaves a usable link.
                try:
                    enriched = enrich(meta.title, meta.body_text)
                except Exception:  # noqa: BLE001
                    enriched = None
            store.apply_bookmark(conn, job["item_id"], meta, enriched)
            store.complete_job(conn, job["id"])
        else:  # pragma: no cover - unknown kind
            store.fail_job(conn, job, f"Unknown job kind: {job['kind']}")
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - a failing job must not kill the worker
        conn.rollback()
        store.fail_job(conn, job, f"{exc.__class__.__name__}: {exc}")
        conn.commit()


def poll_feed(conn: sqlite3.Connection, feed: sqlite3.Row, *, resolve=feedfetch.resolve_feed) -> dict:
    """Fetch a feed and ingest new entries; records last_error on failure."""
    try:
        _url, parsed = resolve(feed["url"])
        counts = store.ingest_entries(conn, feed["id"], parsed.title or feed["title"], parsed.entries)
        if parsed.title and parsed.title != feed["title"]:
            conn.execute(
                "UPDATE feeds SET title = ?, site_url = COALESCE(site_url, ?) WHERE id = ?",
                (parsed.title, parsed.site_url, feed["id"]),
            )
        store.mark_feed_polled(conn, feed["id"], None)
        conn.commit()
        return counts
    except Exception as exc:  # noqa: BLE001 - a bad feed must not kill the worker
        conn.rollback()
        store.mark_feed_polled(conn, feed["id"], f"{exc.__class__.__name__}: {exc}")
        conn.commit()
        return {"eager": 0, "deferred": 0, "error": str(exc)}


def poll_x_account(conn: sqlite3.Connection, account: sqlite3.Row, source) -> dict:
    """Fetch an account's new posts (since the newest we've seen) and ingest them,
    stitching self-threads into single items. Records last_error on failure."""
    try:
        profile = xsource.XProfile(
            handle=account["handle"], user_id=account["user_id"], name=account["name"],
            avatar_url=account["avatar_url"],
        )
        if source.mode == "api" and not profile.user_id:
            profile = source.lookup(profile.handle)
            xstore.update_profile(conn, account["id"], profile)
            account = xstore.get_account(conn, account["id"])
        posts = source.fetch(profile, account["last_seen_id"], config.x_max_results())
        counts = xstore.ingest_threads(conn, account, xsource.stitch_threads(posts))
        xstore.mark_polled(conn, account["id"], None)
        conn.commit()
        return counts
    except Exception as exc:  # noqa: BLE001 - a bad account must not kill the worker
        conn.rollback()
        msg = str(exc) if isinstance(exc, xsource.XError) else f"{exc.__class__.__name__}: {exc}"
        xstore.mark_polled(conn, account["id"], msg)
        conn.commit()
        return {"created": 0, "appended": 0, "error": msg}


def theme_posts(conn: sqlite3.Connection, *, classify=xthemes.classify, batch: int = xthemes.BATCH_SIZE) -> int:
    """Assign themes to one batch of unthemed posts. Returns how many were themed.
    Without an Anthropic key this is a no-op (posts group under "Not yet sorted")."""
    rows = xstore.unthemed_posts(conn, batch)
    if not rows:
        return 0
    inputs = [xthemes.ThemeInput(id=r["id"], author=r["author"], text=r["content_text"] or r["title"] or "") for r in rows]
    themes = classify(inputs, xstore.existing_themes(conn))
    # Anything the model skipped becomes 'Misc' so it isn't re-sent forever.
    for r in rows:
        themes.setdefault(r["id"], "Misc")
    xstore.apply_themes(conn, themes)
    conn.commit()
    return len(themes)


class Worker:
    def __init__(self, db_path: str | None = None, poll: float = 1.0, maint_interval: float = 30.0):
        self.db_path = db_path
        self.poll = poll
        self.maint_interval = maint_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_age = 0.0
        self._theme_backoff_until = 0.0

    def _maintenance(self, conn: sqlite3.Connection) -> None:
        for feed in store.feeds_due(conn, config.feed_poll_seconds()):
            poll_feed(conn, feed)
        source = xsource.get_source()
        if source is not None:
            for account in xstore.accounts_due(conn, config.x_poll_seconds()):
                poll_x_account(conn, account, source)
        now = time.monotonic()
        if config.anthropic_api_key() and now >= self._theme_backoff_until:
            try:
                theme_posts(conn)
            except Exception:  # noqa: BLE001 - themes are a nicety; back off and retry later
                conn.rollback()
                self._theme_backoff_until = now + 900
        if now - self._last_age >= config.feed_age_sweep_seconds():
            store.age_feed_items(conn, config.feed_age_days())
            xstore.age_posts(conn, config.feed_age_days())
            conn.commit()
            self._last_age = now

    def _run(self) -> None:
        conn = db.connect(self.db_path)
        last_maint = 0.0
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_maint >= self.maint_interval:
                    try:
                        self._maintenance(conn)
                    except Exception:  # noqa: BLE001 - maintenance must not kill the worker
                        pass
                    last_maint = now
                job = store.claim_next_job(conn)
                if job is None:
                    self._stop.wait(self.poll)
                    continue
                process_job(conn, job)
        finally:
            conn.close()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="trove-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
