from app import extract, store, worker
from app.enrich import EnrichResult
from app.extract import BookmarkMeta

# --- fixtures: a small HTML page with rich metadata ---
PAGE = """
<html><head>
  <title>Ripgrep — fast recursive search</title>
  <meta property="og:site_name" content="GitHub">
  <meta name="description" content="ripgrep recursively searches directories for a regex pattern.">
  <link rel="icon" href="/favicon-32.png">
</head><body>
  <article><h1>ripgrep</h1><p>ripgrep is a line-oriented search tool that recursively
  searches the current directory for a regex pattern while respecting gitignore rules.</p></article>
</body></html>
"""


def _bookmark_item(conn, url="https://github.com/BurntSushi/ripgrep"):
    return store.create_item(conn, url, url, lane="bookmark", job_kind="bookmark")


# ---- extract.metadata_from_html / fetch_metadata ----
def test_metadata_from_html_pulls_title_site_desc_favicon():
    meta = extract.metadata_from_html(PAGE, "https://github.com/BurntSushi/ripgrep")
    assert meta.status == "extracted"
    assert meta.title and "ripgrep" in meta.title.lower()
    assert "recursively searches" in (meta.description or "")
    assert meta.favicon_url == "https://github.com/favicon-32.png"  # resolved from <link rel=icon>
    assert meta.body_text and "gitignore" in meta.body_text


def test_favicon_falls_back_to_host_root():
    meta = extract.metadata_from_html("<html><head><title>X</title></head><body><p>hi</p></body></html>",
                                      "https://example.com/some/page")
    assert meta.favicon_url == "https://example.com/favicon.ico"


def test_fetch_metadata_is_failure_tolerant():
    def boom(url):
        raise RuntimeError("network down")

    meta = extract.fetch_metadata("https://example.com/x", fetcher=boom)
    assert meta.status == "failed"
    assert meta.title is None
    assert meta.favicon_url == "https://example.com/favicon.ico"  # still usable


# ---- worker bookmark job ----
def _run_bookmark_job(conn, item_id, *, fetch_metadata, enrich):
    job = store.claim_next_job(conn)
    assert job["kind"] == "bookmark" and job["item_id"] == item_id
    worker.process_job(conn, job, fetch_metadata=fetch_metadata, enrich=enrich)


def test_bookmark_job_stores_metadata_and_ai_tags(conn):
    item_id = _bookmark_item(conn)
    conn.commit()
    meta = extract.metadata_from_html(PAGE, "https://github.com/BurntSushi/ripgrep")
    enriched = EnrichResult(summary="A fast grep.", topics=["CLI", "search"], category="reference",
                            source_type="primary", claims=[])
    _run_bookmark_job(conn, item_id, fetch_metadata=lambda url: meta, enrich=lambda *a, **k: enriched)
    conn.commit()
    bm = store.list_bookmarks(conn)[0]
    assert bm["title"] and "ripgrep" in bm["title"].lower()
    assert bm["source"] == "GitHub"
    assert bm["summary"] == "A fast grep."          # AI summary preferred
    assert bm["favicon_url"].endswith("/favicon-32.png")
    assert set(bm["topics"]) == {"CLI", "search"}   # AI tags applied
    assert bm["extraction_status"] == "extracted" and bm["enrichment_status"] == "done"


def test_bookmark_job_survives_fetch_failure(conn):
    url = "https://unreachable.example/x"
    item_id = _bookmark_item(conn, url)
    conn.commit()
    failed = BookmarkMeta(status="failed", favicon_url="https://unreachable.example/favicon.ico")
    _run_bookmark_job(conn, item_id, fetch_metadata=lambda u: failed,
                      enrich=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not enrich")))
    conn.commit()
    bm = store.list_bookmarks(conn)[0]
    assert bm["title"] == "unreachable.example"     # host fallback
    assert bm["topics"] == []
    assert bm["enrichment_status"] == "failed"


def test_bookmark_job_survives_ai_failure(conn):
    item_id = _bookmark_item(conn)
    conn.commit()
    meta = extract.metadata_from_html(PAGE, "https://github.com/BurntSushi/ripgrep")

    def boom(*a, **k):
        raise RuntimeError("no api key")

    _run_bookmark_job(conn, item_id, fetch_metadata=lambda u: meta, enrich=boom)
    conn.commit()
    bm = store.list_bookmarks(conn)[0]
    assert bm["title"] and "ripgrep" in bm["title"].lower()
    assert bm["summary"] and "recursively searches" in bm["summary"]  # falls back to scraped description
    assert bm["topics"] == []
    assert bm["enrichment_status"] == "failed"


# ---- tags: add / remove with normalization ----
def test_add_and_remove_tag_normalizes(conn):
    item_id = _bookmark_item(conn)
    conn.commit()
    assert store.add_item_tag(conn, item_id, "machine learning") == ["AI"]  # synonym-folded
    assert store.add_item_tag(conn, item_id, "rust") == ["AI", "rust"]
    conn.commit()
    # removing by any casing/synonym of the canonical name works
    assert store.remove_item_tag(conn, item_id, "ai") == ["rust"]
    assert store.add_item_tag(conn, 999, "x") is None  # missing item


# ---- routes ----
def test_capture_bookmark_creates_lane_and_job(client):
    res = client.post("/api/items", json={"url": "https://ex.com/tool", "kind": "bookmark"})
    assert res.status_code == 201
    item = res.json()["item"]
    assert item["lane"] == "bookmark"
    # it does not show up in the Saved lane
    assert client.get("/api/items?view=all").json()["items"] == []
    # and it is listed as a bookmark
    assert {b["id"] for b in client.get("/api/bookmarks").json()["bookmarks"]} == {item["id"]}


def test_capture_rejects_bad_kind(client):
    assert client.post("/api/items", json={"url": "https://ex.com/x", "kind": "nope"}).status_code == 422


def test_tag_routes_flow(client):
    item_id = client.post("/api/items", json={"url": "https://ex.com/t", "kind": "bookmark"}).json()["item"]["id"]
    assert client.post(f"/api/items/{item_id}/tags", json={"name": "CLI"}).json()["topics"] == ["CLI"]
    assert client.request("DELETE", f"/api/items/{item_id}/tags/CLI").json()["topics"] == []
    assert client.post(f"/api/items/{item_id}/tags", json={"name": " "}).status_code == 422
    assert client.post("/api/items/999/tags", json={"name": "x"}).status_code == 404


def test_delete_bookmark_removes_it(client):
    item_id = client.post("/api/items", json={"url": "https://ex.com/d", "kind": "bookmark"}).json()["item"]["id"]
    client.post(f"/api/items/{item_id}/tags", json={"name": "cli"})
    assert client.delete(f"/api/items/{item_id}").status_code == 200
    assert client.get("/api/bookmarks").json()["bookmarks"] == []
