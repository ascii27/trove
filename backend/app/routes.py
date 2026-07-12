"""HTTP API. Sync handlers (FastAPI runs them in a threadpool); one SQLite
connection per request via db.cursor()."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db, store
from .urls import canonicalize

router = APIRouter(prefix="/api")


class CaptureBody(BaseModel):
    url: str


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
def list_items(view: str = "all") -> dict:
    if view not in ("all", "unread"):
        raise HTTPException(status_code=422, detail="view must be 'all' or 'unread'")
    with db.cursor() as conn:
        return {"items": store.list_items(conn, view), "unread_count": store.unread_count(conn)}


@router.get("/items/{item_id}")
def get_item(item_id: int) -> dict:
    with db.cursor() as conn:
        item = store.get_item(conn, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found.")
        return {"item": item}


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
