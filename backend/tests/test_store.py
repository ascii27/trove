from app import store
from app.extract import Extracted


def _new_item(conn, url="https://example.com/a"):
    item_id = store.create_item(conn, url, url)
    conn.commit()
    return item_id


def test_create_item_is_pending_and_enqueues_extract(conn):
    item_id = _new_item(conn)
    row = conn.execute("SELECT extraction_status FROM items WHERE id=?", (item_id,)).fetchone()
    assert row["extraction_status"] == "pending"
    jobs = conn.execute("SELECT kind, status FROM jobs WHERE item_id=?", (item_id,)).fetchall()
    assert [(j["kind"], j["status"]) for j in jobs] == [("extract", "pending")]


def test_apply_extraction_extracted_enqueues_enrich(conn):
    item_id = _new_item(conn)
    store.apply_extraction(
        conn,
        item_id,
        Extracted(status="extracted", title="T", content_text="body", word_count=300, reading_minutes=2),
    )
    conn.commit()
    item = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    assert item["extraction_status"] == "extracted"
    assert item["title"] == "T"
    kinds = [j["kind"] for j in conn.execute("SELECT kind FROM jobs WHERE item_id=?", (item_id,))]
    assert "enrich" in kinds


def test_apply_extraction_failed_does_not_enqueue_enrich(conn):
    item_id = _new_item(conn)
    store.apply_extraction(conn, item_id, Extracted(status="failed", error="boom"))
    conn.commit()
    kinds = [j["kind"] for j in conn.execute("SELECT kind FROM jobs WHERE item_id=?", (item_id,))]
    assert "enrich" not in kinds
    item = conn.execute("SELECT extraction_status, error_message FROM items WHERE id=?", (item_id,)).fetchone()
    assert item["extraction_status"] == "failed"
    assert item["error_message"] == "boom"


def test_read_state_and_unread_count(conn):
    a = _new_item(conn, "https://example.com/a")
    b = _new_item(conn, "https://example.com/b")
    assert store.unread_count(conn) == 2
    assert store.set_read_state(conn, a, "read")
    conn.commit()
    assert store.unread_count(conn) == 1
    assert [i["id"] for i in store.list_items(conn, "unread")] == [b]


def test_retry_extract_resets_and_requeues(conn):
    item_id = _new_item(conn)
    # Mirror the worker: the extract job completes, leaving the item in 'failed'.
    job = store.claim_next_job(conn)
    store.apply_extraction(conn, item_id, Extracted(status="failed", error="boom"))
    store.complete_job(conn, job["id"])
    conn.commit()
    assert store.retry_extract(conn, item_id)
    conn.commit()
    item = conn.execute("SELECT extraction_status, error_message FROM items WHERE id=?", (item_id,)).fetchone()
    assert item["extraction_status"] == "pending"
    assert item["error_message"] is None
    pending_extract = conn.execute(
        "SELECT COUNT(*) c FROM jobs WHERE item_id=? AND kind='extract' AND status='pending'", (item_id,)
    ).fetchone()["c"]
    assert pending_extract == 1
