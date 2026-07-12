"""Background job worker.

`process_job` is a pure-ish unit (inject extract/enrich) so tests drive it
directly. `Worker` runs it in a daemon thread that polls the durable jobs table,
started/stopped from the FastAPI lifespan. Single thread => the worker is a
singleton, matching single-user load and the single uvicorn worker.
"""
from __future__ import annotations

import sqlite3
import threading

from . import db, store
from . import enrich as enrich_mod
from . import extract as extract_mod


def process_job(
    conn: sqlite3.Connection,
    job: sqlite3.Row,
    *,
    fetch_and_extract=extract_mod.fetch_and_extract,
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
        else:  # pragma: no cover - unknown kind
            store.fail_job(conn, job, f"Unknown job kind: {job['kind']}")
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - a failing job must not kill the worker
        conn.rollback()
        store.fail_job(conn, job, f"{exc.__class__.__name__}: {exc}")
        conn.commit()


class Worker:
    def __init__(self, db_path: str | None = None, poll: float = 1.0):
        self.db_path = db_path
        self.poll = poll
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        conn = db.connect(self.db_path)
        try:
            while not self._stop.is_set():
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
