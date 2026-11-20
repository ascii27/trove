"""The Newspaper — a daily paper assembled from your feeds, X posts and reading list.

One cheap Claude call (TROVE_PAPER_MODEL, Haiku 5.5 at low effort) acts as editor: given the
unread, never-printed candidates since the last edition, it picks a lead, groups
the best stories into sections it names, writes a headline and a short summary
for each, glosses a few X posts and pulls one or two items off your reading
list. Everything it returns is checked against the candidate list (unknown or
duplicate ids are dropped), then laid out as self-contained JSON with images:
the item's own image, else the page's og:image fetched for the lead and each
section's top story.

Editions run in a background thread (manual "Print a new edition") or on a
schedule checked by the worker's maintenance pass (`maybe_print`). The client
and fetcher are injectable so tests mock both.
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, db, extract, paperstore

log = logging.getLogger(__name__)

MIN_STORIES = 3  # fewer new stories than this and there's no paper to print
TARGET_STORIES = 15
_IMAGE_TIMEOUT = 8.0


class PaperError(Exception):
    pass


_STORY = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "headline": {"type": "string", "description": "Newspaper headline, sentence case, under 90 chars"},
        "summary": {"type": "string", "description": "1-2 sentence standfirst, only from the given text"},
    },
    "required": ["id", "headline", "summary"],
    "additionalProperties": False,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "editors_note": {"type": "string", "description": "One sentence: what's in today's paper"},
        "lead": _STORY,
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Section name, 1-3 words"},
                    "stories": {"type": "array", "items": _STORY},
                },
                "required": ["name", "stories"],
                "additionalProperties": False,
            },
        },
        "from_x": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "summary": {"type": "string", "description": "One line on what the post says"},
                },
                "required": ["id", "summary"],
                "additionalProperties": False,
            },
        },
        "from_shelf": {"type": "array", "items": _STORY},
    },
    "required": ["editors_note", "lead", "sections", "from_x", "from_shelf"],
    "additionalProperties": False,
}

_PROMPT = """You are the editor of a personal morning newspaper for one reader, built only from the \
candidate items below (their RSS feeds, people they follow on X, and articles they saved to read).

Assemble today's edition:
- lead: the single most interesting, substantial story.
- sections: up to {target} stories in total (including the lead) across 2-5 sections you name \
yourself (1-3 words, e.g. "AI", "Engineering", "Business", "Culture"). 1-4 stories per section, \
best first. Leave out thin items (bare links, quotes with no context, promos) and near-duplicates; \
when several items cover the same news, pick the best one. Prefer variety of sources. If there are \
fewer good stories than {target}, print fewer — never pad.
- from_x: 0-5 of the most interesting X posts, each with a one-line summary.
- from_shelf: 0-2 items from the reading list worth a nudge today.
- editors_note: one plain sentence introducing the paper.

Only use ids from the candidates, each at most once, and only feed items in lead/sections, x items \
in from_x, saved items in from_shelf. Headlines: clear, specific, sentence case, no clickbait. \
Summaries: 1-2 sentences written only from the candidate's text — never add facts it doesn't \
contain; if the text is thin, keep the summary short.

Candidates (JSON lines; lane is feed, x or saved):
{candidates}"""


# ----------------------------------------------------------------- editor ----
def _default_client():
    import anthropic

    return anthropic.Anthropic()


def _candidate_line(c: paperstore.Candidate) -> str:
    return json.dumps(
        {
            "id": c.id,
            "lane": c.lane,
            "title": (c.title or "")[:160],
            "source": c.source or c.author or "",
            "topics": c.topics,
            "text": c.text,
        },
        ensure_ascii=False,
    )


def edit(cands: list[paperstore.Candidate], *, client=None, model: str | None = None) -> tuple[dict, dict]:
    """Ask the editor for an edition. Returns (raw edition, usage)."""
    client = client or _default_client()
    model = model or config.paper_model()
    prompt = _PROMPT.format(target=TARGET_STORIES, candidates="\n".join(_candidate_line(c) for c in cands))
    output_config: dict = {"format": {"type": "json_schema", "schema": _SCHEMA}}
    if "haiku-4" not in model:
        output_config["effort"] = "low"
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
        output_config=output_config,
    )
    if resp.stop_reason == "refusal":
        raise PaperError("The editor declined to assemble this edition. Try again later.")
    if resp.stop_reason == "max_tokens":
        raise PaperError("The edition was cut off before it finished. Try again.")
    text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
    if not text:
        raise PaperError("The editor returned nothing. Try again.")
    usage = getattr(resp, "usage", None)
    return json.loads(text), {
        "input": getattr(usage, "input_tokens", None),
        "output": getattr(usage, "output_tokens", None),
    }


# ----------------------------------------------------------------- layout ----
def _clean(s, limit: int) -> str:
    return " ".join(str(s or "").split())[:limit]


def _story(c: paperstore.Candidate, headline: str | None, summary: str | None) -> dict:
    return {
        "item_id": c.id,
        "lane": c.lane,
        "headline": _clean(headline, 140) or _clean(c.title, 140) or "Untitled",
        "summary": _clean(summary, 420),
        "original_title": c.title,
        "source": c.source,
        "author": c.author,
        "url": c.url,
        "image": c.image,
        "published_at": c.published_at,
    }


def assemble(raw: dict, cands: list[paperstore.Candidate]) -> tuple[dict, list[int]]:
    """Validate the editor's picks against the candidates and lay out the paper.

    Returns (layout, item ids printed). Unknown ids, wrong lanes and repeats are dropped;
    if the editor's lead is unusable, the first good section story is promoted.
    """
    by_id = {c.id: c for c in cands}
    used: set[int] = set()

    def take(entry: dict | None, lanes: tuple[str, ...]) -> paperstore.Candidate | None:
        if not isinstance(entry, dict):
            return None
        c = by_id.get(entry.get("id"))
        if c is None or c.lane not in lanes or c.id in used:
            return None
        used.add(c.id)
        return c

    lead_c = take(raw.get("lead"), ("feed",))
    lead = _story(lead_c, raw["lead"].get("headline"), raw["lead"].get("summary")) if lead_c else None

    sections = []
    for sec in raw.get("sections") or []:
        stories = []
        for e in sec.get("stories") or []:
            c = take(e, ("feed",))
            if c:
                stories.append(_story(c, e.get("headline"), e.get("summary")))
        name = _clean(sec.get("name"), 30)
        if stories and name:
            sections.append({"name": name, "stories": stories})
    if lead is None:
        for sec in sections:
            if sec["stories"]:
                lead = sec["stories"].pop(0)
                break
        sections = [s for s in sections if s["stories"]]

    from_x = []
    for e in raw.get("from_x") or []:
        c = take(e, ("x",))
        if c:
            from_x.append(_story(c, c.author, e.get("summary")) | {"text": c.text[:280]})
    shelf = []
    for e in raw.get("from_shelf") or []:
        c = take(e, ("saved",))
        if c:
            shelf.append(_story(c, e.get("headline"), e.get("summary")))

    layout = {
        "editors_note": _clean(raw.get("editors_note"), 300),
        "lead": lead,
        "sections": sections,
        "from_x": from_x[:5],
        "from_shelf": shelf[:2],
    }
    stories = ([lead] if lead else []) + [s for sec in sections for s in sec["stories"]]
    layout["source_count"] = len({s["source"] for s in stories + shelf if s["source"]})
    printed = [s["item_id"] for s in stories] + [s["item_id"] for s in layout["from_x"]] + [
        s["item_id"] for s in layout["from_shelf"]
    ]
    return layout, printed


def fetch_page_image(url: str) -> str | None:
    try:
        html = extract.fetch_html(url, timeout=_IMAGE_TIMEOUT)
    except Exception:  # noqa: BLE001 - no image is fine
        return None
    return extract.page_image(html, url)


def fill_images(layout: dict, *, fetch=fetch_page_image) -> dict[int, str]:
    """Give the lead and each section's top story a picture. Returns {item_id: image} newly found."""
    featured = ([layout["lead"]] if layout.get("lead") else []) + [
        sec["stories"][0] for sec in layout["sections"] if sec["stories"]
    ]
    missing = [s for s in featured if not s.get("image") and s.get("url")]
    found: dict[int, str] = {}
    if missing:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for s, img in zip(missing, pool.map(lambda s: fetch(s["url"]), missing)):
                if img:
                    s["image"] = img
                    found[s["item_id"]] = img
    # Only featured stories show a picture; drop the rest so the layout stays calm.
    featured_ids = {s["item_id"] for s in featured}
    for sec in layout["sections"]:
        for s in sec["stories"]:
            if s["item_id"] not in featured_ids:
                s["image"] = None
    return found


# ------------------------------------------------------------------- run ----
def run(eid: int, *, db_path: str | None = None, edit_fn=edit, fetch_image=fetch_page_image) -> bool:
    """Build one edition end to end. Returns True if it printed."""
    with db.cursor(db_path) as conn:
        ed = paperstore.get_edition(conn, eid)
        if ed is None:
            return False
        cands = paperstore.candidates(conn, ed["window_start"])
    try:
        feed_count = sum(1 for c in cands if c.lane in ("feed", "saved"))
        if feed_count < MIN_STORIES:
            raise PaperError(
                f"Not enough new stories since the last edition ({feed_count}). "
                "Try again later, or follow more feeds in Discover."
            )
        raw, usage = edit_fn(cands)
        layout, printed = assemble(raw, cands)
        if layout["lead"] is None:
            raise PaperError("The editor didn't pick any stories. Try again.")
        found = fill_images(layout, fetch=fetch_image)
    except PaperError as exc:
        _fail(db_path, eid, str(exc))
        return False
    except Exception:  # noqa: BLE001 - API/network failure: record it, don't kill the thread
        log.exception("edition %s failed", eid)
        _fail(db_path, eid, "Printing failed partway. Try again.")
        return False
    with db.cursor(db_path) as conn:
        for item_id, img in found.items():
            paperstore.set_item_image(conn, item_id, img)
        paperstore.finish_edition(
            conn, eid, layout, printed, input_tokens=usage.get("input"), output_tokens=usage.get("output")
        )
    log.warning(
        "edition %s: %d candidates, %d printed; tokens in/out %s/%s",
        eid, len(cands), len(printed), usage.get("input"), usage.get("output"),
    )
    return True


def _fail(db_path: str | None, eid: int, error: str) -> None:
    with db.cursor(db_path) as conn:
        paperstore.fail_edition(conn, eid, error)


def launch(eid: int) -> None:
    threading.Thread(target=run, args=(eid,), name=f"edition-{eid}", daemon=True).start()


def start(conn, trigger: str) -> int:
    """Create a running edition (caller commits) — window is fixed now, so it's reproducible."""
    return paperstore.create_edition(conn, trigger, paperstore.window_start(conn))


# --------------------------------------------------------------- schedule ----
def due(settings: dict, now: datetime) -> str | None:
    """The local date to print for, if a scheduled edition is due now; else None.

    Starts 10 minutes before the hour so the paper is ready on time. A server that was
    down at print time catches up later the same day.
    """
    if settings["schedule"] == "off":
        return None
    try:
        tz = ZoneInfo(settings["tz"])
    except Exception:  # noqa: BLE001 - bad zone: fall back to UTC rather than never printing
        tz = timezone.utc
    local = now.astimezone(tz)
    weekend = local.weekday() >= 5
    if (settings["schedule"] == "weekdays" and weekend) or (settings["schedule"] == "weekends" and not weekend):
        return None
    ready_at = local.replace(hour=settings["hour"], minute=0, second=0, microsecond=0) - timedelta(minutes=10)
    if local < ready_at:
        return None
    today = local.date().isoformat()
    return None if settings.get("last_scheduled") == today else today


def maybe_print(conn, now: datetime | None = None, *, launch_fn=None) -> int | None:
    """Worker hook: start a scheduled edition if one is due. Returns its id."""
    settings = paperstore.get_settings(conn)
    day = due(settings, now or datetime.now(timezone.utc))
    if day is None or paperstore.running_edition(conn) is not None:
        return None
    paperstore.mark_scheduled(conn, day)
    eid = start(conn, "schedule")
    conn.commit()
    (launch_fn or launch)(eid)
    return eid
