"""Feed fetching, auto-discovery, and parsing.

`parse_feed` and `find_feed_links` are pure (content in, data out) so tests use
fixtures. `resolve_feed` accepts either a feed URL or a site homepage and finds
the feed via <link rel="alternate">.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import feedparser
import httpx
from lxml import html as lxml_html

_UA = "Mozilla/5.0 (compatible; Trove/0.1; +https://trove-app.exe.xyz)"


class FeedError(Exception):
    pass


@dataclass
class Entry:
    title: str | None
    link: str
    summary: str | None
    published: str | None


@dataclass
class ParsedFeed:
    title: str | None
    site_url: str | None
    entries: list[Entry] = field(default_factory=list)


def _text(html_fragment: str | None) -> str | None:
    """Strip HTML from a feed summary for a clean list preview."""
    if not html_fragment:
        return None
    try:
        # Wrap so stray/partial tags in feed summaries are contained, not leaked as text.
        txt = lxml_html.fromstring(f"<div>{html_fragment}</div>").text_content()
    except Exception:  # noqa: BLE001 - summary may be plain text or malformed
        txt = html_fragment
    txt = " ".join(txt.split())
    return txt or None


def parse_feed(content: str | bytes, url: str) -> ParsedFeed | None:
    """Return a ParsedFeed if content is RSS/Atom, else None (e.g. an HTML page)."""
    d = feedparser.parse(content)
    is_feed = bool(getattr(d, "version", "")) or len(d.entries) > 0
    if not is_feed:
        return None
    entries: list[Entry] = []
    for e in d.entries:
        link = e.get("link")
        if not link:
            continue
        summary = e.get("summary")
        if not summary and e.get("content"):
            summary = e["content"][0].get("value")
        entries.append(
            Entry(
                title=e.get("title"),
                link=link,
                summary=_text(summary),
                published=e.get("published") or e.get("updated"),
            )
        )
    return ParsedFeed(title=d.feed.get("title"), site_url=d.feed.get("link"), entries=entries)


def find_feed_links(content: str, base_url: str) -> list[str]:
    """Find RSS/Atom <link rel="alternate"> hrefs on an HTML page."""
    try:
        doc = lxml_html.fromstring(content)
    except Exception:  # noqa: BLE001
        return []
    doc.make_links_absolute(base_url, resolve_base_href=True)
    return doc.xpath(
        '//link[@rel="alternate"][contains(@type,"rss") or contains(@type,"atom") or contains(@type,"xml")]/@href'
    )


def fetch(url: str, *, timeout: float = 20.0) -> str:
    resp = httpx.get(
        url,
        headers={"User-Agent": _UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/html"},
        follow_redirects=True,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.text


def resolve_feed(url: str, *, fetcher=fetch) -> tuple[str, ParsedFeed]:
    """Resolve a feed from a feed URL or a site homepage. Returns (feed_url, parsed)."""
    content = fetcher(url)
    parsed = parse_feed(content, url)
    if parsed is not None:
        return url, parsed
    for link in find_feed_links(content, url):
        try:
            sub = fetcher(link)
        except Exception:  # noqa: BLE001 - try the next candidate
            continue
        p = parse_feed(sub, link)
        if p is not None:
            return link, p
    raise FeedError("Couldn't find a feed at that URL.")
