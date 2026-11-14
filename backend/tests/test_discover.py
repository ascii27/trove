from types import SimpleNamespace

import pytest

from app import db, discover, discoverstore, feedfetch, store, xsource
from app.feedfetch import Entry, ParsedFeed
from app.xsource import XProfile


# ------------------------------------------------------------- helpers ----
def _item(conn, url, *, lane="saved", read="unread", topics=(), title=None):
    item_id = store.create_item(conn, url, url, lane=lane)
    conn.execute("UPDATE items SET read_state = ?, title = ? WHERE id = ?", (read, title, item_id))
    for t in topics:
        store.add_item_tag(conn, item_id, t)
    return item_id


def _parsed(title="A blog", n=3):
    return ParsedFeed(
        title=title,
        site_url="https://a.blog",
        entries=[Entry(title=f"p{i}", link=f"https://a.blog/{i}", summary=None, published=None) for i in range(n)],
    )


def _block(type_, **kw):
    return SimpleNamespace(type=type_, **kw)


class FakeClient:
    """Replays canned responses; records each request's messages."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        return self.responses.pop(0)


PICKS = {
    "blogs": [
        {"name": "Wine Folly", "url": "https://winefolly.com", "feed_url": "", "description": "d",
         "reason": "r", "topics": ["wine"]},
        {"name": "Ghost", "url": "https://ghost.invalid", "feed_url": "", "description": "d",
         "reason": "r", "topics": []},
    ],
    "people": [
        {"handle": "@jancisrobinson", "name": "Jancis Robinson", "description": "d", "reason": "r",
         "topics": ["wine"]},
        {"handle": "not a handle!", "name": "Bad", "description": "d", "reason": "r", "topics": []},
    ],
}


def _resolve(url):
    if "ghost" in url:
        raise feedfetch.FeedError("no feed")
    host = url.split("//")[-1].split("/")[0]
    return f"https://{host}/feed", _parsed(title=host)


# ------------------------------------------------------------- profile ----
def test_profile_weights_topics_by_engagement(conn):
    _item(conn, "https://x.com/a", lane="feed", topics=["Gardening"])
    _item(conn, "https://x.com/b", lane="feed", topics=["Gardening"])
    kept = _item(conn, "https://x.com/c", lane="saved", read="read", topics=["Wine"])
    store.create_highlight(conn, kept, "q", 0, 1)
    store.add_feed(conn, "https://f.example/rss", "https://f.example", "F Blog")
    p = discoverstore.build_profile(conn)
    assert p.topics[0] == "Wine"  # one saved+read+highlighted item beats two passing feed items
    assert "Gardening" in p.topics
    assert p.feeds[0]["title"] == "F Blog"
    assert not p.empty


def test_empty_profile(conn):
    assert discoverstore.build_profile(conn).empty


# -------------------------------------------------------------- prompt ----
def test_prompt_focuses_on_context_and_lists_exclusions():
    p = discoverstore.Profile(topics=["AI"], x_accounts=[{"handle": "karpathy", "name": "Andrej"}])
    text = discover.build_prompt(p, "I'm interested in wine", "x", ["@already"])
    assert "I'm interested in wine" in text
    assert "people to follow on X" in text and "blogs or newsletters" not in text
    assert "@karpathy (Andrej)" in text and "- @already" in text


# --------------------------------------------------------------- loop ----
def test_research_resumes_pause_turn_and_nudges_for_submit():
    client = FakeClient([
        SimpleNamespace(stop_reason="pause_turn", content=[_block("server_tool_use", name="web_search")]),
        SimpleNamespace(stop_reason="end_turn", content=[_block("text", text="Here are some ideas")]),
        SimpleNamespace(stop_reason="tool_use",
                        content=[_block("tool_use", name="submit_suggestions", input=PICKS)]),
    ])
    out = discover.research("prompt", client=client, model="claude-opus-5-5")
    assert out == PICKS
    assert len(client.calls) == 3
    # pause_turn resumes with no extra user turn; end_turn gets exactly one nudge.
    assert [m["role"] for m in client.calls[1]["messages"]] == ["user", "assistant"]
    assert client.calls[2]["messages"][-1]["content"].startswith("Call submit_suggestions")
    tools = client.calls[0]["tools"]
    assert tools[0]["type"] == "web_search_20260209" and tools[1]["name"] == "submit_suggestions"
    assert client.calls[0]["fallbacks"] == "default"


def test_research_gives_up_after_one_nudge():
    talk = SimpleNamespace(stop_reason="end_turn", content=[_block("text", text="hmm")])
    with pytest.raises(discover.DiscoverError):
        discover.research("p", client=FakeClient([talk, talk]), model="claude-opus-5-5")


def test_research_uses_basic_search_on_older_models():
    client = FakeClient([SimpleNamespace(stop_reason="tool_use",
                                         content=[_block("tool_use", name="submit_suggestions", input=PICKS)])])
    discover.research("p", client=client, model="claude-haiku-4-5")
    call = client.calls[0]
    assert call["tools"][0]["type"] == "web_search_20250305"
    assert "fallbacks" not in call and "output_config" not in call


# -------------------------------------------------------- verification ----
def test_verify_blogs_drops_unresolvable_and_followed():
    blogs = PICKS["blogs"] + [{"name": "Mine", "url": "https://mine.example", "feed_url": "",
                               "description": "", "reason": "", "topics": []}]
    out = discover.verify_blogs(blogs, {"https://mine.example/feed"}, resolve=_resolve)
    assert [c.name for c in out] == ["Wine Folly"]
    assert out[0].feed_url == "https://winefolly.com/feed"


def test_verify_blogs_drops_empty_feeds():
    out = discover.verify_blogs(PICKS["blogs"][:1], set(), resolve=lambda u: (u, _parsed(n=0)))
    assert out == []


def test_verify_people_normalizes_and_filters():
    people = PICKS["people"] + [{"handle": "Followed", "name": "F", "description": "", "reason": "", "topics": []}]
    out = discover.verify_people(people, {"followed"})
    assert [(c.handle, c.key) for c in out] == [("jancisrobinson", "jancisrobinson")]


# ----------------------------------------------------------------- run ----
def test_run_stores_verified_suggestions_once(db_path):
    with db.cursor(db_path) as conn:
        r1 = discoverstore.create_run(conn, "wine", "all")
    found = discover.run(r1, db_path=db_path, research_fn=lambda p: PICKS, resolve=_resolve)
    assert found == 2
    with db.cursor(db_path) as conn:
        run = discoverstore.get_run(conn, r1)
        assert run["status"] == "done" and run["found"] == 2
        kinds = [(s["kind"], s["name"]) for s in discoverstore.list_suggestions(conn)]
        assert kinds == [("blog", "Wine Folly"), ("x", "Jancis Robinson")]
        r2 = discoverstore.create_run(conn, None, "all")
    # The same sources again add nothing new, and a second run sees them in its exclusions.
    prompts = []
    assert discover.run(r2, db_path=db_path, research_fn=lambda p: prompts.append(p) or PICKS, resolve=_resolve) == 0
    assert "- @jancisrobinson" in prompts[0] and "- Wine Folly" in prompts[0]


def test_run_records_failure(db_path):
    with db.cursor(db_path) as conn:
        rid = discoverstore.create_run(conn, "wine", "all")

    def boom(prompt):
        raise discover.DiscoverError("Claude declined this request. Try different wording.")

    discover.run(rid, db_path=db_path, research_fn=boom)
    with db.cursor(db_path) as conn:
        run = discoverstore.get_run(conn, rid)
    assert run["status"] == "failed" and "declined" in run["error"]


def test_interrupted_runs_are_failed(conn):
    rid = discoverstore.create_run(conn, None, "all")
    assert discoverstore.fail_interrupted_runs(conn) == 1
    assert discoverstore.get_run(conn, rid)["status"] == "failed"


# -------------------------------------------------------------- routes ----
@pytest.fixture
def sync_discover(monkeypatch):
    """Run discovery inline with canned picks instead of a thread + real Claude."""
    monkeypatch.setattr(discover, "launch",
                        lambda rid: discover.run(rid, research_fn=lambda p: PICKS, resolve=_resolve))


def test_discover_requires_interests_or_context(client):
    res = client.post("/api/discover", json={})
    assert res.status_code == 422 and "interests" in res.json()["detail"]


def test_discover_flow_follow_and_dismiss(client, sync_discover, monkeypatch):
    res = client.post("/api/discover", json={"context": "  I'm interested\nin wine  "})
    assert res.status_code == 202
    assert res.json()["run"]["context"] == "I'm interested in wine"

    state = client.get("/api/discover").json()
    assert state["run"]["status"] == "done"
    blog, person = state["suggestions"]
    assert blog["topics"] == ["wine"] and person["handle"] == "jancisrobinson"
    assert state["x_configured"] is False

    monkeypatch.setattr(feedfetch, "resolve_feed", lambda url, **kw: (url, _parsed("Wine Folly")))
    res = client.post(f"/api/discover/suggestions/{blog['id']}/follow")
    assert res.status_code == 200
    assert res.json()["feed"]["url"] == "https://winefolly.com/feed"
    assert res.json()["suggestion"]["status"] == "followed"

    # X isn't configured: following fails clearly and the suggestion stays.
    res = client.post(f"/api/discover/suggestions/{person['id']}/follow")
    assert res.status_code == 422 and "X isn't connected" in res.json()["detail"]
    assert [s["id"] for s in client.get("/api/discover").json()["suggestions"]] == [person["id"]]

    assert client.post(f"/api/discover/suggestions/{person['id']}/dismiss").status_code == 200
    assert client.get("/api/discover").json()["suggestions"] == []


def test_follow_x_suggestion(client, sync_discover, monkeypatch):
    client.post("/api/discover", json={"context": "wine", "kinds": "x"})
    (person,) = client.get("/api/discover").json()["suggestions"]

    class Src:
        mode = "api"

        def lookup(self, handle):
            return XProfile(handle=handle, user_id="9", name="Jancis Robinson")

        def fetch(self, profile, since_id, max_results):
            return []

    monkeypatch.setattr(xsource, "get_source", lambda: Src())
    res = client.post(f"/api/discover/suggestions/{person['id']}/follow")
    assert res.status_code == 200
    assert res.json()["account"]["handle"] == "jancisrobinson"


def test_discover_rejects_concurrent_runs(client, monkeypatch):
    monkeypatch.setattr(discover, "launch", lambda rid: None)  # stays 'running'
    assert client.post("/api/discover", json={"context": "wine"}).status_code == 202
    res = client.post("/api/discover", json={"context": "cheese"})
    assert res.status_code == 409


def test_hand_followed_suggestions_leave_the_list(client, sync_discover, monkeypatch):
    client.post("/api/discover", json={"context": "wine", "kinds": "blogs"})
    monkeypatch.setattr(feedfetch, "resolve_feed", lambda url, **kw: ("https://winefolly.com/feed", _parsed()))
    client.post("/api/feeds", json={"url": "https://winefolly.com"})
    assert client.get("/api/discover").json()["suggestions"] == []


def test_bad_kinds(client):
    assert client.post("/api/discover", json={"context": "x", "kinds": "tiktok"}).status_code == 422
