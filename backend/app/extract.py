"""Article extraction — server-side fetch + trafilatura (Readability-class).

Extraction is near-instant but not guaranteed, which is why the item can end in a
'failed' or 'partial' state (PRD S1, §11). Content is stored as Markdown; the
reader renders it. `extract_from_html` is pure (no network) so tests use fixtures.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 Trove/0.1"
)
# Below this word count we treat the capture as truncated/paywalled rather than a
# clean article. Heuristic; deliberately low to avoid flagging genuinely short posts.
_PARTIAL_WORD_THRESHOLD = 100


@dataclass
class Extracted:
    status: str  # 'extracted' | 'partial' | 'failed'
    title: str | None = None
    author: str | None = None
    source: str | None = None
    publish_date: str | None = None
    content_text: str | None = None  # Markdown
    word_count: int = 0
    reading_minutes: int = 0
    error: str | None = None
    extra: dict = field(default_factory=dict)


def _reading_minutes(word_count: int) -> int:
    return max(1, math.ceil(word_count / 200)) if word_count else 0


def extract_from_html(html: str, url: str) -> Extracted:
    if not html or not html.strip():
        return Extracted(status="failed", error="Empty document")

    content = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,
        include_formatting=True,
        favor_recall=True,
    )
    if not content or not content.strip():
        return Extracted(status="failed", error="No article content found")

    meta = trafilatura.extract_metadata(html, default_url=url)
    title = getattr(meta, "title", None) if meta else None
    author = getattr(meta, "author", None) if meta else None
    source = (getattr(meta, "sitename", None) or getattr(meta, "hostname", None)) if meta else None
    publish_date = getattr(meta, "date", None) if meta else None

    word_count = len(content.split())
    status = "partial" if word_count < _PARTIAL_WORD_THRESHOLD else "extracted"

    return Extracted(
        status=status,
        title=title,
        author=author,
        source=source,
        publish_date=publish_date,
        content_text=content,
        word_count=word_count,
        reading_minutes=_reading_minutes(word_count),
    )


def fetch_html(url: str, *, timeout: float = 20.0) -> str:
    resp = httpx.get(
        url,
        headers={"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml"},
        follow_redirects=True,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.text


def fetch_and_extract(url: str, *, fetcher=fetch_html) -> Extracted:
    try:
        html = fetcher(url)
    except httpx.HTTPStatusError as exc:
        return Extracted(status="failed", error=f"Fetch failed: HTTP {exc.response.status_code}")
    except httpx.HTTPError as exc:
        return Extracted(status="failed", error=f"Could not reach the page: {exc.__class__.__name__}")
    except Exception as exc:  # noqa: BLE001 - defensive; extraction must never crash the worker
        return Extracted(status="failed", error=f"Unexpected fetch error: {exc.__class__.__name__}")
    return extract_from_html(html, url)


# --------------------------------------------------------------- bookmarks ----
@dataclass
class BookmarkMeta:
    """Light metadata for a bookmarked URL. `body_text` is transient (fed to the
    AI for a summary + tags) and never persisted."""
    status: str  # 'extracted' | 'failed'
    title: str | None = None
    source: str | None = None       # site name
    publish_date: str | None = None
    description: str | None = None   # meta/OG description
    favicon_url: str | None = None
    body_text: str | None = None
    error: str | None = None


def _favicon_url(html: str, url: str) -> str:
    """Prefer a declared <link rel="icon">; fall back to /favicon.ico at the host."""
    for m in re.finditer(r"<link\b[^>]*>", html, re.IGNORECASE):
        tag = m.group(0)
        if not re.search(r'rel\s*=\s*["\'][^"\']*\bicon\b', tag, re.IGNORECASE):
            continue
        href = re.search(r'href\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if href:
            return urljoin(url, href.group(1))
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/favicon.ico"


def metadata_from_html(html: str, url: str) -> BookmarkMeta:
    """Pure: derive bookmark metadata from HTML (no network) — testable via fixtures."""
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = getattr(meta, "title", None) if meta else None
    source = (getattr(meta, "sitename", None) or getattr(meta, "hostname", None)) if meta else None
    publish_date = getattr(meta, "date", None) if meta else None
    description = getattr(meta, "description", None) if meta else None
    body = trafilatura.extract(html, url=url, output_format="markdown", favor_recall=True)
    return BookmarkMeta(
        status="extracted",
        title=title,
        source=source,
        publish_date=publish_date,
        description=description,
        favicon_url=_favicon_url(html, url),
        body_text=(body or None),
    )


def fetch_metadata(url: str, *, fetcher=fetch_html) -> BookmarkMeta:
    """Fetch a URL once and derive light bookmark metadata. Failure-tolerant: a
    page we can't reach still yields a usable bookmark (status='failed', no title
    — the caller falls back to the URL host)."""
    try:
        html = fetcher(url)
    except Exception as exc:  # noqa: BLE001 - a bad URL must not block bookmarking
        parts = urlsplit(url)
        favicon = f"{parts.scheme}://{parts.netloc}/favicon.ico" if parts.netloc else None
        return BookmarkMeta(status="failed", favicon_url=favicon, error=exc.__class__.__name__)
    return metadata_from_html(html, url)
