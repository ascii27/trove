def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_capture_creates_pending_item(client):
    r = client.post("/api/items", json={"url": "https://example.com/post"})
    assert r.status_code == 201
    body = r.json()
    assert body["duplicate"] is False
    assert body["item"]["extraction_status"] == "pending"
    assert body["item"]["read_state"] == "unread"


def test_capture_dedupes(client):
    first = client.post("/api/items", json={"url": "https://www.example.com/post?utm_source=x"}).json()
    second = client.post("/api/items", json={"url": "https://example.com/post"}).json()
    assert second["duplicate"] is True
    assert second["item"]["id"] == first["item"]["id"]


def test_capture_rejects_blank(client):
    r = client.post("/api/items", json={"url": "   "})
    assert r.status_code == 422


def test_list_and_unread_count(client):
    client.post("/api/items", json={"url": "https://example.com/a"})
    client.post("/api/items", json={"url": "https://example.com/b"})
    r = client.get("/api/items?view=all")
    body = r.json()
    assert len(body["items"]) == 2
    assert body["unread_count"] == 2


def test_mark_read_unread_roundtrip(client):
    item_id = client.post("/api/items", json={"url": "https://example.com/a"}).json()["item"]["id"]
    read = client.post(f"/api/items/{item_id}/read").json()
    assert read["item"]["read_state"] == "read"
    assert read["unread_count"] == 0
    unread = client.post(f"/api/items/{item_id}/unread").json()
    assert unread["item"]["read_state"] == "unread"
    assert unread["unread_count"] == 1


def test_get_missing_item_404(client):
    assert client.get("/api/items/999").status_code == 404


def test_list_rejects_bad_view(client):
    assert client.get("/api/items?view=weird").status_code == 422
