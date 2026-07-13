"""The lens query engine — keyword + topic + metadata matching.

Expands an interest ("AI") into related terms so a lens surfaces conceptually
related items (LLM/agents/inference) even when they aren't literally tagged with
the query, then scores every item, weighting normalized-topic matches highest.
No embeddings — this leans on Phase 1's enrichment (topics, summary, claims).
"""
from __future__ import annotations

import re

from . import topics as topics_mod

# Query term (lowercased) -> related terms. Grows as the library grows; mirrors
# the normalized topic vocabulary so a lens spans a concept, not just a word.
EXPANSIONS: dict[str, list[str]] = {
    "ai": ["ai", "llm", "llms", "agent", "agents", "inference", "model", "models",
           "machine learning", "ml", "genai", "generative", "embedding", "neural",
           "transformer", "evals", "eval", "coding agent", "verification"],
    "agents": ["agent", "agents", "ai agents", "autonomous", "tool use"],
    "platform": ["platform", "platform engineering", "idp", "internal developer platform",
                 "developer platform", "golden path", "self-service", "dx",
                 "developer experience", "paved road", "onboarding"],
    "platform engineering": ["platform", "platform engineering", "idp", "golden path",
                             "self-service", "developer experience", "paved road"],
    "macro": ["macro", "yen", "jpy", "boj", "rates", "inflation", "economy", "fed", "currency"],
    "architecture": ["architecture", "eda", "event-driven", "event driven", "messaging",
                     "scale", "coupling", "microservices", "distributed", "systems"],
    "security": ["security", "vulnerability", "exploit", "auth", "authentication",
                 "encryption", "cve", "threat"],
    "career": ["career", "staff engineer", "staff-plus", "promotion", "leadership", "management"],
}


def expand(query: str) -> set[str]:
    """Return the set of match terms for a query (query words + canonical topic
    forms + related-term expansions)."""
    q = query.strip().lower()
    terms: set[str] = set()
    if not q:
        return terms
    # whole-phrase expansion (e.g. "platform engineering")
    terms.update(EXPANSIONS.get(q, []))
    terms.add(q)
    for word in re.findall(r"[a-z0-9][a-z0-9+.-]*", q):
        terms.add(word)
        canon = topics_mod.canonicalize(word)
        if canon:
            terms.add(canon.lower())
        terms.update(EXPANSIONS.get(word, []))
    return {t for t in terms if t}


def score_item(
    *, title: str | None, summary: str | None, category: str | None,
    claims: list[str], item_topics: list[str], terms: set[str],
) -> tuple[int, list[str]]:
    """Score one item against the expanded terms; return (score, matched_topics)."""
    tag_text = " | ".join(item_topics).lower()
    text = " ".join(filter(None, [title, summary, category, " ".join(claims)])).lower()
    score = 0
    matched: list[str] = []
    for term in terms:
        if term in tag_text:
            score += 3
            for topic in item_topics:
                if term in topic.lower():
                    matched.append(topic)
        elif term in text:
            score += 1
    # unique, preserve order
    seen: set[str] = set()
    matched_unique = [t for t in matched if not (t in seen or seen.add(t))]
    return score, matched_unique
