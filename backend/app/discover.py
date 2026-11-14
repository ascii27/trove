"""Discover — suggest blogs and X accounts to follow.

One on-demand Claude call with structured JSON output. The prompt carries an
interest profile read from the library (discoverstore.build_profile) plus any
context you type ("I'm interested in wine"); the model proposes more candidates
than are needed, from what it knows.

Trove then checks them itself instead of trusting them: every blog must resolve
to a working RSS/Atom feed (trying common feed paths when the homepage doesn't
advertise one) that has posted recently, handles must be valid, and anything
you already follow, or were shown before, is filtered out. The first PER_KIND of
each kind that pass are kept. X handles are checked for real when you follow
(the X source looks them up), so suggesting one costs no X API reads.

Why not the web search tool: in live runs Opus 5.5 routed every search through
code execution, decided it couldn't read the results, and submitted one pick or
none. Checking the feeds directly is both stricter and far cheaper.

The Anthropic client and feed resolver are injectable so tests mock both.
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from . import config, db, discoverstore, feedfetch, xsource
from .urls import canonicalize

log = logging.getLogger(__name__)

PER_KIND = 8  # suggestions kept per kind per run
ASK_BLOGS = 12  # over-ask: some won't have a working feed
ASK_PEOPLE = 10
STALE_DAYS = 270  # a blog whose newest post is older than this counts as dormant
_RESOLVE_TIMEOUT = 12.0
# Tried in order when a homepage doesn't advertise its feed with <link rel="alternate">.
_FEED_PATHS = ("/feed/", "/feed", "/rss.xml", "/rss", "/atom.xml", "/index.xml", "/feed.xml", "/blog/feed/")


class DiscoverError(Exception):
    pass


_ITEM_PROPS = {
    "description": {"type": "string", "description": "One sentence: what it covers / who they are"},
    "reason": {"type": "string", "description": "One sentence: why it fits this reader"},
    "topics": {"type": "array", "items": {"type": "string"}, "description": "1-3 short topics"},
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "blogs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string", "description": "Homepage URL"},
                    "feed_url": {"type": "string", "description": "RSS/Atom URL if known, else empty"},
                    **_ITEM_PROPS,
                },
                "required": ["name", "url", "feed_url", "description", "reason", "topics"],
                "additionalProperties": False,
            },
        },
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "handle": {"type": "string", "description": "X handle without @"},
                    "name": {"type": "string"},
                    **_ITEM_PROPS,
                },
                "required": ["handle", "name", "description", "reason", "topics"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["blogs", "people"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- prompt ----
def _bullets(values: list[str]) -> str:
    return "\n".join(f"- {v}" for v in values) if values else "- (none)"


def build_prompt(profile: discoverstore.Profile, context: str | None, kinds: str, exclude: list[str]) -> str:
    want = []
    if kinds in ("all", "blogs"):
        want.append(f"{ASK_BLOGS} blogs or newsletters that publish an RSS/Atom feed")
    if kinds in ("all", "x"):
        want.append(f"{ASK_PEOPLE} people to follow on X (Twitter)")
    feeds = [f"{f['title'] or '(untitled)'} — {f['site_url'] or f['url']}" for f in profile.feeds]
    people = [f"@{a['handle']}" + (f" ({a['name']})" if a["name"] else "") for a in profile.x_accounts]

    if context:
        focus = (
            f"The reader asked specifically for: \"{context}\"\n"
            "Make every suggestion serve that request. Use the profile below only to judge "
            "their taste (depth, tone, the kind of writer they like) — not to pick the subject."
        )
    else:
        focus = (
            "Suggest sources that match the interests in the profile below. Favour the strongest "
            "and most recurring interests, and include a few that sit next to them."
        )

    return f"""You help one person find new writers to read in Trove, their calm, personal reading app.

Suggest {" and ".join(want)}. Leave a list empty if it isn't asked for.

{focus}

## Reader profile
Topics they keep, strongest first:
{_bullets(profile.topics)}

Feeds they already follow:
{_bullets(feeds)}

People they already follow on X:
{_bullets(people)}

Themes in their X stream:
{_bullets(profile.x_themes)}

Their research collections:
{_bullets(profile.collections)}

Recently saved articles:
{_bullets(profile.recent_titles)}

## Already suggested before — do not suggest these again
{_bullets(exclude)}

## How to choose
- Suggest writers you're confident exist and were still publishing recently. Never invent a URL
  or handle; leave a source out rather than guess. Trove checks each blog's feed for recent posts
  and quietly drops ones that fail, so give the full number asked for, strongest first.
- Prefer individual writers, independent blogs, researchers and practitioners with a real point of
  view over large news outlets and brand accounts.
- Don't suggest anything they already follow. Vary the picks; avoid five versions of the same voice.
- For blogs give the homepage URL, and the feed URL if you know it (else an empty string).
- For people give their exact X handle.
- Keep each description and reason to one plain sentence. Give 1-3 short topics each."""


# --------------------------------------------------------------- the call ----
def _default_client():
    import anthropic

    return anthropic.Anthropic()


def _supports_fallbacks(model: str) -> bool:
    return any(m in model for m in ("opus-5-5", "opus-5", "sonnet-5-5", "fable-5"))


def research(prompt: str, *, client=None, model: str | None = None, effort: str | None = None) -> dict:
    """Ask for candidates. Returns {blogs, people} as the model gave them, plus token usage."""
    client = client or _default_client()
    model = model or config.discover_model()
    output_config: dict = {"format": {"type": "json_schema", "schema": _SCHEMA}}
    kwargs: dict = {}
    if not any(m in model for m in ("haiku-4", "-3-")):
        output_config["effort"] = effort or config.discover_effort()
    if _supports_fallbacks(model):
        # A safety-classifier refusal reroutes to a fallback model instead of failing the run.
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
    resp = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
        output_config=output_config,
        **kwargs,
    )
    if resp.stop_reason == "refusal":
        raise DiscoverError("Claude declined this request. Try different wording.")
    if resp.stop_reason == "max_tokens":
        raise DiscoverError("The suggestions were cut off before they finished. Try again.")
    text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
    if not text:
        raise DiscoverError("Claude didn't return any suggestions. Try again.")
    data = json.loads(text)
    usage = getattr(resp, "usage", None)
    return {
        "blogs": list(data.get("blogs") or []),
        "people": list(data.get("people") or []),
        "usage": {
            "input": getattr(usage, "input_tokens", None),
            "output": getattr(usage, "output_tokens", None),
        },
    }


# ----------------------------------------------------------- verification ----
@dataclass
class Candidate:
    kind: str  # 'blog' | 'x'
    key: str
    name: str
    url: str | None = None
    feed_url: str | None = None
    handle: str | None = None
    description: str | None = None
    reason: str | None = None
    topics: list[str] = field(default_factory=list)


def _clean(s) -> str:
    return " ".join(str(s or "").split()).strip()


def _candidate_urls(url: str, feed: str) -> list[str]:
    urls = [u for u in (feed, url) if u]
    if url:
        parts = urlsplit(url if "://" in url else f"https://{url}")
        if parts.netloc:
            urls += [f"{parts.scheme}://{parts.netloc}{p}" for p in _FEED_PATHS]
    return list(dict.fromkeys(urls))


def _is_fresh(parsed: feedfetch.ParsedFeed, now: datetime) -> bool:
    dates = [e.published_at for e in parsed.entries if e.published_at]
    if not dates:
        return True  # undated feed: can't tell, give it the benefit of the doubt
    return datetime.fromisoformat(max(dates)) >= now - timedelta(days=STALE_DAYS)


def _resolve_blog(raw: dict, resolve, now: datetime) -> Candidate | None:
    url = _clean(raw.get("url"))
    for candidate in _candidate_urls(url, _clean(raw.get("feed_url"))):
        try:
            feed_url, parsed = resolve(candidate)
        except Exception:  # noqa: BLE001 - dead link, no feed, timeout: try the next
            continue
        if not parsed.entries or not _is_fresh(parsed, now):
            return None  # empty or dormant — not worth following
        name = _clean(raw.get("name")) or parsed.title or url
        return Candidate(
            kind="blog",
            key=canonicalize(feed_url),
            name=name[:120],
            url=url or parsed.site_url,
            feed_url=feed_url,
            description=_clean(raw.get("description"))[:300] or None,
            reason=_clean(raw.get("reason"))[:300] or None,
            topics=[_clean(t)[:40] for t in raw.get("topics") or [] if _clean(t)],
        )
    return None


def verify_blogs(
    blogs: list[dict], followed_feeds: set[str], *, resolve=None, now: datetime | None = None, limit: int = PER_KIND
) -> list[Candidate]:
    """Keep blogs with a fresh, non-empty feed you don't already follow — the first `limit`, in order."""
    resolve = resolve or (lambda u: feedfetch.resolve_feed(u, fetcher=_quick_fetch))
    now = now or datetime.now()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda b: _resolve_blog(b, resolve, now), blogs))
    out: list[Candidate] = []
    seen: set[str] = set()
    for c in results:
        if c is None or c.key in seen:
            continue
        site = canonicalize(c.url) if c.url else None
        if c.key in followed_feeds or (site and site in followed_feeds):
            continue
        seen.add(c.key)
        out.append(c)
    return out[:limit]


def _quick_fetch(url: str) -> str:
    return feedfetch.fetch(url, timeout=_RESOLVE_TIMEOUT)


def verify_people(people: list[dict], followed_handles: set[str], *, limit: int = PER_KIND) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()
    for raw in people:
        try:
            handle = xsource.normalize_handle(_clean(raw.get("handle")))
        except xsource.XError:
            continue
        key = handle.lower()
        if key in followed_handles or key in seen:
            continue
        seen.add(key)
        out.append(
            Candidate(
                kind="x",
                key=key,
                name=(_clean(raw.get("name")) or f"@{handle}")[:120],
                url=f"https://x.com/{handle}",
                handle=handle,
                description=_clean(raw.get("description"))[:300] or None,
                reason=_clean(raw.get("reason"))[:300] or None,
                topics=[_clean(t)[:40] for t in raw.get("topics") or [] if _clean(t)],
            )
        )
    return out[:limit]


# ------------------------------------------------------------- the run ----
def run(run_id: int, *, db_path: str | None = None, research_fn=research, resolve=None) -> int:
    """Execute a discovery run end to end. Returns how many new suggestions it added."""
    with db.cursor(db_path) as conn:
        r = discoverstore.get_run(conn, run_id)
        if r is None:
            return 0
        profile = discoverstore.build_profile(conn)
        exclude = discoverstore.known_suggestions(conn)
        followed_feeds, followed_handles = discoverstore.followed_keys(conn)
    try:
        prompt = build_prompt(profile, r["context"], r["kinds"], exclude)
        picks = research_fn(prompt)
        candidates: list[Candidate] = []
        proposed = 0
        if r["kinds"] in ("all", "blogs"):
            proposed += len(picks["blogs"])
            candidates += verify_blogs(picks["blogs"], followed_feeds, resolve=resolve)
        if r["kinds"] in ("all", "x"):
            proposed += len(picks["people"])
            candidates += verify_people(picks["people"], followed_handles)
    except DiscoverError as exc:
        _finish(db_path, run_id, error=str(exc))
        return 0
    except Exception as exc:  # noqa: BLE001 - API/network failure: record it, don't crash the thread
        log.exception("discovery run %s failed", run_id)
        _finish(db_path, run_id, error=_friendly(exc))
        return 0

    usage = picks.get("usage") or {}
    found = 0
    with db.cursor(db_path) as conn:
        for c in candidates:
            found += discoverstore.add_suggestion(
                conn,
                run_id,
                kind=c.kind,
                key=c.key,
                name=c.name,
                url=c.url,
                feed_url=c.feed_url,
                handle=c.handle,
                description=c.description,
                reason=c.reason,
                topics=c.topics,
            )
        discoverstore.finish_run(
            conn,
            run_id,
            found=found,
            proposed=proposed,
            passed=len(candidates),
            input_tokens=usage.get("input"),
            output_tokens=usage.get("output"),
        )
    log.warning(
        "discovery run %s: %d proposed, %d passed checks, %d new; tokens in/out %s/%s",
        run_id, proposed, len(candidates), found, usage.get("input"), usage.get("output"),
    )
    return found


def _finish(db_path: str | None, run_id: int, *, error: str) -> None:
    with db.cursor(db_path) as conn:
        discoverstore.finish_run(conn, run_id, error=error)


def _friendly(exc: Exception) -> str:
    name = type(exc).__name__
    if "Authentication" in name or "PermissionDenied" in name:
        return "Trove couldn't reach Claude: check ANTHROPIC_API_KEY on the server."
    if "RateLimit" in name or "Overloaded" in name:
        return "Claude is busy right now. Try again in a minute."
    return "Finding suggestions failed partway. Try again."


def launch(run_id: int) -> None:
    """Run in a background thread — the call plus feed checks take a while, too long for a request."""
    threading.Thread(target=run, args=(run_id,), name=f"discover-{run_id}", daemon=True).start()
