import pytest

from app import xsource
from app.xsource import ApiSource, BridgeSource, XError, XProfile


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("@jack", "jack"),
        ("jack", "jack"),
        ("https://x.com/Some_One", "Some_One"),
        ("twitter.com/someone/status/123", "someone"),
        ("  @a_b  ", "a_b"),
    ],
)
def test_normalize_handle(raw, expected):
    assert xsource.normalize_handle(raw) == expected


@pytest.mark.parametrize("raw", ["", "@", "not a handle", "waytoolonghandle_123", "https://x.com/"])
def test_normalize_handle_rejects(raw):
    with pytest.raises(XError):
        xsource.normalize_handle(raw)


def test_post_markdown_expands_links_mentions_and_escapes():
    md, plain = xsource.post_markdown(
        "#buildinpublic shipped v2 &amp; more, thanks @alice!\nDetails: https://t.co/abc. pic https://t.co/img",
        {"https://t.co/abc": "https://example.com/post_one", "https://t.co/img": None},
        ["https://pbs.twimg.com/media/x.jpg"],
    )
    assert md.startswith("\\#buildinpublic")  # a hashtag, not a heading
    assert "&" in md and "&amp;" not in md
    assert "[@alice](https://x.com/alice)" in md
    assert "[example.com/post\\_one](https://example.com/post_one)." in md
    assert "t.co/img" not in md  # media link dropped…
    assert md.endswith("![](https://pbs.twimg.com/media/x.jpg)")  # …image rendered instead
    assert "  \n" in md  # single newline → hard break
    assert "https://example.com/post_one" in plain and "\\" not in plain


def _tweet(id_, text, conv=None, reply_to=None, **extra):
    t = {"id": id_, "text": text, "conversation_id": conv or id_, "created_at": "2026-11-10T14:03:00.000Z"}
    if reply_to:
        t["in_reply_to_user_id"] = reply_to
    t.update(extra)
    return t


def test_posts_from_api_keeps_self_threads_drops_other_replies():
    payload = {
        "data": [
            _tweet("103", "3/ end", conv="101", reply_to="u1"),
            _tweet("102", "2/ middle", conv="101", reply_to="u1"),
            _tweet("101", "1/ a thread"),
            _tweet("104", "@bob agreed", reply_to="u2"),
            _tweet("105", "RT stuff", referenced_tweets=[{"type": "retweeted", "id": "9"}]),
            _tweet(
                "106",
                "short",
                note_tweet={"text": "the full long form text"},
                attachments={"media_keys": ["m1"]},
            ),
        ],
        "includes": {"media": [{"media_key": "m1", "type": "photo", "url": "https://img/1.jpg"}]},
    }
    posts = xsource.posts_from_api(payload, "u1")
    assert [p.id for p in posts] == ["103", "102", "101", "106"]
    long = posts[-1]
    assert "the full long form text" in long.markdown and long.images == ["https://img/1.jpg"]
    assert posts[0].created_at == "2026-11-10T14:03:00"

    threads = xsource.stitch_threads(posts)
    assert [t.root_id for t in threads] == ["101", "106"]
    assert [p.id for p in threads[0].posts] == ["101", "102", "103"]
    assert threads[0].plain.startswith("1/ a thread")


RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<title>Jane Doe / @jane</title><link>https://bridge/jane</link>
<item><title>RT by @jane: someone else</title><link>https://bridge/other/status/1#m</link>
<description>nope</description></item>
<item><title>R to @bob: reply</title><link>https://bridge/jane/status/2#m</link>
<description>reply</description></item>
<item><title>hello</title><link>https://bridge/jane/status/3#m</link>
<pubDate>Tue, 10 Nov 2026 14:03:00 GMT</pubDate>
<description>&lt;p&gt;hello world&lt;br&gt;line two&lt;/p&gt;&lt;img src="https://img/a.jpg"&gt;</description></item>
</channel></rss>"""


def test_posts_from_feed():
    posts = xsource.posts_from_feed(RSS)
    assert [p.id for p in posts] == ["3"]
    p = posts[0]
    assert "hello world  \nline two" in p.markdown
    assert p.images == ["https://img/a.jpg"]
    assert p.created_at == "2026-11-10T14:03:00"


class _Resp:
    def __init__(self, status, data=None, text=""):
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_api_source_lookup_and_fetch():
    calls = []

    def http_get(url, headers=None, params=None):
        calls.append((url, headers, params))
        if "/users/by/username/" in url:
            return _Resp(200, {"data": {"id": "u1", "username": "Jane", "name": "Jane D", "profile_image_url": "a.png"}})
        return _Resp(200, {"data": [_tweet("5", "hi")]})

    src = ApiSource("tok", base="https://api.test/2", http_get=http_get)
    prof = src.lookup("jane")
    assert (prof.handle, prof.user_id, prof.name) == ("Jane", "u1", "Jane D")
    posts = src.fetch(prof, "4", 50)
    assert [p.id for p in posts] == ["5"]
    url, headers, params = calls[-1]
    assert url == "https://api.test/2/users/u1/tweets"
    assert headers["Authorization"] == "Bearer tok"
    assert params["since_id"] == "4" and params["exclude"] == "retweets"


def test_api_source_errors_are_user_facing():
    src = ApiSource("tok", base="https://api.test/2", http_get=lambda *a, **k: _Resp(401))
    with pytest.raises(XError, match="token"):
        src.lookup("jane")
    src = ApiSource("tok", base="https://api.test/2", http_get=lambda *a, **k: _Resp(200, {"errors": []}))
    with pytest.raises(XError, match="Couldn't find"):
        src.lookup("ghost")


def test_bridge_source_filters_since_id():
    src = BridgeSource("https://bridge/{handle}/rss", http_get=lambda url, **k: _Resp(200, text=RSS))
    assert src.lookup("jane").name == "Jane Doe"
    assert [p.id for p in src.fetch(XProfile("jane"), None, 50)] == ["3"]
    assert src.fetch(XProfile("jane"), "3", 50) == []


def test_get_source_prefers_api(monkeypatch):
    monkeypatch.delenv("TROVE_X_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("TROVE_X_RSS_TEMPLATE", raising=False)
    assert xsource.get_source() is None
    monkeypatch.setenv("TROVE_X_RSS_TEMPLATE", "https://b/{handle}")
    assert xsource.get_source().mode == "bridge"
    monkeypatch.setenv("TROVE_X_BEARER_TOKEN", "t")
    assert xsource.get_source().mode == "api"
