"""Topic (tag) normalization — the PRD's design-critical dependency.

Topics must resolve to a controlled vocabulary, or interest-lenses and filters
(Phase 2) fragment. Two steps: a growable synonym map folds known variants onto a
canonical display name, and storage dedupes case-insensitively (unique index on
name COLLATE NOCASE), so "AI" / "artificial intelligence" / "ML" become one tag.
"""
from __future__ import annotations

import re
import sqlite3

# Known variant (lowercased) -> canonical display name. Grow as the library grows.
SYNONYMS: dict[str, str] = {
    "ai": "AI",
    "a.i.": "AI",
    "artificial intelligence": "AI",
    "ml": "AI",
    "machine learning": "AI",
    "llm": "AI",
    "llms": "AI",
    "large language model": "AI",
    "large language models": "AI",
    "genai": "AI",
    "generative ai": "AI",
    "agents": "AI agents",
    "ai agent": "AI agents",
    "dx": "developer experience",
    "developer experience": "developer experience",
    "idp": "internal developer platform",
    "internal developer platform": "internal developer platform",
    "platform engineering": "platform engineering",
    "eda": "event-driven architecture",
    "event driven architecture": "event-driven architecture",
    "event-driven architecture": "event-driven architecture",
}


def canonicalize(raw: str) -> str | None:
    """Return the canonical display name for a raw topic, or None if empty."""
    key = re.sub(r"\s+", " ", raw.strip().lower())
    if not key:
        return None
    return SYNONYMS.get(key, raw.strip())


def upsert_topic(conn: sqlite3.Connection, name: str) -> int:
    """Insert the topic if new (case-insensitively) and return its id."""
    conn.execute("INSERT OR IGNORE INTO topics (name) VALUES (?)", (name,))
    row = conn.execute(
        "SELECT id FROM topics WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    return row["id"]


def set_item_topics(conn: sqlite3.Connection, item_id: int, raw_topics: list[str]) -> None:
    """Normalize + attach a fresh set of topics to an item (replaces existing)."""
    conn.execute("DELETE FROM item_topics WHERE item_id = ?", (item_id,))
    seen: set[str] = set()
    for raw in raw_topics:
        name = canonicalize(raw)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        topic_id = upsert_topic(conn, name)
        conn.execute(
            "INSERT OR IGNORE INTO item_topics (item_id, topic_id) VALUES (?, ?)",
            (item_id, topic_id),
        )
