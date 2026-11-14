"""HTTP API. Sync handlers (FastAPI runs them in a threadpool); one SQLite
connection per request via db.cursor()."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db, discover, discoverstore, feedfetch, store, xsource, xstore
from .worker import poll_x_account
from .urls import canonicalize

router = APIRouter(prefix="/api")


class CaptureBody(BaseModel):
    url: str
    kind: str = "saved"  # 'saved' (read-later) | 'bookmark'


class FeedBody(BaseModel):
    url: str


class CollectionBody(BaseModel):
    name: str
    query: str | None = None
    item_ids: list[int] | None = None


class AddItemBody(BaseModel):
    item_id: int


class HighlightBody(BaseModel):
    quote: str
    start: int
    end: int


class TagBody(BaseModel):
    name: str


class XAccountBody(BaseModel):
    handle: str


class XReadBody(BaseModel):
    ids: list[int]
    state: str = "read"  # 'read' | 'unread'


class XThemeBody(BaseModel):
    theme: str | None = None


class DiscoverBody(BaseModel):
    context: str | None = None
    kinds: str = "all"  # 'all' | 'blogs' | 'x'


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/items", status_code=201)
def capture(body: CaptureBody) -> dict:
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="Enter a URL to save.")
    if body.kind not in ("saved", "bookmark"):
        raise HTTPException(status_code=422, detail="kind must be 'saved' or 'bookmark'.")
    canon = canonicalize(url)
    with db.cursor() as conn:
        existing = store.get_item_by_url(conn, canon)
        if existing is not None:
            # Duplicate capture: surface the existing item, don't make a copy (PRD §11).
            return {"item": dict(existing), "duplicate": True}
        lane = "bookmark" if body.kind == "bookmark" else "saved"
        job_kind = "bookmark" if body.kind == "bookmark" else "extract"
        item_id = store.create_item(conn, canon, url, lane=lane, job_kind=job_kind)
        item = store.get_item_by_url(conn, canon)
        return {"item": dict(item), "duplicate": False}


@router.get("/items")
def list_items(view: str = "all", feed_id: int | None = None) -> dict:
    if view not in ("all", "unread", "feed"):
        raise HTTPException(status_code=422, detail="view must be 'all', 'unread', or 'feed'")
    if view == "feed" and feed_id is None:
        raise HTTPException(status_code=422, detail="feed view requires feed_id")
    with db.cursor() as conn:
        return {
            "items": store.list_items(conn, view, feed_id),
            "unread_count": store.unread_count(conn),
        }


@router.get("/lens")
def lens(q: str = "") -> dict:
    with db.cursor() as conn:
        result = store.lens_search(conn, q)
        return {"query": q.strip(), **result}


@router.get("/items/{item_id}")
def get_item(item_id: int) -> dict:
    with db.cursor() as conn:
        # Opening an item starts what it deferred (feed fetch, AI enrichment).
        store.on_open(conn, item_id)
        item = store.get_item(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return {"item": item}


@router.post("/items/{item_id}/save")
def save_item(item_id: int) -> dict:
    with db.cursor() as conn:
        if not store.promote_to_saved(conn, item_id):
            raise HTTPException(status_code=404, detail="Item not found.")
        return {"item": store.get_item(conn, item_id)}


@router.post("/items/{item_id}/read")
def mark_read(item_id: int) -> dict:
    with db.cursor() as conn:
        if not store.set_read_state(conn, item_id, "read"):
            raise HTTPException(status_code=404, detail="Item not found.")
        return {"item": store.get_item(conn, item_id), "unread_count": store.unread_count(conn)}


@router.post("/items/{item_id}/unread")
def mark_unread(item_id: int) -> dict:
    with db.cursor() as conn:
        if not store.set_read_state(conn, item_id, "unread"):
            raise HTTPException(status_code=404, detail="Item not found.")
        return {"item": store.get_item(conn, item_id), "unread_count": store.unread_count(conn)}


@router.delete("/items/{item_id}")
def delete_item(item_id: int) -> dict:
    with db.cursor() as conn:
        if not store.delete_item(conn, item_id):
            raise HTTPException(status_code=404, detail="Item not found.")
        return {"deleted": True, "unread_count": store.unread_count(conn)}


@router.post("/items/{item_id}/retry")
def retry(item_id: int) -> dict:
    with db.cursor() as conn:
        if not store.retry_extract(conn, item_id):
            raise HTTPException(status_code=404, detail="Item not found.")
        return {"item": store.get_item(conn, item_id)}


# ---------------------------------------------------------------- feeds ----
@router.get("/feeds")
def list_feeds() -> dict:
    with db.cursor() as conn:
        return {"feeds": store.list_feeds(conn)}


@router.post("/feeds", status_code=201)
def add_feed(body: FeedBody) -> dict:
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="Enter a feed or site URL.")
    try:
        feed_url, parsed = feedfetch.resolve_feed(url)
    except feedfetch.FeedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:  # noqa: BLE001 - network/parse failure
        raise HTTPException(status_code=502, detail="Couldn't reach that URL.")
    with db.cursor() as conn:
        existing = store.get_feed_by_url(conn, feed_url)
        feed_id = store.add_feed(conn, feed_url, parsed.site_url, parsed.title)
        store.ingest_entries(conn, feed_id, parsed.title, parsed.entries)
        store.mark_feed_polled(conn, feed_id, None)
        feed = dict(store.get_feed(conn, feed_id))
        feed["unread_count"] = next(
            (f["unread_count"] for f in store.list_feeds(conn) if f["id"] == feed_id), 0
        )
        return {"feed": feed, "duplicate": existing is not None}


@router.delete("/feeds/{feed_id}")
def delete_feed(feed_id: int) -> dict:
    with db.cursor() as conn:
        if not store.delete_feed(conn, feed_id):
            raise HTTPException(status_code=404, detail="Feed not found.")
        return {"deleted": True}


# ---------------------------------------------------------- collections ----
def _collection_with_count(conn, cid: int) -> dict:
    return next((c for c in store.list_collections(conn) if c["id"] == cid), None)


@router.get("/collections")
def list_collections() -> dict:
    with db.cursor() as conn:
        return {"collections": store.list_collections(conn)}


@router.post("/collections", status_code=201)
def create_collection(body: CollectionBody) -> dict:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name the collection.")
    with db.cursor() as conn:
        cid = store.create_collection(conn, name, (body.query or None), body.item_ids)
        return {"collection": _collection_with_count(conn, cid)}


@router.get("/collections/{cid}")
def get_collection(cid: int) -> dict:
    with db.cursor() as conn:
        col = store.get_collection(conn, cid)
        if col is None:
            raise HTTPException(status_code=404, detail="Collection not found.")
        return {"collection": dict(col), "items": store.collection_items(conn, cid)}


@router.delete("/collections/{cid}")
def delete_collection(cid: int) -> dict:
    with db.cursor() as conn:
        if not store.delete_collection(conn, cid):
            raise HTTPException(status_code=404, detail="Collection not found.")
        return {"deleted": True}


@router.post("/collections/{cid}/items")
def add_to_collection(cid: int, body: AddItemBody) -> dict:
    with db.cursor() as conn:
        if not store.add_item_to_collection(conn, cid, body.item_id):
            raise HTTPException(status_code=404, detail="Collection or item not found.")
        return {"collection": _collection_with_count(conn, cid)}


@router.delete("/collections/{cid}/items/{item_id}")
def remove_from_collection(cid: int, item_id: int) -> dict:
    with db.cursor() as conn:
        store.remove_item_from_collection(conn, cid, item_id)
        return {"collection": _collection_with_count(conn, cid)}


# ------------------------------------------------------------ highlights ----
@router.post("/items/{item_id}/highlights", status_code=201)
def create_highlight(item_id: int, body: HighlightBody) -> dict:
    # Store the quote verbatim (offsets must still match it for repainting);
    # only validate that the selection isn't blank.
    if not (body.quote or "").strip():
        raise HTTPException(status_code=422, detail="Select some text to highlight.")
    if body.start < 0 or body.end <= body.start:
        raise HTTPException(status_code=422, detail="Highlight range is invalid.")
    with db.cursor() as conn:
        hl = store.create_highlight(conn, item_id, body.quote, body.start, body.end)
        if hl is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return {"highlight": hl}


@router.get("/highlights")
def list_highlights() -> dict:
    with db.cursor() as conn:
        return {"highlights": store.list_highlights(conn)}


@router.delete("/highlights/{hid}")
def delete_highlight(hid: int) -> dict:
    with db.cursor() as conn:
        if not store.delete_highlight(conn, hid):
            raise HTTPException(status_code=404, detail="Highlight not found.")
        return {"deleted": True}


# ------------------------------------------------------------- bookmarks ----
@router.get("/bookmarks")
def list_bookmarks() -> dict:
    with db.cursor() as conn:
        return {"bookmarks": store.list_bookmarks(conn)}


@router.post("/items/{item_id}/tags")
def add_tag(item_id: int, body: TagBody) -> dict:
    if not (body.name or "").strip():
        raise HTTPException(status_code=422, detail="Enter a tag.")
    with db.cursor() as conn:
        topics = store.add_item_tag(conn, item_id, body.name)
        if topics is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return {"topics": topics}


@router.delete("/items/{item_id}/tags/{name}")
def remove_tag(item_id: int, name: str) -> dict:
    with db.cursor() as conn:
        topics = store.remove_item_tag(conn, item_id, name)
        if topics is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return {"topics": topics}


# -------------------------------------------------------------------- X ----
@router.get("/x/status")
def x_status() -> dict:
    source = xsource.get_source()
    return {
        "configured": source is not None,
        "mode": source.mode if source else None,
        "message": None if source else xsource.NOT_CONFIGURED,
    }


@router.get("/x/accounts")
def list_x_accounts() -> dict:
    with db.cursor() as conn:
        return {"accounts": xstore.list_accounts(conn), "unread_count": xstore.unread_total(conn)}


@router.post("/x/accounts", status_code=201)
def follow_x_account(body: XAccountBody) -> dict:
    try:
        handle = xsource.normalize_handle(body.handle)
    except xsource.XError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    with db.cursor() as conn:
        existing = xstore.get_account_by_handle(conn, handle)
        if existing is not None:
            return {"account": xstore.account_dict(conn, existing["id"]), "duplicate": True}
    source = xsource.get_source()
    if source is None:
        raise HTTPException(status_code=422, detail=xsource.NOT_CONFIGURED)
    try:
        profile = source.lookup(handle)
    except xsource.XError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:  # noqa: BLE001 - network failure
        raise HTTPException(status_code=502, detail="Couldn't reach X. Try again in a moment.")
    with db.cursor() as conn:
        account_id = xstore.add_account(conn, profile)
        conn.commit()
        # First pull now so the stream isn't empty; failures are recorded on the account.
        poll_x_account(conn, xstore.get_account(conn, account_id), source)
        return {"account": xstore.account_dict(conn, account_id), "duplicate": False}


@router.delete("/x/accounts/{account_id}")
def unfollow_x_account(account_id: int) -> dict:
    with db.cursor() as conn:
        if not xstore.delete_account(conn, account_id):
            raise HTTPException(status_code=404, detail="Account not found.")
        return {"deleted": True}


@router.post("/x/accounts/{account_id}/refresh")
def refresh_x_account(account_id: int) -> dict:
    source = xsource.get_source()
    if source is None:
        raise HTTPException(status_code=422, detail=xsource.NOT_CONFIGURED)
    with db.cursor() as conn:
        account = xstore.get_account(conn, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found.")
        counts = poll_x_account(conn, account, source)
        return {"account": xstore.account_dict(conn, account_id), **counts}


@router.get("/x/posts")
def list_x_posts(account_id: int | None = None, unread: bool = False) -> dict:
    with db.cursor() as conn:
        return {
            "posts": xstore.list_posts(conn, account_id, unread_only=unread),
            "unread_count": xstore.unread_total(conn),
        }


@router.post("/x/posts/read")
def mark_x_posts(body: XReadBody) -> dict:
    if body.state not in ("read", "unread"):
        raise HTTPException(status_code=422, detail="state must be 'read' or 'unread'.")
    with db.cursor() as conn:
        n = xstore.mark_posts(conn, body.ids, body.state)
        return {"updated": n, "unread_count": xstore.unread_total(conn)}


@router.put("/x/posts/{item_id}/theme")
def set_x_post_theme(item_id: int, body: XThemeBody) -> dict:
    theme = " ".join((body.theme or "").split())[:40] or None
    with db.cursor() as conn:
        if not xstore.set_theme(conn, item_id, theme):
            raise HTTPException(status_code=404, detail="Post not found.")
        return {"post": xstore.get_post(conn, item_id)}


# -------------------------------------------------------------- discover ----
def _discover_state(conn) -> dict:
    discoverstore.reconcile_followed(conn)
    return {
        "run": discoverstore.latest_run(conn),
        "suggestions": discoverstore.list_suggestions(conn, "new"),
        "profile": discoverstore.build_profile(conn).summary(),
        "x_configured": xsource.get_source() is not None,
    }


@router.get("/discover")
def get_discover() -> dict:
    with db.cursor() as conn:
        return _discover_state(conn)


@router.post("/discover", status_code=202)
def start_discover(body: DiscoverBody) -> dict:
    context = " ".join((body.context or "").split())[:300] or None
    if body.kinds not in discoverstore.KINDS:
        raise HTTPException(status_code=422, detail="kinds must be 'all', 'blogs', or 'x'.")
    with db.cursor() as conn:
        if discoverstore.running_run(conn) is not None:
            raise HTTPException(status_code=409, detail="A search is already running. It'll finish shortly.")
        if context is None and discoverstore.build_profile(conn).empty:
            raise HTTPException(
                status_code=422,
                detail="Trove doesn't know your interests yet. Tell it what you're into, or follow a few feeds first.",
            )
        run_id = discoverstore.create_run(conn, context, body.kinds)
        conn.commit()
        run = discoverstore.get_run(conn, run_id)
    discover.launch(run_id)
    return {"run": run}


@router.post("/discover/suggestions/{sid}/follow")
def follow_suggestion(sid: int) -> dict:
    with db.cursor() as conn:
        s = discoverstore.get_suggestion(conn, sid)
    if s is None:
        raise HTTPException(status_code=404, detail="Suggestion not found.")
    result: dict = {}
    if s["kind"] == "blog":
        result = add_feed(FeedBody(url=s["feed_url"] or s["url"] or ""))
    else:
        result = follow_x_account(XAccountBody(handle=s["handle"] or ""))
    with db.cursor() as conn:
        discoverstore.set_status(conn, sid, "followed")
        return {**result, "suggestion": discoverstore.get_suggestion(conn, sid)}


@router.post("/discover/suggestions/{sid}/dismiss")
def dismiss_suggestion(sid: int) -> dict:
    with db.cursor() as conn:
        if not discoverstore.set_status(conn, sid, "dismissed"):
            raise HTTPException(status_code=404, detail="Suggestion not found.")
        return {"suggestion": discoverstore.get_suggestion(conn, sid)}
