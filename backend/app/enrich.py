"""AI metadata enrichment — one Anthropic call per item, structured output.

Runs after extraction and never blocks reading (PRD F2). Uses Claude Haiku 4.5 by
default (cheap/fast; upgradeable via TROVE_ENRICH_MODEL). The Anthropic client is
injectable so tests mock it at this boundary — no live calls in the test suite.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import config

_MAX_CONTENT_CHARS = 12000

_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "1-2 sentence summary for skim/triage"},
        "topics": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-6 concise topic tags (e.g. 'AI', 'platform engineering')",
        },
        "category": {
            "type": "string",
            "description": "Content type",
            "enum": ["essay", "paper", "news", "docs", "analysis", "newsletter", "reference", "other"],
        },
        "source_type": {
            "type": "string",
            "description": "Credibility class for research",
            "enum": ["primary", "secondary", "analysis"],
        },
        "claims": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-4 key claims or takeaways, each a standalone assertion",
        },
    },
    "required": ["summary", "topics", "category", "source_type", "claims"],
    "additionalProperties": False,
}

_PROMPT = (
    "You are enriching a saved article for a personal research library. "
    "Read the article and produce metadata: a 1-2 sentence summary, 3-6 topic tags, "
    "a content category, a source type (primary = original source/data/first-hand; "
    "secondary = reporting/synthesis of others' work; analysis = opinion/argument/interpretation), "
    "and 2-4 key claims. Be concise and faithful to the text.\n\n"
    "Title: {title}\n\nArticle:\n{body}"
)


@dataclass
class EnrichResult:
    summary: str
    topics: list[str]
    category: str
    source_type: str
    claims: list[str]


def _default_client():
    import anthropic

    return anthropic.Anthropic()


def enrich(title: str | None, text: str, *, client=None, model: str | None = None) -> EnrichResult:
    import json

    client = client or _default_client()
    model = model or config.enrich_model()
    body = text[:_MAX_CONTENT_CHARS]
    prompt = _PROMPT.format(title=title or "(untitled)", body=body)

    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    raw = next(b.text for b in resp.content if getattr(b, "type", None) == "text")
    data = json.loads(raw)
    return EnrichResult(
        summary=data["summary"],
        topics=list(data.get("topics") or []),
        category=data["category"],
        source_type=data["source_type"],
        claims=list(data.get("claims") or []),
    )
