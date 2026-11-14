"""Discover — suggest blogs and X accounts to follow.

One on-demand Claude call with the web search server tool. The prompt carries an
interest profile read from the library (discoverstore.build_profile) plus any
context you type ("I'm interested in wine"); the model searches for real,
active sources and hands back its picks through a `submit_suggestions` tool.

Nothing it says is trusted blindly: every blog is resolved to a working RSS/Atom
feed with feedfetch before it's shown (unresolvable ones are dropped), handles
must be valid, and anything you already follow — or were shown before — is
filtered out. X handles are checked for real when you follow (the X source
looks them up), so suggesting one costs no X API reads.

The Anthropic client and feed resolver are injectable so tests mock both.
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import config, db, discoverstore, feedfetch, xsource
from .urls import canonicalize

log = logging.getLogger(__name__)

PER_KIND = 8  # suggestions asked for per kind per run
_MAX_TURNS = 8  # pause_turn resumes + one nudge to submit
_RESOLVE_TIMEOUT = 12.0


class DiscoverError(Exception):
    pass


_SUBMIT_TOOL = {
    "name": "submit_suggestions",
    "description": (
        "Submit your final suggestions. Call this exactly once, after searching, "
        "with only sources you confirmed exist and are active."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "blogs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Blog or newsletter name"},
                        "url": {"type": "string", "description": "Homepage URL"},
                        "feed_url": {
                            "type": "string",
                            "description": "RSS/Atom feed URL if you found it, else empty string",
                        },
                        "description": {"type": "string", "description": "One sentence: what it covers"},
                        "reason": {"type": "string", "description": "One sentence: why it fits this reader"},
                        "topics": {"type": "array", "items": {"type": "string"}},
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
                        "description": {"type": "string", "description": "One sentence: who they are"},
                        "reason": {"type": "string", "description": "One sentence: why they fit this reader"},
                        "topics": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["handle", "name", "description", "reason", "topics"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["blogs", "people"],
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------- prompt ----
def _bullets(values: list[str]) -> str:
    return "\n".join(f"- {v}" for v in values) if values else "- (none)"


def build_prompt(
    profile: discoverstore.Profile,
    context: str | None,
    kinds: str,
    exclude: list[str],
    *,
    per_kind: int = PER_KIND,
) -> str:
    want = []
    if kinds in ("all", "blogs"):
        want.append(f"up to {per_kind} blogs or newsletters that publish an RSS/Atom feed")
    if kinds in ("all", "x"):
        want.append(f"up to {per_kind} people to follow on X (Twitter)")
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

Find {" and ".join(want)}.

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
- Use web search to find and check every source. Only suggest ones you confirmed exist and have
  published in roughly the last six months. Never guess a URL or handle.
- Prefer individual writers, independent blogs, researchers and practitioners with a real point of
  view over large news outlets and brand accounts.
- Don't suggest anything they already follow. Vary the picks; avoid five versions of the same voice.
- For blogs give the homepage URL, and the feed URL when you can find it.
- For people give the exact X handle from their profile.
- Keep each description and reason to one plain sentence. Give 1-3 short topics each.

When you're done, call submit_suggestions once with your picks."""


# --------------------------------------------------------------- the call ----
def _default_client():
    import anthropic

    return anthropic.Anthropic()


def _search_tool(model: str, max_uses: int) -> dict:
    # Dynamic-filtering web search needs a 4.6+ model; Haiku 4.5 and older take the basic one.
    basic = any(m in model for m in ("haiku-4", "sonnet-4-5", "opus-4-5", "opus-4-1", "-3-"))
    return {
        "type": "web_search_20250305" if basic else "web_search_20260209",
        "name": "web_search",
        "max_uses": max_uses,
    }


def _supports_fallbacks(model: str) -> bool:
    return any(m in model for m in ("opus-5-5", "opus-5", "sonnet-5-5", "fable-5"))


def research(
    prompt: str,
    *,
    client=None,
    model: str | None = None,
    effort: str | None = None,
    max_searches: int | None = None,
) -> dict:
    """Run the search-and-pick loop. Returns the submit_suggestions input: {blogs, people}."""
    client = client or _default_client()
    model = model or config.discover_model()
    tools = [_search_tool(model, max_searches or config.discover_max_searches()), _SUBMIT_TOOL]
    kwargs: dict = {}
    if not any(m in model for m in ("haiku-4", "-3-")):
        kwargs["output_config"] = {"effort": effort or config.discover_effort()}
    if _supports_fallbacks(model):
        # A safety-classifier refusal reroutes to a fallback model instead of failing the run.
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"

    messages: list = [{"role": "user", "content": prompt}]
    nudged = False
    for _ in range(_MAX_TURNS):
        resp = client.beta.messages.create(
            model=model, max_tokens=16000, tools=tools, messages=messages, **kwargs
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "submit_suggestions":
                data = block.input if isinstance(block.input, dict) else json.loads(block.input)
                return {"blogs": list(data.get("blogs") or []), "people": list(data.get("people") or [])}
        if resp.stop_reason == "refusal":
            raise DiscoverError("Claude declined this request. Try different wording.")
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "pause_turn":
            continue  # server-side search loop hit its limit; resend and it resumes
        if resp.stop_reason == "max_tokens":
            raise DiscoverError("The search ran out of room before it finished. Try again.")
        if nudged:
            break
        # Finished talking without submitting — ask once for the tool call.
        messages.append({"role": "user", "content": "Call submit_suggestions now with your final picks."})
        nudged = True
    raise DiscoverError("The search didn't return any suggestions. Try again.")


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


def _resolve_blog(raw: dict, resolve) -> Candidate | None:
    url = _clean(raw.get("url"))
    feed = _clean(raw.get("feed_url"))
    for candidate in [u for u in (feed, url) if u]:
        try:
            feed_url, parsed = resolve(candidate)
        except Exception:  # noqa: BLE001 - dead link, no feed, timeout: try the next
            continue
        if not parsed.entries:
            return None  # a feed with nothing in it isn't worth following
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


def verify_blogs(blogs: list[dict], followed_feeds: set[str], *, resolve=None) -> list[Candidate]:
    """Keep only blogs that resolve to a non-empty feed you don't already follow. Order is kept."""
    resolve = resolve or (lambda u: feedfetch.resolve_feed(u, fetcher=_quick_fetch))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda b: _resolve_blog(b, resolve), blogs))
    out: list[Candidate] = []
    seen: set[str] = set()
    for c, raw in zip(results, blogs):
        if c is None or c.key in seen:
            continue
        site = canonicalize(c.url) if c.url else None
        if c.key in followed_feeds or (site and site in followed_feeds):
            continue
        seen.add(c.key)
        out.append(c)
    return out


def _quick_fetch(url: str) -> str:
    return feedfetch.fetch(url, timeout=_RESOLVE_TIMEOUT)


def verify_people(people: list[dict], followed_handles: set[str]) -> list[Candidate]:
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
    return out


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
        if r["kinds"] in ("all", "blogs"):
            candidates += verify_blogs(picks["blogs"], followed_feeds, resolve=resolve)
        if r["kinds"] in ("all", "x"):
            candidates += verify_people(picks["people"], followed_handles)
        log.warning(
            "discovery run %s: model picked %d blogs / %d people; %d passed verification",
            run_id, len(picks["blogs"]), len(picks["people"]), len(candidates),
        )
    except DiscoverError as exc:
        _finish(db_path, run_id, error=str(exc))
        return 0
    except Exception as exc:  # noqa: BLE001 - API/network failure: record it, don't crash the thread
        log.exception("discovery run %s failed", run_id)
        _finish(db_path, run_id, error=_friendly(exc))
        return 0

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
        discoverstore.finish_run(conn, run_id, found=found)
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
    return "The search failed partway. Try again."


def launch(run_id: int) -> None:
    """Run in a background thread — a search takes a minute or two, too long for a request."""
    threading.Thread(target=run, args=(run_id,), name=f"discover-{run_id}", daemon=True).start()
