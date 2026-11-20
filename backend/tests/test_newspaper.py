from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import db, feedfetch, newspaper, paperstore, store


# ------------------------------------------------------------- helpers ----
def _feed_item(conn, n, *, feed_id=None, hours_ago=2, read="unread", image=None, lane="feed"):
    url = f"https://news.example/{lane}/{n}"
    cur = conn.execute(
        "INSERT INTO items (url_canonical, original_url, lane, feed_id, title, source, summary, content_text, "
        "image_url, read_state, extraction_status, enrichment_status, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted', 'deferred', strftime('%Y-%m-%dT%H:%M:%S', 'now', ?))",
        (url, url, lane, feed_id, f"Story {n}", f"Source {feed_id or n}", f"Summary of story {n}.",
         f"Post text {n}" if lane == "x" else None, image, read, f"-{hours_ago} hours"),
    )
    return cur.lastrowid


def _feed(conn, n):
    return store.add_feed(conn, f"https://f{n}.example/rss", f"https://f{n}.example", f"Feed {n}")


def _resp(data, stop="end_turn"):
    import json

    return SimpleNamespace(stop_reason=stop, usage=SimpleNamespace(input_tokens=9000, output_tokens=2500),
                           content=[SimpleNamespace(type="text", text=json.dumps(data))])


class FakeClient:
    def __init__(self, data):
        self.data, self.calls = data, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        return _resp(self.data)


def _raw(lead, sections, x=(), shelf=()):
    st = lambda i: {"id": i, "headline": f"Headline {i}", "summary": f"Sum {i}."}  # noqa: E731
    return {
        "editors_note": "Today: things.",
        "lead": st(lead),
        "sections": [{"name": n, "stories": [st(i) for i in ids]} for n, ids in sections],
        "from_x": [{"id": i, "summary": f"Post {i}"} for i in x],
        "from_shelf": [st(i) for i in shelf],
    }


# ---------------------------------------------------------- candidates ----
def test_candidates_are_recent_unread_and_never_printed(conn):
    f = _feed(conn, 1)
    fresh = _feed_item(conn, 1, feed_id=f)
    _feed_item(conn, 2, feed_id=f, hours_ago=100)  # before the window
    _feed_item(conn, 3, feed_id=f, read="read")  # already read
    printed = _feed_item(conn, 4, feed_id=f)
    post = _feed_item(conn, 5, lane="x")
    eid = paperstore.create_edition(conn, "manual", "2000-01-01 00:00:00")
    paperstore.finish_edition(conn, eid, {}, [printed])
    since = conn.execute("SELECT datetime('now', '-2 days') AS w").fetchone()["w"]
    got = {c.id: c for c in paperstore.candidates(conn, since)}
    assert set(got) == {fresh, post}
    assert got[post].text == "Post text 5"


def test_one_feed_cant_crowd_out_the_rest(conn):
    big, small = _feed(conn, 1), _feed(conn, 2)
    for n in range(12):
        _feed_item(conn, n, feed_id=big)
    _feed_item(conn, 99, feed_id=small, hours_ago=5)
    since = conn.execute("SELECT datetime('now', '-2 days') AS w").fetchone()["w"]
    cands = paperstore.candidates(conn, since, per_feed=8)
    assert sum(c.feed_id == big for c in cands) == 8
    assert any(c.feed_id == small for c in cands)


def test_window_is_since_last_edition_capped_at_a_week(conn):
    first = paperstore.window_start(conn)
    assert first == conn.execute("SELECT datetime('now', '-3 days') AS w").fetchone()["w"]
    eid = paperstore.create_edition(conn, "manual", first)
    conn.execute("UPDATE editions SET created_at = datetime('now', '-1 day') WHERE id = ?", (eid,))
    paperstore.finish_edition(conn, eid, {}, [])
    assert paperstore.window_start(conn) == conn.execute("SELECT datetime('now', '-1 day') AS w").fetchone()["w"]
    conn.execute("UPDATE editions SET created_at = datetime('now', '-30 days')")
    assert paperstore.window_start(conn) == conn.execute("SELECT datetime('now', '-7 days') AS w").fetchone()["w"]


# ------------------------------------------------------------ assemble ----
def _cands(conn):
    f = _feed(conn, 1)
    ids = [_feed_item(conn, n, feed_id=f) for n in range(1, 6)]
    x = _feed_item(conn, 50, lane="x")
    saved = _feed_item(conn, 60, lane="saved")
    since = conn.execute("SELECT datetime('now', '-2 days') AS w").fetchone()["w"]
    return paperstore.candidates(conn, since), ids, x, saved


def test_assemble_drops_unknown_repeated_and_wrong_lane_ids(conn):
    cands, ids, x, saved = _cands(conn)
    raw = _raw(ids[0], [("AI", [ids[1], ids[1], 9999, x]), ("Work", [ids[2]])], x=[x, ids[3]], shelf=[saved])
    layout, printed = newspaper.assemble(raw, cands)
    assert layout["lead"]["item_id"] == ids[0] and layout["lead"]["headline"] == f"Headline {ids[0]}"
    assert [[s["item_id"] for s in sec["stories"]] for sec in layout["sections"]] == [[ids[1]], [ids[2]]]
    assert [s["item_id"] for s in layout["from_x"]] == [x]
    assert [s["item_id"] for s in layout["from_shelf"]] == [saved]
    assert sorted(printed) == sorted([ids[0], ids[1], ids[2], x, saved])


def test_assemble_promotes_a_lead_when_the_editors_is_bad(conn):
    cands, ids, x, _ = _cands(conn)
    layout, _ = newspaper.assemble(_raw(x, [("AI", [ids[1]]), ("Work", [ids[2]])]), cands)
    assert layout["lead"]["item_id"] == ids[1]
    assert [sec["name"] for sec in layout["sections"]] == ["Work"]  # emptied section removed


def test_images_only_on_featured_stories(conn):
    cands, ids, _, _ = _cands(conn)
    layout, _ = newspaper.assemble(_raw(ids[0], [("AI", [ids[1], ids[2]])]), cands)
    layout["sections"][0]["stories"][1]["image"] = "https://img/kept-off.jpg"
    found = newspaper.fill_images(layout, fetch=lambda url: f"{url}/og.jpg")
    assert layout["lead"]["image"].endswith("/og.jpg")
    assert layout["sections"][0]["stories"][0]["image"].endswith("/og.jpg")
    assert layout["sections"][0]["stories"][1]["image"] is None
    assert set(found) == {ids[0], ids[1]}


# ----------------------------------------------------------------- run ----
def test_run_prints_an_edition_and_never_repeats(db_path):
    with db.cursor(db_path) as conn:
        cands, ids, x, _ = _cands(conn)
        eid = newspaper.start(conn, "manual")
    client = FakeClient(_raw(ids[0], [("AI", [ids[1], ids[2]])], x=[x]))
    ok = newspaper.run(eid, db_path=db_path, edit_fn=lambda c: newspaper.edit(c, client=client, model="claude-haiku-5-5"),
                       fetch_image=lambda url: None)
    assert ok
    assert client.calls[0]["output_config"]["effort"] == "low"
    with db.cursor(db_path) as conn:
        ed = paperstore.get_edition(conn, eid)
        assert ed["status"] == "done" and ed["number"] == 1 and ed["story_count"] == 4
        assert ed["input_tokens"] == 9000
        # A second edition only sees what wasn't printed.
        left = {c.id for c in paperstore.candidates(conn, "2000-01-01 00:00:00")}
    assert left.isdisjoint({ids[0], ids[1], ids[2], x})
    assert {ids[3], ids[4]} <= left


def test_run_refuses_a_thin_paper(db_path):
    with db.cursor(db_path) as conn:
        f = _feed(conn, 1)
        _feed_item(conn, 1, feed_id=f)
        eid = newspaper.start(conn, "manual")
    assert not newspaper.run(eid, db_path=db_path, edit_fn=lambda c: pytest.fail("no call for a thin paper"))
    with db.cursor(db_path) as conn:
        ed = paperstore.get_edition(conn, eid)
    assert ed["status"] == "failed" and "Not enough new stories" in ed["error"]


# ------------------------------------------------------------ schedule ----
def _settings(**over):
    return {"schedule": "daily", "hour": 6, "tz": "America/Los_Angeles", "last_scheduled": None, **over}


def _utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_due_respects_local_time_and_days():
    # 2026-11-20 is a Friday. 13:49Z = 05:49 in Los Angeles: within 10 minutes of 6am.
    assert newspaper.due(_settings(), _utc("2026-11-20T13:49:00")) is None
    assert newspaper.due(_settings(), _utc("2026-11-20T13:51:00")) == "2026-11-20"
    assert newspaper.due(_settings(last_scheduled="2026-11-20"), _utc("2026-11-20T20:00:00")) is None
    assert newspaper.due(_settings(schedule="weekends"), _utc("2026-11-20T20:00:00")) is None
    assert newspaper.due(_settings(schedule="weekends"), _utc("2026-11-21T20:00:00")) == "2026-11-21"
    assert newspaper.due(_settings(schedule="weekdays"), _utc("2026-11-21T20:00:00")) is None
    assert newspaper.due(_settings(schedule="off"), _utc("2026-11-20T20:00:00")) is None


def test_maybe_print_starts_once_per_day(conn):
    paperstore.save_settings(conn, "daily", 6, "UTC")
    launched = []
    now = _utc("2026-11-20T07:00:00")
    assert newspaper.maybe_print(conn, now, launch_fn=launched.append) is not None
    paperstore.fail_edition(conn, launched[0], "x")
    assert newspaper.maybe_print(conn, now, launch_fn=launched.append) is None
    assert len(launched) == 1
    assert paperstore.get_edition(conn, launched[0])["trigger"] == "schedule"


# --------------------------------------------------------------- feeds ----
def test_feed_entry_images():
    rss = """<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
      <title>T</title><link>https://t.example</link>
      <item><title>A</title><link>https://t.example/a</link><media:thumbnail url="https://img/a.jpg"/></item>
      <item><title>B</title><link>https://t.example/b</link><enclosure url="https://img/b.png" type="image/png"/></item>
      <item><title>C</title><link>https://t.example/c</link>
        <description><![CDATA[<p><img src="https://img/c.jpg"> hello</p>]]></description></item>
      <item><title>D</title><link>https://t.example/d</link><description>plain</description></item>
    </channel></rss>"""
    entries = feedfetch.parse_feed(rss, "https://t.example/rss").entries
    assert [e.image for e in entries] == ["https://img/a.jpg", "https://img/b.png", "https://img/c.jpg", None]


# -------------------------------------------------------------- routes ----
def test_newspaper_routes(client, monkeypatch):
    launched = []
    monkeypatch.setattr(newspaper, "launch", launched.append)
    state = client.get("/api/newspaper").json()
    assert state["editions"] == [] and state["latest_id"] is None
    assert state["settings"]["schedule"] == "off"

    res = client.post("/api/newspaper")
    assert res.status_code == 202 and res.json()["running"]["id"] == launched[0]
    assert client.post("/api/newspaper").status_code == 409

    assert client.get("/api/newspaper/editions/999").status_code == 404
    ed = client.get(f"/api/newspaper/editions/{launched[0]}").json()["edition"]
    assert ed["status"] == "running"


def test_settings_validation_and_no_instant_print(client, monkeypatch):
    assert client.put("/api/newspaper/settings", json={"schedule": "hourly"}).status_code == 422
    assert client.put("/api/newspaper/settings", json={"schedule": "daily", "tz": "Mars/Base"}).status_code == 422
    # Switching on after today's print time waits for tomorrow rather than printing now.
    now = datetime.now(timezone.utc)
    hour = max(0, now.hour - 1)
    res = client.put("/api/newspaper/settings", json={"schedule": "daily", "hour": hour, "tz": "UTC"})
    s = res.json()["settings"]
    assert s["schedule"] == "daily" and s["hour"] == hour
    if now.hour >= 1:
        assert s["last_scheduled"] == now.date().isoformat()


def test_page_image_reads_og_image():
    from app import extract

    html = ('<html><head><meta property="og:image" content="https://img.example/hero.jpg"><title>T</title></head>'
            "<body><article><p>" + "Words here. " * 80 + "</p></article></body></html>")
    assert extract.page_image(html, "https://e.example/a") == "https://img.example/hero.jpg"
    assert extract.extract_from_html(html, "https://e.example/a").image == "https://img.example/hero.jpg"


def test_schedule_check_leaves_no_open_transaction(db_path):
    """Regression: the worker's check wrote a settings row without committing, which held
    SQLite's write lock on its long-lived connection and 500'd every other writer."""
    worker_conn = db.connect(db_path)
    other = db.connect(db_path)
    other.execute("PRAGMA busy_timeout=200")
    try:
        assert newspaper.maybe_print(worker_conn, _utc("2026-11-20T07:00:00"), launch_fn=lambda e: None) is None
        assert not worker_conn.in_transaction
        other.execute("UPDATE newspaper_settings SET hour = 7 WHERE id = 1")  # would raise "database is locked"
        other.commit()
    finally:
        worker_conn.close()
        other.close()


def test_worker_maintenance_never_leaves_a_transaction_open(db_path, monkeypatch):
    from app import worker

    monkeypatch.setattr(worker.config, "anthropic_api_key", lambda: "k")
    monkeypatch.setattr(worker, "theme_posts", lambda conn: conn.execute("UPDATE items SET theme = theme"))
    w = worker.Worker(db_path=db_path)
    conn = db.connect(db_path)
    try:
        w._maintenance(conn)
        assert not conn.in_transaction
    finally:
        conn.close()
