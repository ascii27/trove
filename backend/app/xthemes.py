"""Theme grouping for X posts — one batched AI call for many short posts.

Enriching every post individually (summary, claims, …) would be wasteful for
280-character text, so posts instead get a single short *theme* label, assigned
in batches. Existing theme names are passed in so the model reuses them and the
"group by theme" view stays stable instead of fragmenting. The Anthropic client
is injectable (mocked in tests), mirroring enrich.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import config

BATCH_SIZE = 40
_MAX_POST_CHARS = 600

_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "theme": {"type": "string"},
                },
                "required": ["id", "theme"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["assignments"],
    "additionalProperties": False,
}

_PROMPT = (
    "You are grouping posts from X (Twitter) by theme for a calm personal reader. "
    "Give every post exactly one theme: 1-4 words, sentence case, broad enough that "
    "several posts could share it (e.g. 'AI agents', 'Startup fundraising', "
    "'Climate policy', 'Personal life'). Reuse an existing theme whenever one fits; "
    "only invent a new one when none does. Use 'Misc' for posts with no real subject.\n\n"
    "Existing themes: {existing}\n\nPosts:\n{posts}"
)


@dataclass
class ThemeInput:
    id: int
    author: str | None
    text: str


def _default_client():
    import anthropic

    return anthropic.Anthropic()


def _clean(theme: str) -> str | None:
    t = " ".join((theme or "").split()).strip(" .\"'")
    if not t:
        return None
    t = t[:40]
    return t[0].upper() + t[1:]


def classify(
    posts: list[ThemeInput], existing: list[str], *, client=None, model: str | None = None
) -> dict[int, str]:
    """Return {post id: theme}. Ids the model skips are simply absent."""
    if not posts:
        return {}
    client = client or _default_client()
    model = model or config.enrich_model()
    lines = [
        json.dumps({"id": p.id, "author": p.author or "", "text": p.text[:_MAX_POST_CHARS]}, ensure_ascii=False)
        for p in posts
    ]
    prompt = _PROMPT.format(
        existing=", ".join(existing) if existing else "(none yet)", posts="\n".join(lines)
    )
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    raw = next(b.text for b in resp.content if getattr(b, "type", None) == "text")
    data = json.loads(raw)
    # Fold case variants onto existing names so "ai agents" joins "AI agents".
    by_lower = {e.lower(): e for e in existing}
    wanted = {p.id for p in posts}
    out: dict[int, str] = {}
    for a in data.get("assignments") or []:
        pid, theme = a.get("id"), _clean(a.get("theme", ""))
        if pid in wanted and theme:
            theme = by_lower.setdefault(theme.lower(), theme)
            out[pid] = theme
    return out
