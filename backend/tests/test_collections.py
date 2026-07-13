from app import store


def _item(conn, url, lane="saved"):
    cur = conn.execute(
        "INSERT INTO items (url_canonical, original_url, lane) VALUES (?, ?, ?)", (url, url, lane)
    )
    return cur.lastrowid


# ---- store ----
def test_create_collection_with_items_and_count(conn):
    a = _item(conn, "https://ex.com/a")
    b = _item(conn, "https://ex.com/b", lane="feed")
    cid = store.create_collection(conn, "AI research", query="AI", item_ids=[a, b])
    conn.commit()
    cols = store.list_collections(conn)
    assert cols[0]["name"] == "AI research"
    assert cols[0]["query"] == "AI"
    assert cols[0]["item_count"] == 2
    ids = [i["id"] for i in store.collection_items(conn, cid)]
    assert set(ids) == {a, b}  # cross-lane members


def test_add_remove_and_multi_membership(conn):
    a = _item(conn, "https://ex.com/a")
    c1 = store.create_collection(conn, "One")
    c2 = store.create_collection(conn, "Two")
    conn.commit()
    assert store.add_item_to_collection(conn, c1, a)
    assert store.add_item_to_collection(conn, c2, a)  # same item in two collections
    conn.commit()
    assert store.get_item(conn, a)["collection_ids"] == sorted([c1, c2])
    assert store.remove_item_from_collection(conn, c1, a)
    conn.commit()
    assert store.get_item(conn, a)["collection_ids"] == [c2]


def test_add_rejects_missing_item_or_collection(conn):
    a = _item(conn, "https://ex.com/a")
    cid = store.create_collection(conn, "One")
    conn.commit()
    assert store.add_item_to_collection(conn, cid, 999) is False
    assert store.add_item_to_collection(conn, 999, a) is False


def test_delete_collection_cascades_membership(conn):
    a = _item(conn, "https://ex.com/a")
    cid = store.create_collection(conn, "One", item_ids=[a])
    conn.commit()
    assert store.delete_collection(conn, cid)
    conn.commit()
    assert store.get_collection(conn, cid) is None
    assert conn.execute("SELECT COUNT(*) c FROM item_collections WHERE collection_id=?", (cid,)).fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM items WHERE id=?", (a,)).fetchone()["c"] == 1  # item survives


# ---- routes ----
def test_collection_routes_flow(client):
    a = client.post("/api/items", json={"url": "https://ex.com/a"}).json()["item"]["id"]
    b = client.post("/api/items", json={"url": "https://ex.com/b"}).json()["item"]["id"]

    created = client.post("/api/collections", json={"name": "AI", "query": "AI", "item_ids": [a]})
    assert created.status_code == 201
    cid = created.json()["collection"]["id"]
    assert created.json()["collection"]["item_count"] == 1

    # add the second item, and the item's detail reports its membership
    client.post(f"/api/collections/{cid}/items", json={"item_id": b})
    assert client.get(f"/api/items/{b}").json()["item"]["collection_ids"] == [cid]

    got = client.get(f"/api/collections/{cid}").json()
    assert got["collection"]["name"] == "AI"
    assert {i["id"] for i in got["items"]} == {a, b}

    # remove one, then delete the collection
    client.request("DELETE", f"/api/collections/{cid}/items/{a}")
    assert {i["id"] for i in client.get(f"/api/collections/{cid}").json()["items"]} == {b}
    assert client.delete(f"/api/collections/{cid}").status_code == 200
    assert client.get(f"/api/collections/{cid}").status_code == 404


def test_create_collection_requires_name(client):
    assert client.post("/api/collections", json={"name": "  "}).status_code == 422
