"""HTTP API. Sync handlers (FastAPI runs them in a threadpool); one SQLite
connection per request via db.cursor()."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db, feedfetch, store
from .urls import canonicalize

router = APIRouter(prefix="/api")


class CaptureBody(BaseModel):
    url: str


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


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/items", status_code=201)
def capture(body: CaptureBody) -> dict:
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="Enter a URL to save.")
    canon = canonicalize(url)
    with db.cursor() as conn:
        existing = store.get_item_by_url(conn, canon)
        if existing is not None:
            # Duplicate capture: surface the existing item, don't make a copy (PRD §11).
            return {"item": dict(existing), "duplicate": True}
        item_id = store.create_item(conn, canon, url)
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
        # Opening a deferred feed item starts its extraction (lazy load).
        store.load_if_deferred(conn, item_id)
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
