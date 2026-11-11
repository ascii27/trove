"""Pulling posts from X (Twitter) for followed accounts.

Two interchangeable sources, chosen by config:

- `ApiSource` — the official X API v2 with a bearer token. Gives conversation
  ids (so an author's self-thread reads as one blog-style post), full long-form
  text (`note_tweet`), expanded links, and images.
- `BridgeSource` — any RSS bridge you run (RSSHub, Nitter, …) via a URL
  template containing `{handle}`. No thread info; each post stands alone.

The parsing is pure (`posts_from_api`, `posts_from_feed`, `stitch_threads`,
`post_markdown`) so tests use fixtures. Network calls go through an injectable
`http_get`, mirroring feedfetch/extract.
"""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from . import config

_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_TOKEN_RE = re.compile(r"(https?://[^\s<>\"]+|(?<![\w@])@[A-Za-z0-9_]{1,15})")
_STATUS_RE = re.compile(r"/status(?:es)?/(\d+)")


class XError(Exception):
    """A user-facing problem (bad handle, not configured, account not found)."""


@dataclass
class XProfile:
    handle: str
    user_id: str | None = None
    name: str | None = None
    avatar_url: str | None = None


@dataclass
class XPost:
    id: str
    conversation_id: str
    created_at: str | None  # ISO 8601 UTC, "%Y-%m-%dT%H:%M:%S"
    markdown: str
    plain: str  # unformatted text, for titles and theme classification
    images: list[str] = field(default_factory=list)


@dataclass
class XThread:
    """One stored item: a standalone post, or an author's self-thread stitched together."""

    root_id: str
    posts: list[XPost]

    @property
    def created_at(self) -> str | None:
        return self.posts[0].created_at

    @property
    def markdown(self) -> str:
        return "\n\n".join(p.markdown for p in self.posts)

    @property
    def plain(self) -> str:
        return "\n\n".join(p.plain for p in self.posts)


# ------------------------------------------------------------ handles ----
def normalize_handle(raw: str) -> str:
    """Accept '@name', 'name', or an x.com / twitter.com profile URL."""
    s = (raw or "").strip()
    if "/" in s:
        parts = [p for p in urlsplit(s if "://" in s else f"https://{s}").path.split("/") if p]
        s = parts[0] if parts else ""
    s = s.lstrip("@")
    if not _HANDLE_RE.match(s):
        raise XError("Enter an X handle like @username or a profile link.")
    return s


def post_url(handle: str, post_id: str) -> str:
    return f"https://x.com/{handle}/status/{post_id}"


# ---------------------------------------------------------- formatting ----
_MD_INLINE = re.compile(r"([\\`*_\[\]<>|~])")
_MD_LINE_START = re.compile(r"^(\s*)([#>+\-=]|\d+[.)])", re.MULTILINE)


def _escape(text: str) -> str:
    """Make post text render literally (a leading '#' is a hashtag, not a heading)."""
    text = _MD_INLINE.sub(r"\\\1", text)
    return _MD_LINE_START.sub(lambda m: m.group(1) + "\\" + m.group(2), text)


def post_markdown(text: str, urls: dict[str, str | None], images: list[str]) -> tuple[str, str]:
    """Turn raw post text into (markdown, plain).

    `urls` maps t.co short links to their expanded URL, or None to drop the link
    (media links — the images are rendered below the text instead). Mentions
    become profile links; single newlines become hard line breaks.
    """
    text = html_mod.unescape(text or "")
    md_parts: list[str] = []
    plain_parts: list[str] = []
    for i, tok in enumerate(_TOKEN_RE.split(text)):
        if i % 2 == 0:
            md_parts.append(_escape(tok))
            plain_parts.append(tok)
            continue
        if tok.startswith("@"):
            md_parts.append(f"[{_escape(tok)}](https://x.com/{tok[1:]})")
            plain_parts.append(tok)
            continue
        tail = ""
        while tok and tok[-1] in ".,;:!?)'\"":
            tok, tail = tok[:-1], tok[-1] + tail
        if tok in urls:
            target = urls[tok]
            if target is not None:
                display = re.sub(r"^https?://(www\.)?", "", target)
                display = display if len(display) <= 40 else display[:39] + "…"
                md_parts.append(f"[{_escape(display)}]({target})")
                plain_parts.append(target)
        else:
            md_parts.append(f"<{tok}>")
            plain_parts.append(tok)
        md_parts.append(_escape(tail))
        plain_parts.append(tail)
    md = "".join(md_parts).strip()
    plain = re.sub(r"[ \t]+", " ", "".join(plain_parts)).strip()
    # Paragraphs stay paragraphs; single newlines are hard breaks (two trailing spaces).
    md = "\n\n".join(
        "  \n".join(line.rstrip() for line in para.split("\n")) for para in re.split(r"\n\s*\n", md)
    )
    md += "".join(f"\n\n![]({src})" for src in images)
    return md, plain


def _iso(ts: str | None) -> str | None:
    """'2026-11-10T14:03:00.000Z' → '2026-11-10T14:03:00' (UTC, sortable)."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# -------------------------------------------------------------- X API v2 ----
def posts_from_api(payload: dict, user_id: str) -> list[XPost]:
    """Parse a /2/users/:id/tweets response. Keeps the author's own posts and
    their replies to themselves (thread continuations); drops replies to others."""
    media = {m["media_key"]: m for m in (payload.get("includes") or {}).get("media", [])}
    out: list[XPost] = []
    for t in payload.get("data") or []:
        reply_to = t.get("in_reply_to_user_id")
        if reply_to and reply_to != user_id:
            continue
        if any(r.get("type") == "retweeted" for r in t.get("referenced_tweets") or []):
            continue
        note = t.get("note_tweet") or {}
        text = note.get("text") or t.get("text") or ""
        entities = note.get("entities") or t.get("entities") or {}
        urls: dict[str, str | None] = {}
        for u in entities.get("urls") or []:
            short = u.get("url")
            if not short:
                continue
            urls[short] = None if u.get("media_key") else (u.get("unwound_url") or u.get("expanded_url") or short)
        # Plain tweet entities can carry media links even when note_tweet is used.
        for u in (t.get("entities") or {}).get("urls") or []:
            if u.get("media_key") and u.get("url"):
                urls[u["url"]] = None
        images = []
        for key in (t.get("attachments") or {}).get("media_keys") or []:
            m = media.get(key) or {}
            src = m.get("url") or m.get("preview_image_url")
            if src:
                images.append(src)
        md, plain = post_markdown(text, urls, images)
        out.append(
            XPost(
                id=str(t["id"]),
                conversation_id=str(t.get("conversation_id") or t["id"]),
                created_at=_iso(t.get("created_at")),
                markdown=md,
                plain=plain,
                images=images,
            )
        )
    return out


# ---------------------------------------------------------- RSS bridge ----
def posts_from_feed(content: str | bytes) -> list[XPost]:
    """Parse an RSS bridge feed for one account. Retweets ('RT …') and replies to
    others ('R to @…') are dropped; each remaining entry is a standalone post."""
    import time

    import feedparser
    from lxml import html as lxml_html

    d = feedparser.parse(content)
    out: list[XPost] = []
    for e in d.entries:
        title = (e.get("title") or "").strip()
        if title.startswith("RT ") or title.startswith("R to @"):
            continue
        link = e.get("link") or ""
        m = _STATUS_RE.search(link) or _STATUS_RE.search(e.get("id") or "")
        if not m:
            continue
        body = e.get("summary") or (e["content"][0].get("value") if e.get("content") else "") or title
        images: list[str] = []
        urls: dict[str, str | None] = {}
        try:
            doc = lxml_html.fromstring(f"<div>{body}</div>")
            images = [src for src in doc.xpath("//img/@src") if src]
            for img in doc.xpath("//img"):
                img.drop_tree()
            for br in doc.xpath("//br"):
                br.tail = "\n" + (br.tail or "")
            for p in doc.xpath("//p"):
                p.tail = "\n\n" + (p.tail or "")
            text = doc.text_content()
        except Exception:  # noqa: BLE001 - plain text or malformed
            text = body
        parsed = e.get("published_parsed") or e.get("updated_parsed")
        md, plain = post_markdown(text.strip(), urls, images)
        pid = m.group(1)
        out.append(
            XPost(
                id=pid,
                conversation_id=pid,
                created_at=time.strftime("%Y-%m-%dT%H:%M:%S", parsed) if parsed else None,
                markdown=md,
                plain=plain,
                images=images,
            )
        )
    return out


# -------------------------------------------------------------- threads ----
def stitch_threads(posts: list[XPost]) -> list[XThread]:
    """Group posts by conversation, oldest-first within each thread."""
    groups: dict[str, list[XPost]] = {}
    for p in posts:
        groups.setdefault(p.conversation_id, []).append(p)
    threads = []
    for root, ps in groups.items():
        ps.sort(key=lambda p: int(p.id) if p.id.isdigit() else 0)
        threads.append(XThread(root_id=root, posts=ps))
    threads.sort(key=lambda t: int(t.root_id) if t.root_id.isdigit() else 0)
    return threads


# -------------------------------------------------------------- sources ----
def _http_get(url: str, *, headers: dict | None = None, params: dict | None = None) -> httpx.Response:
    return httpx.get(url, headers=headers, params=params, follow_redirects=True, timeout=20.0)


class ApiSource:
    mode = "api"

    def __init__(self, token: str, *, base: str | None = None, http_get=_http_get):
        self.token = token
        self.base = (base or config.x_api_base()).rstrip("/")
        self.http_get = http_get

    def _get(self, path: str, params: dict) -> dict:
        resp = self.http_get(
            f"{self.base}{path}", headers={"Authorization": f"Bearer {self.token}"}, params=params
        )
        if resp.status_code == 401 or resp.status_code == 403:
            raise XError("X rejected the API token. Check TROVE_X_BEARER_TOKEN.")
        if resp.status_code == 429:
            raise XError("X rate limit reached. Trove will try again on the next poll.")
        resp.raise_for_status()
        return resp.json()

    def lookup(self, handle: str) -> XProfile:
        data = self._get(f"/users/by/username/{handle}", {"user.fields": "profile_image_url,name"})
        user = data.get("data")
        if not user:
            raise XError(f"Couldn't find @{handle} on X.")
        return XProfile(
            handle=user.get("username") or handle,
            user_id=str(user["id"]),
            name=user.get("name"),
            avatar_url=user.get("profile_image_url"),
        )

    def fetch(self, profile: XProfile, since_id: str | None, max_results: int) -> list[XPost]:
        if not profile.user_id:
            profile = self.lookup(profile.handle)
        params = {
            "max_results": max_results,
            "exclude": "retweets",
            "tweet.fields": "created_at,conversation_id,in_reply_to_user_id,entities,note_tweet,attachments,referenced_tweets",
            "expansions": "attachments.media_keys",
            "media.fields": "url,preview_image_url,type",
        }
        if since_id:
            params["since_id"] = since_id
        return posts_from_api(self._get(f"/users/{profile.user_id}/tweets", params), profile.user_id)


class BridgeSource:
    mode = "bridge"

    def __init__(self, template: str, *, http_get=_http_get):
        self.template = template
        self.http_get = http_get

    def _feed(self, handle: str) -> str:
        resp = self.http_get(self.template.replace("{handle}", handle))
        if resp.status_code == 404:
            raise XError(f"Couldn't find @{handle} through the RSS bridge.")
        resp.raise_for_status()
        return resp.text

    def lookup(self, handle: str) -> XProfile:
        import feedparser

        d = feedparser.parse(self._feed(handle))
        if not getattr(d, "version", "") and not d.entries:
            raise XError(f"The RSS bridge didn't return a feed for @{handle}.")
        title = d.feed.get("title") or ""
        # Bridges title feeds like "Jane Doe / @jane" or "Twitter @jane".
        name = re.split(r"\s*[/(|]\s*@", title)[0].strip() or None
        image = (d.feed.get("image") or {}).get("href")
        return XProfile(handle=handle, name=name, avatar_url=image)

    def fetch(self, profile: XProfile, since_id: str | None, max_results: int) -> list[XPost]:
        posts = posts_from_feed(self._feed(profile.handle))
        if since_id and since_id.isdigit():
            posts = [p for p in posts if p.id.isdigit() and int(p.id) > int(since_id)]
        return posts[:max_results]


def get_source():
    """The configured source, or None if X isn't set up."""
    token = config.x_bearer_token()
    if token:
        return ApiSource(token)
    template = config.x_rss_template()
    if template:
        return BridgeSource(template)
    return None


NOT_CONFIGURED = (
    "X isn't connected yet. Set TROVE_X_BEARER_TOKEN (X API) or "
    "TROVE_X_RSS_TEMPLATE (an RSS bridge URL with {handle}) and restart Trove."
)
