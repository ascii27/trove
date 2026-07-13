from app import store


def _item(conn, url, lane="saved"):
    cur = conn.execute(
        "INSERT INTO items (url_canonical, original_url, lane) VALUES (?, ?, ?)", (url, url, lane)
    )
    return cur.lastrowid


# ---- store ----
def test_create_and_list_for_item_in_document_order(conn):
    a = _item(conn, "https://ex.com/a")
    store.create_highlight(conn, a, "second", 20, 26)
    store.create_highlight(conn, a, "first", 0, 5)
    conn.commit()
    hls = store.highlights_for_item(conn, a)
    assert [h["quote"] for h in hls] == ["first", "second"]  # ordered by start offset
    assert hls[0]["start_offset"] == 0 and hls[0]["end_offset"] == 5


def test_create_on_missing_item_returns_none(conn):
    assert store.create_highlight(conn, 999, "x", 0, 1) is None


def test_get_item_carries_highlights(conn):
    a = _item(conn, "https://ex.com/a")
    store.create_highlight(conn, a, "quote", 3, 8)
    conn.commit()
    item = store.get_item(conn, a)
    assert len(item["highlights"]) == 1
    assert item["highlights"][0]["quote"] == "quote"


def test_list_highlights_includes_source_newest_first(conn):
    a = _item(conn, "https://ex.com/a")
    b = _item(conn, "https://ex.com/b")
    conn.execute("UPDATE items SET title = ? WHERE id = ?", ("Article A", a))
    conn.commit()
    store.create_highlight(conn, a, "older", 0, 5)
    conn.commit()
    store.create_highlight(conn, b, "newer", 0, 5)
    conn.commit()
    archive = store.list_highlights(conn)
    assert archive[0]["quote"] == "newer"  # newest first
    a_entry = next(h for h in archive if h["item_id"] == a)
    assert a_entry["title"] == "Article A"
    assert a_entry["original_url"] == "https://ex.com/a"


def test_delete_highlight(conn):
    a = _item(conn, "https://ex.com/a")
    hl = store.create_highlight(conn, a, "quote", 0, 5)
    conn.commit()
    assert store.delete_highlight(conn, hl["id"])
    conn.commit()
    assert store.highlights_for_item(conn, a) == []
    assert store.delete_highlight(conn, hl["id"]) is False  # already gone


def test_deleting_item_cascades_highlights(conn):
    a = _item(conn, "https://ex.com/a")
    store.create_highlight(conn, a, "quote", 0, 5)
    conn.commit()
    store.delete_item(conn, a)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM highlights WHERE item_id=?", (a,)).fetchone()["c"] == 0


# ---- routes ----
def test_highlight_routes_flow(client):
    a = client.post("/api/items", json={"url": "https://ex.com/a"}).json()["item"]["id"]

    created = client.post(f"/api/items/{a}/highlights", json={"quote": "a passage", "start": 4, "end": 13})
    assert created.status_code == 201
    hid = created.json()["highlight"]["id"]

    # item detail carries the highlight
    assert client.get(f"/api/items/{a}").json()["item"]["highlights"][0]["quote"] == "a passage"

    # global archive lists it with its source
    archive = client.get("/api/highlights").json()["highlights"]
    assert archive[0]["quote"] == "a passage"
    assert archive[0]["item_id"] == a

    # delete, then it's gone
    assert client.delete(f"/api/highlights/{hid}").status_code == 200
    assert client.delete(f"/api/highlights/{hid}").status_code == 404
    assert client.get(f"/api/items/{a}").json()["item"]["highlights"] == []


def test_create_highlight_validates(client):
    a = client.post("/api/items", json={"url": "https://ex.com/a"}).json()["item"]["id"]
    assert client.post(f"/api/items/{a}/highlights", json={"quote": "  ", "start": 0, "end": 5}).status_code == 422
    assert client.post(f"/api/items/{a}/highlights", json={"quote": "x", "start": 5, "end": 5}).status_code == 422
    assert client.post("/api/items/999/highlights", json={"quote": "x", "start": 0, "end": 1}).status_code == 404
