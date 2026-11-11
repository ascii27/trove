import json
from types import SimpleNamespace

import pytest

from app import xsource, xstore, xthemes
from app.worker import poll_x_account, theme_posts
from app.xsource import XPost, XProfile


def _post(id_, text, conv=None, when="2026-11-10T14:00:00"):
    md, plain = xsource.post_markdown(text, {}, [])
    return XPost(id=id_, conversation_id=conv or id_, created_at=when, markdown=md, plain=plain)


class FakeSource:
    mode = "api"

    def __init__(self, posts=None, profile=None):
        self.posts = posts or []
        self.profile = profile or XProfile(handle="jane", user_id="u1", name="Jane Doe", avatar_url="a.png")
        self.since = []

    def lookup(self, handle):
        if handle == "ghost":
            raise xsource.XError("Couldn't find @ghost on X.")
        return self.profile

    def fetch(self, profile, since_id, max_results):
        self.since.append(since_id)
        return [p for p in self.posts if since_id is None or int(p.id) > int(since_id)]


def _account(conn, handle="jane"):
    aid = xstore.add_account(conn, XProfile(handle=handle, user_id="u1", name="Jane Doe"))
    conn.commit()
    return xstore.get_account(conn, aid)


def test_poll_stitches_threads_and_tracks_since_id(conn):
    acct = _account(conn)
    src = FakeSource([_post("10", "1/ thread start"), _post("11", "2/ more", conv="10"), _post("12", "solo")])
    assert poll_x_account(conn, acct, src) == {"created": 2, "appended": 0}
    posts = xstore.list_posts(conn)
    assert len(posts) == 2
    thread = next(p for p in posts if p["post_id"] == "10")
    assert thread["thread_len"] == 2
    assert thread["content_text"].index("thread start") < thread["content_text"].index("more")
    assert thread["title"] == "1/ thread start"
    assert thread["original_url"] == "https://x.com/jane/status/10"
    assert thread["handle"] == "jane" and thread["read_state"] == "unread"

    # Next poll only asks for newer posts; a late thread part is appended.
    xstore.mark_posts(conn, [thread["id"]], "read")
    src.posts.append(_post("13", "3/ the end", conv="10"))
    acct = xstore.get_account(conn, acct["id"])
    assert poll_x_account(conn, acct, src) == {"created": 0, "appended": 1}
    assert src.since[-1] == "12"
    thread = next(p for p in xstore.list_posts(conn) if p["post_id"] == "10")
    assert thread["thread_len"] == 3 and thread["content_text"].endswith("3/ the end")
    assert thread["read_state"] == "unread"  # new parts resurface it


def test_poll_records_errors(conn):
    acct = _account(conn)

    class Boom(FakeSource):
        def fetch(self, *a):
            raise xsource.XError("X rate limit reached.")

    out = poll_x_account(conn, acct, Boom())
    assert out["error"] == "X rate limit reached."
    assert xstore.get_account(conn, acct["id"])["last_error"] == "X rate limit reached."


def test_theme_posts_batches_and_reuses_existing(conn):
    acct = _account(conn)
    poll_x_account(conn, acct, FakeSource([_post("1", "agents are neat"), _post("2", "raised a seed"), _post("3", "lunch")]))
    ids = {p["title"]: p["id"] for p in xstore.list_posts(conn)}
    seen = {}

    def classify(inputs, existing):
        seen["n"] = len(inputs)
        return {ids["agents are neat"]: "AI agents", ids["raised a seed"]: "Fundraising"}  # skips one

    assert theme_posts(conn, classify=classify) == 3
    assert seen["n"] == 3
    themes = {p["title"]: p["theme"] for p in xstore.list_posts(conn)}
    assert themes == {"agents are neat": "AI agents", "raised a seed": "Fundraising", "lunch": "Misc"}
    assert theme_posts(conn, classify=classify) == 0  # nothing left to theme
    assert xstore.existing_themes(conn)[0] in {"AI agents", "Fundraising", "Misc"}


def test_classify_parses_and_folds_case():
    payload = {"assignments": [{"id": 1, "theme": "ai agents"}, {"id": 2, "theme": " new  theme. "}, {"id": 99, "theme": "x"}]}
    client = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **kw: SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))])
        )
    )
    out = xthemes.classify(
        [xthemes.ThemeInput(1, "a", "t"), xthemes.ThemeInput(2, "b", "u")], ["AI agents"], client=client, model="m"
    )
    assert out == {1: "AI agents", 2: "New theme"}


def test_age_posts_spares_tagged_and_highlighted(conn):
    acct = _account(conn)
    old = "2020-01-01T00:00:00"
    poll_x_account(conn, acct, FakeSource([_post("1", "a", when=old), _post("2", "b", when=old), _post("3", "c", when=old), _post("4", "d")]))
    by = {p["title"]: p["id"] for p in xstore.list_posts(conn)}
    from app import store

    store.add_item_tag(conn, by["b"], "keep")
    store.create_highlight(conn, by["c"], "c", 0, 1)
    assert xstore.age_posts(conn, 30) == 1
    assert sorted(p["title"] for p in xstore.list_posts(conn)) == ["b", "c", "d"]


def test_unfollow_keeps_posts_you_invested_in(conn):
    acct = _account(conn)
    poll_x_account(conn, acct, FakeSource([_post("1", "plain"), _post("2", "tagged")]))
    by = {p["title"]: p["id"] for p in xstore.list_posts(conn)}
    from app import store

    store.add_item_tag(conn, by["tagged"], "ideas")
    assert xstore.delete_account(conn, acct["id"])
    posts = xstore.list_posts(conn)
    assert [p["title"] for p in posts] == ["tagged"]
    assert posts[0]["handle"] == "jane" and posts[0]["topics"] == ["ideas"]


# ---------------------------------------------------------------- routes ----
@pytest.fixture
def fake_source(monkeypatch):
    src = FakeSource([_post("10", "hello #world"), _post("11", "second", when="2026-11-11T09:00:00")])
    monkeypatch.setattr(xsource, "get_source", lambda: src)
    return src


def test_status_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("TROVE_X_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("TROVE_X_RSS_TEMPLATE", raising=False)
    body = client.get("/api/x/status").json()
    assert body["configured"] is False and "TROVE_X_BEARER_TOKEN" in body["message"]
    r = client.post("/api/x/accounts", json={"handle": "@jane"})
    assert r.status_code == 422


def test_follow_list_tag_highlight_and_read(client, fake_source):
    r = client.post("/api/x/accounts", json={"handle": "https://x.com/jane"})
    assert r.status_code == 201
    account = r.json()["account"]
    assert account["handle"] == "jane" and account["unread_count"] == 2
    assert client.post("/api/x/accounts", json={"handle": "@Jane"}).json()["duplicate"] is True

    body = client.get("/api/x/posts").json()
    posts = body["posts"]
    assert [p["title"] for p in posts] == ["second", "hello #world"]  # newest first
    assert body["unread_count"] == 2
    pid = posts[0]["id"]

    # Tags + highlights reuse the generic item endpoints.
    assert client.post(f"/api/items/{pid}/tags", json={"name": "ideas"}).json()["topics"] == ["ideas"]
    client.post(f"/api/items/{pid}/highlights", json={"quote": "sec", "start": 0, "end": 3})
    post = client.get(f"/api/x/posts?account_id={account['id']}").json()["posts"][0]
    assert post["topics"] == ["ideas"] and post["highlights"][0]["quote"] == "sec"
    assert client.get("/api/highlights").json()["highlights"][0]["title"] == "second"

    r = client.post("/api/x/posts/read", json={"ids": [p["id"] for p in posts]})
    assert r.json() == {"updated": 2, "unread_count": 0}
    assert client.get("/api/x/posts?unread=true").json()["posts"] == []

    # Manual theme override; X posts never leak into the Saved lane.
    t = client.put(f"/api/x/posts/{pid}/theme", json={"theme": "Writing"}).json()["post"]
    assert t["theme"] == "Writing"
    assert client.get("/api/items?view=all").json()["items"] == []

    assert client.delete(f"/api/x/accounts/{account['id']}").json() == {"deleted": True}
    assert [p["title"] for p in client.get("/api/x/posts").json()["posts"]] == ["second"]


def test_follow_unknown_handle(client, fake_source):
    r = client.post("/api/x/accounts", json={"handle": "ghost"})
    assert r.status_code == 422 and "ghost" in r.json()["detail"]
    assert client.post("/api/x/accounts", json={"handle": "no spaces"}).status_code == 422
