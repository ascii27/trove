from app import topics


def test_canonicalize_folds_synonyms():
    assert topics.canonicalize("artificial intelligence") == "AI"
    assert topics.canonicalize("ML") == "AI"
    assert topics.canonicalize("llms") == "AI"
    assert topics.canonicalize("  AI ") == "AI"


def test_canonicalize_passthrough_and_empty():
    assert topics.canonicalize("Wardley Maps") == "Wardley Maps"
    assert topics.canonicalize("   ") is None


def test_set_item_topics_dedupes_case_and_synonyms(conn):
    conn.execute("INSERT INTO items (url_canonical, original_url) VALUES ('u', 'u')")
    item_id = conn.execute("SELECT id FROM items").fetchone()["id"]

    topics.set_item_topics(conn, item_id, ["AI", "artificial intelligence", "ml", "Platform Engineering", "platform engineering"])
    conn.commit()

    names = [
        r["name"]
        for r in conn.execute(
            "SELECT t.name FROM topics t JOIN item_topics it ON it.topic_id = t.id "
            "WHERE it.item_id = ? ORDER BY t.name",
            (item_id,),
        )
    ]
    # AI/ML/artificial intelligence collapse to one; platform engineering dedupes by case
    assert names == ["AI", "platform engineering"]
    # topics table did not accumulate duplicate rows
    assert conn.execute("SELECT COUNT(*) c FROM topics").fetchone()["c"] == 2
