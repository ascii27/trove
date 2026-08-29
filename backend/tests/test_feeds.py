from app import store, worker
from app.feedfetch import Entry, ParsedFeed


def _entries(n, prefix="https://ex.com/"):
    return [Entry(title=f"Post {i}", link=f"{prefix}{i}", summary=f"summary {i}", published="2026-07-01") for i in range(n)]


def test_ingest_eager_then_deferred(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", "https://ex.com", "Ex")
    counts = store.ingest_entries(conn, feed_id, "Ex", _entries(12), eager_limit=10)
    conn.commit()
    assert counts == {"eager": 10, "deferred": 2}

    rows = conn.execute("SELECT extraction_status, COUNT(*) c FROM items WHERE lane='feed' GROUP BY extraction_status").fetchall()
    by_status = {r["extraction_status"]: r["c"] for r in rows}
    assert by_status["pending"] == 10
    assert by_status["deferred"] == 2
    # only eager items got extract jobs
    assert conn.execute("SELECT COUNT(*) c FROM jobs WHERE kind='extract'").fetchone()["c"] == 10
    # deferred items still carry the feed's summary for the list preview
    deferred = conn.execute("SELECT summary FROM items WHERE extraction_status='deferred' LIMIT 1").fetchone()
    assert deferred["summary"].startswith("summary")


def test_ingest_dedupes_across_library(conn):
    # an already-saved article shouldn't re-appear as a feed item
    store.create_item(conn, "https://ex.com/1", "https://ex.com/1")
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    counts = store.ingest_entries(conn, feed_id, "Ex", _entries(3))
    conn.commit()
    assert counts["eager"] == 2  # /1 skipped as duplicate
    assert conn.execute("SELECT COUNT(*) c FROM items WHERE lane='feed'").fetchone()["c"] == 2


def test_poll_feed_ingests_via_injected_resolver(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, None)
    feed = store.get_feed(conn, feed_id)
    conn.commit()

    def resolve(_url):
        return "https://ex.com/feed", ParsedFeed(title="Ex Blog", site_url="https://ex.com", entries=_entries(3))

    counts = worker.poll_feed(conn, feed, resolve=resolve)
    assert counts["eager"] == 3
    updated = store.get_feed(conn, feed_id)
    assert updated["title"] == "Ex Blog"
    assert updated["last_polled_at"] is not None
    assert updated["last_error"] is None


def test_poll_feed_records_error(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    feed = store.get_feed(conn, feed_id)
    conn.commit()

    def boom(_url):
        raise RuntimeError("feed down")

    counts = worker.poll_feed(conn, feed, resolve=boom)
    assert "error" in counts
    assert "feed down" in store.get_feed(conn, feed_id)["last_error"]


def test_age_feed_items_archives_old_unread(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    conn.execute(
        "INSERT INTO items (url_canonical, original_url, lane, feed_id, read_state, date_saved) "
        "VALUES ('https://ex.com/old', 'https://ex.com/old', 'feed', ?, 'unread', datetime('now','-40 days'))",
        (feed_id,),
    )
    conn.execute(
        "INSERT INTO items (url_canonical, original_url, lane, feed_id, read_state, date_saved) "
        "VALUES ('https://ex.com/new', 'https://ex.com/new', 'feed', ?, 'unread', datetime('now'))",
        (feed_id,),
    )
    conn.commit()
    n = store.age_feed_items(conn, 30)
    conn.commit()
    assert n == 1
    states = {r["url_canonical"]: r["read_state"] for r in conn.execute("SELECT url_canonical, read_state FROM items")}
    assert states["https://ex.com/old"] == "archived"
    assert states["https://ex.com/new"] == "unread"


def test_promote_to_saved_loads_deferred(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    store.ingest_entries(conn, feed_id, "Ex", _entries(11), eager_limit=10)  # 11th is deferred
    conn.commit()
    deferred = conn.execute("SELECT id FROM items WHERE extraction_status='deferred'").fetchone()["id"]

    assert store.promote_to_saved(conn, deferred)
    conn.commit()
    row = conn.execute("SELECT lane, extraction_status FROM items WHERE id=?", (deferred,)).fetchone()
    assert row["lane"] == "saved"
    assert row["extraction_status"] == "pending"  # load triggered
    assert conn.execute("SELECT COUNT(*) c FROM jobs WHERE item_id=? AND kind='extract'", (deferred,)).fetchone()["c"] == 1


def test_delete_feed_keeps_saved_items(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    store.ingest_entries(conn, feed_id, "Ex", _entries(3))
    conn.commit()
    keep = conn.execute("SELECT id FROM items WHERE lane='feed' LIMIT 1").fetchone()["id"]
    store.promote_to_saved(conn, keep)
    conn.commit()

    assert store.delete_feed(conn, feed_id)
    conn.commit()
    remaining = conn.execute("SELECT id, lane FROM items").fetchall()
    assert [r["id"] for r in remaining] == [keep]
    assert remaining[0]["lane"] == "saved"
    assert store.get_feed(conn, feed_id) is None


def test_feed_items_list_newest_first(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    # Insert in feed order (newest first), each with its own publish timestamp.
    entries = [
        Entry(title="new", link="https://ex.com/new", summary="s", published="d3", published_at="2026-07-10T00:00:00"),
        Entry(title="mid", link="https://ex.com/mid", summary="s", published="d2", published_at="2026-07-05T00:00:00"),
        Entry(title="old", link="https://ex.com/old", summary="s", published="d1", published_at="2026-07-01T00:00:00"),
    ]
    store.ingest_entries(conn, feed_id, "Ex", entries)
    conn.commit()
    titles = [i["title"] for i in store.list_items(conn, "feed", feed_id)]
    assert titles == ["new", "mid", "old"]  # newest publish date first


def test_list_feeds_unread_counts(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    store.ingest_entries(conn, feed_id, "Ex", _entries(3))
    conn.commit()
    feeds = store.list_feeds(conn)
    assert feeds[0]["unread_count"] == 3


# --------------------------------------------- deferred enrichment (on open) ----
def _extracted(**kw):
    from app.extract import Extracted

    return Extracted(status="extracted", title="T", content_text="body", word_count=300, reading_minutes=2, **kw)


def test_ingest_defers_enrichment_for_every_feed_item(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    store.ingest_entries(conn, feed_id, "Ex", _entries(12), eager_limit=10)
    conn.commit()
    statuses = {r["enrichment_status"] for r in conn.execute("SELECT enrichment_status FROM items WHERE lane='feed'")}
    assert statuses == {"deferred"}


def test_extracting_a_feed_item_does_not_enqueue_enrich(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    store.ingest_entries(conn, feed_id, "Ex", _entries(1), eager_limit=10)
    conn.commit()
    item_id = conn.execute("SELECT id FROM items WHERE lane='feed'").fetchone()["id"]

    store.apply_extraction(conn, item_id, _extracted())
    conn.commit()

    kinds = [j["kind"] for j in conn.execute("SELECT kind FROM jobs WHERE item_id=?", (item_id,))]
    assert "enrich" not in kinds


def test_opening_an_extracted_feed_item_enqueues_enrich(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    store.ingest_entries(conn, feed_id, "Ex", _entries(1), eager_limit=10)
    item_id = conn.execute("SELECT id FROM items WHERE lane='feed'").fetchone()["id"]
    store.apply_extraction(conn, item_id, _extracted())
    conn.commit()

    store.on_open(conn, item_id)
    conn.commit()

    row = conn.execute("SELECT enrichment_status FROM items WHERE id=?", (item_id,)).fetchone()
    assert row["enrichment_status"] == "pending"
    kinds = [j["kind"] for j in conn.execute("SELECT kind FROM jobs WHERE item_id=?", (item_id,))]
    assert kinds.count("enrich") == 1


def test_opening_a_deferred_feed_item_chains_extract_then_enrich(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    store.ingest_entries(conn, feed_id, "Ex", _entries(11), eager_limit=10)
    conn.commit()
    item_id = conn.execute("SELECT id FROM items WHERE extraction_status='deferred'").fetchone()["id"]

    store.on_open(conn, item_id)
    conn.commit()
    kinds = [j["kind"] for j in conn.execute("SELECT kind FROM jobs WHERE item_id=?", (item_id,))]
    assert kinds == ["extract"]  # nothing to enrich until there's content

    store.apply_extraction(conn, item_id, _extracted())
    conn.commit()
    kinds = [j["kind"] for j in conn.execute("SELECT kind FROM jobs WHERE item_id=?", (item_id,))]
    assert kinds.count("enrich") == 1


def test_opening_twice_enqueues_only_one_enrich(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    store.ingest_entries(conn, feed_id, "Ex", _entries(1), eager_limit=10)
    item_id = conn.execute("SELECT id FROM items WHERE lane='feed'").fetchone()["id"]
    store.apply_extraction(conn, item_id, _extracted())
    conn.commit()

    store.on_open(conn, item_id)
    store.on_open(conn, item_id)
    conn.commit()

    kinds = [j["kind"] for j in conn.execute("SELECT kind FROM jobs WHERE item_id=?", (item_id,))]
    assert kinds.count("enrich") == 1


def test_promote_to_saved_clears_the_enrichment_deferral(conn):
    feed_id = store.add_feed(conn, "https://ex.com/feed", None, "Ex")
    store.ingest_entries(conn, feed_id, "Ex", _entries(1), eager_limit=10)
    item_id = conn.execute("SELECT id FROM items WHERE lane='feed'").fetchone()["id"]
    store.apply_extraction(conn, item_id, _extracted())
    conn.commit()

    assert store.promote_to_saved(conn, item_id)
    conn.commit()

    row = conn.execute("SELECT enrichment_status FROM items WHERE id=?", (item_id,)).fetchone()
    assert row["enrichment_status"] == "pending"
    kinds = [j["kind"] for j in conn.execute("SELECT kind FROM jobs WHERE item_id=?", (item_id,))]
    assert kinds.count("enrich") == 1
