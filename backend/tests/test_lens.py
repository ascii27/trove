from app import lens, store, topics


def test_expand_covers_related_concepts():
    terms = lens.expand("AI")
    for t in ("ai", "llm", "agents", "inference"):
        assert t in terms


def test_expand_phrase_and_empty():
    assert "platform engineering" in lens.expand("platform engineering")
    assert lens.expand("   ") == set()


def test_score_weights_topics_over_text():
    terms = lens.expand("AI")
    # Same text; the item also tagged with the topic should score higher.
    tagged, matched = lens.score_item(
        title="an essay on llm agents", summary="", category=None, claims=[], item_topics=["AI"], terms=terms
    )
    untagged, _ = lens.score_item(
        title="an essay on llm agents", summary="", category=None, claims=[], item_topics=[], terms=terms
    )
    assert tagged > untagged
    assert matched == ["AI"]


def _item(conn, url, lane, *, summary=None, topic_names=None, feed_id=None):
    cur = conn.execute(
        "INSERT INTO items (url_canonical, original_url, lane, feed_id, title, summary, extraction_status, enrichment_status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'extracted', 'done')",
        (url, url, lane, feed_id, url, summary),
    )
    iid = cur.lastrowid
    if topic_names:
        topics.set_item_topics(conn, iid, topic_names)
    return iid


def test_lens_search_ranks_cross_lane(conn):
    feed_id = store.add_feed(conn, "https://f/feed", None, "F")
    a = _item(conn, "https://ex.com/a", "saved", summary="about inference at scale", topic_names=["AI", "evals"])
    _item(conn, "https://ex.com/b", "feed", summary="the paved road", topic_names=["platform engineering"], feed_id=feed_id)
    c = _item(conn, "https://ex.com/c", "saved", summary="an essay about LLM agents")  # text hit only, no AI topic
    conn.commit()

    res = store.lens_search(conn, "AI")
    ids = [i["id"] for i in res["items"]]
    assert a in ids and c in ids
    assert res["items"][0]["id"] == a  # topic match ranks first
    assert "AI" in res["items"][0]["matched_topics"]
    # item b (platform engineering) is not a match for "AI"
    assert all(i["id"] != _item_id_of(conn, "https://ex.com/b") for i in res["items"])
    assert res["saved_count"] == 2 and res["feed_count"] == 0


def _item_id_of(conn, url):
    return conn.execute("SELECT id FROM items WHERE url_canonical=?", (url,)).fetchone()["id"]


def test_lens_search_excludes_archived(conn):
    _item(conn, "https://ex.com/a", "saved", summary="inference", topic_names=["AI"])
    arch = _item(conn, "https://ex.com/old", "feed", summary="inference", topic_names=["AI"])
    conn.execute("UPDATE items SET read_state='archived' WHERE id=?", (arch,))
    conn.commit()
    res = store.lens_search(conn, "AI")
    assert arch not in [i["id"] for i in res["items"]]


def test_lens_route_empty_query(client):
    r = client.get("/api/lens")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == [] and body["saved_count"] == 0
