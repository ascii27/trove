from app import feedfetch

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Pragmatic Engineer</title>
  <link>https://blog.pragmaticengineer.com</link>
  <item><title>First post</title><link>https://blog.pragmaticengineer.com/first</link>
    <description>&lt;p&gt;A short summary.&lt;/p&gt;</description>
    <pubDate>Mon, 06 Jul 2026 10:00:00 GMT</pubDate></item>
  <item><title>Second post</title><link>https://blog.pragmaticengineer.com/second</link>
    <description>Another summary.</description></item>
</channel></rss>"""

HTML_WITH_FEED = """<!doctype html><html><head>
  <title>Some Blog</title>
  <link rel="alternate" type="application/rss+xml" href="/feed.xml">
</head><body><h1>hi</h1></body></html>"""


def test_parse_feed_extracts_entries_and_cleans_summary():
    parsed = feedfetch.parse_feed(RSS, "https://blog.pragmaticengineer.com/feed")
    assert parsed is not None
    assert parsed.title == "Pragmatic Engineer"
    assert parsed.site_url == "https://blog.pragmaticengineer.com"
    assert len(parsed.entries) == 2
    e0 = parsed.entries[0]
    assert e0.title == "First post"
    assert e0.link == "https://blog.pragmaticengineer.com/first"
    assert e0.summary == "A short summary."  # HTML stripped
    assert e0.published


def test_parse_feed_returns_none_for_html():
    assert feedfetch.parse_feed(HTML_WITH_FEED, "https://example.com") is None


def test_find_feed_links_makes_absolute():
    links = feedfetch.find_feed_links(HTML_WITH_FEED, "https://example.com/")
    assert links == ["https://example.com/feed.xml"]


def test_resolve_feed_direct():
    def fetch(url):
        return RSS

    feed_url, parsed = feedfetch.resolve_feed("https://blog.pragmaticengineer.com/feed", fetcher=fetch)
    assert feed_url == "https://blog.pragmaticengineer.com/feed"
    assert parsed.title == "Pragmatic Engineer"


def test_resolve_feed_autodiscovers_from_html():
    def fetch(url):
        return RSS if url.endswith("/feed.xml") else HTML_WITH_FEED

    feed_url, parsed = feedfetch.resolve_feed("https://example.com/", fetcher=fetch)
    assert feed_url == "https://example.com/feed.xml"
    assert len(parsed.entries) == 2


def test_resolve_feed_raises_when_none_found():
    def fetch(url):
        return "<html><body>no feed here</body></html>"

    try:
        feedfetch.resolve_feed("https://example.com", fetcher=fetch)
        assert False, "expected FeedError"
    except feedfetch.FeedError:
        pass
