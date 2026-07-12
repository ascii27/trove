from app import store, worker
from app.enrich import EnrichResult
from app.extract import Extracted


def _seed_item(conn, url="https://example.com/a"):
    item_id = store.create_item(conn, url, url)  # also enqueues the extract job
    conn.commit()
    return item_id


def _drain_extract(conn):
    """Claim + complete the pending extract job with a canned success."""
    job = store.claim_next_job(conn)
    assert job["kind"] == "extract"
    worker.process_job(
        conn,
        job,
        fetch_and_extract=lambda url: Extracted(
            status="extracted", title="T", source="src", content_text="the body text",
            word_count=250, reading_minutes=2,
        ),
    )
    return job


def test_extract_job_runs_and_enqueues_enrich(conn):
    item_id = _seed_item(conn)
    job = store.claim_next_job(conn)
    assert job["kind"] == "extract"
    # claim flips the item to 'extracting'
    assert conn.execute("SELECT extraction_status FROM items WHERE id=?", (item_id,)).fetchone()[0] == "extracting"

    worker.process_job(
        conn,
        job,
        fetch_and_extract=lambda url: Extracted(
            status="extracted", title="T", source="src", content_text="the body text", word_count=250, reading_minutes=2
        ),
    )
    item = conn.execute("SELECT extraction_status, title FROM items WHERE id=?", (item_id,)).fetchone()
    assert item["extraction_status"] == "extracted"
    assert item["title"] == "T"
    assert conn.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()[0] == "done"
    assert conn.execute(
        "SELECT COUNT(*) c FROM jobs WHERE item_id=? AND kind='enrich' AND status='pending'", (item_id,)
    ).fetchone()["c"] == 1


def test_enrich_job_stores_metadata(conn):
    item_id = _seed_item(conn)
    _drain_extract(conn)  # this enqueues the single enrich job

    job = store.claim_next_job(conn)
    assert job["kind"] == "enrich"
    worker.process_job(
        conn,
        job,
        enrich=lambda title, text: EnrichResult(
            summary="A summary.",
            topics=["AI", "artificial intelligence"],
            category="essay",
            source_type="analysis",
            claims=["Claim one.", "Claim two."],
        ),
    )
    item = store.get_item(conn, item_id)
    assert item["enrichment_status"] == "done"
    assert item["summary"] == "A summary."
    assert item["source_type"] == "analysis"
    assert item["topics"] == ["AI"]  # synonyms folded
    assert item["claims"] == ["Claim one.", "Claim two."]


def test_enrich_failure_retries_then_fails(conn):
    item_id = _seed_item(conn)
    _drain_extract(conn)  # enqueues one enrich job

    def boom(title, text):
        raise RuntimeError("api down")

    statuses = []
    for _ in range(store.MAX_ATTEMPTS + 2):
        job = store.claim_next_job(conn)
        if job is None:
            break
        assert job["kind"] == "enrich"
        worker.process_job(conn, job, enrich=boom)
        statuses.append(conn.execute("SELECT status FROM jobs WHERE id=?", (job["id"],)).fetchone()[0])

    assert statuses[-1] == "failed"
    assert conn.execute("SELECT enrichment_status FROM items WHERE id=?", (item_id,)).fetchone()[0] == "failed"
