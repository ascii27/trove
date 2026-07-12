import pytest

from app import feedfetch
from app.feedfetch import Entry, ParsedFeed


@pytest.fixture
def fake_resolve(monkeypatch):
    def _install(parsed: ParsedFeed, feed_url="https://ex.com/feed"):
        monkeypatch.setattr(feedfetch, "resolve_feed", lambda url, **kw: (feed_url, parsed))

    return _install


def _entries(n):
    return [Entry(title=f"Post {i}", link=f"https://ex.com/{i}", summary=f"s{i}", published="2026-07-01") for i in range(n)]


def test_add_feed_and_list(client, fake_resolve):
    fake_resolve(ParsedFeed(title="Ex Blog", site_url="https://ex.com", entries=_entries(3)))
    r = client.post("/api/feeds", json={"url": "https://ex.com"})
    assert r.status_code == 201
    feed = r.json()["feed"]
    assert feed["title"] == "Ex Blog"
    assert feed["unread_count"] == 3

    feeds = client.get("/api/feeds").json()["feeds"]
    assert len(feeds) == 1 and feeds[0]["unread_count"] == 3

    fid = feed["id"]
    items = client.get(f"/api/items?view=feed&feed_id={fid}").json()["items"]
    assert len(items) == 3
    assert all(i["lane"] == "feed" for i in items)


def test_feed_view_requires_feed_id(client):
    assert client.get("/api/items?view=feed").status_code == 422


def test_saved_view_excludes_feed_items(client, fake_resolve):
    fake_resolve(ParsedFeed(title="Ex", site_url=None, entries=_entries(2)))
    client.post("/api/feeds", json={"url": "https://ex.com"})
    client.post("/api/items", json={"url": "https://saved.example.com/x"})
    saved = client.get("/api/items?view=all").json()["items"]
    assert len(saved) == 1 and saved[0]["lane"] == "saved"


def test_open_deferred_item_triggers_load(client, fake_resolve):
    fake_resolve(ParsedFeed(title="Ex", site_url=None, entries=_entries(11)))  # 11th deferred
    fid = client.post("/api/feeds", json={"url": "https://ex.com"}).json()["feed"]["id"]
    items = client.get(f"/api/items?view=feed&feed_id={fid}").json()["items"]
    deferred = [i for i in items if i["extraction_status"] == "deferred"]
    assert deferred, "expected a deferred item"
    opened = client.get(f"/api/items/{deferred[0]['id']}").json()["item"]
    assert opened["extraction_status"] == "pending"  # load kicked off


def test_save_promotes_feed_item(client, fake_resolve):
    fake_resolve(ParsedFeed(title="Ex", site_url=None, entries=_entries(2)))
    fid = client.post("/api/feeds", json={"url": "https://ex.com"}).json()["feed"]["id"]
    item_id = client.get(f"/api/items?view=feed&feed_id={fid}").json()["items"][0]["id"]
    saved = client.post(f"/api/items/{item_id}/save").json()["item"]
    assert saved["lane"] == "saved"
    assert item_id in [i["id"] for i in client.get("/api/items?view=all").json()["items"]]


def test_delete_feed(client, fake_resolve):
    fake_resolve(ParsedFeed(title="Ex", site_url=None, entries=_entries(2)))
    fid = client.post("/api/feeds", json={"url": "https://ex.com"}).json()["feed"]["id"]
    assert client.delete(f"/api/feeds/{fid}").status_code == 200
    assert client.get("/api/feeds").json()["feeds"] == []
    assert client.delete(f"/api/feeds/{fid}").status_code == 404


def test_add_feed_no_feed_found(client, monkeypatch):
    def boom(url, **kw):
        raise feedfetch.FeedError("Couldn't find a feed at that URL.")

    monkeypatch.setattr(feedfetch, "resolve_feed", boom)
    r = client.post("/api/feeds", json={"url": "https://nope.example.com"})
    assert r.status_code == 422
