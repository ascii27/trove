"""Article extraction — server-side fetch + trafilatura (Readability-class).

Extraction is near-instant but not guaranteed, which is why the item can end in a
'failed' or 'partial' state (PRD S1, §11). Content is stored as Markdown; the
reader renders it. `extract_from_html` is pure (no network) so tests use fixtures.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

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
