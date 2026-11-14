"""Runtime configuration, read from the environment."""
from __future__ import annotations

import os
from pathlib import Path


def db_path() -> str:
    """Path to the SQLite database file.

    Defaults to ./trove.db for local dev; the container sets TROVE_DB_PATH to a
    location on the persistent volume (e.g. /data/trove.db).
    """
    return os.environ.get("TROVE_DB_PATH", str(Path(__file__).resolve().parent.parent / "trove.db"))


def enrich_model() -> str:
    return os.environ.get("TROVE_ENRICH_MODEL", "claude-haiku-4-5")


def anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


def static_dir() -> str | None:
    """Directory holding the built React SPA, if present (set in the container)."""
    return os.environ.get("TROVE_STATIC_DIR")


def feed_poll_seconds() -> int:
    return int(os.environ.get("TROVE_FEED_POLL_SECONDS", "1800"))  # 30 min


def feed_age_days() -> int:
    return int(os.environ.get("TROVE_FEED_AGE_DAYS", "30"))


def feed_age_sweep_seconds() -> int:
    return int(os.environ.get("TROVE_FEED_AGE_SWEEP_SECONDS", "3600"))  # hourly


# ---- X (Twitter) ----
# Two ways to pull posts. The official X API v2 (pay-per-use; set a bearer token)
# gives threads, media, and full long-form text. Without one, an RSS bridge you
# run (RSSHub, Nitter, …) works too: set a URL template containing {handle}.
def x_bearer_token() -> str | None:
    return os.environ.get("TROVE_X_BEARER_TOKEN") or None


def x_rss_template() -> str | None:
    return os.environ.get("TROVE_X_RSS_TEMPLATE") or None


def x_api_base() -> str:
    return os.environ.get("TROVE_X_API_BASE", "https://api.x.com/2")


def x_poll_seconds() -> int:
    return int(os.environ.get("TROVE_X_POLL_SECONDS", "3600"))  # hourly — API reads are billed


def x_max_results() -> int:
    """Posts requested per poll (API allows 5–100)."""
    return max(5, min(100, int(os.environ.get("TROVE_X_MAX_RESULTS", "50"))))


# ---- Discovery ----
# Suggests blogs and X accounts with one Claude call. Runs only when
# you ask (it isn't on a schedule), so a more capable model than enrichment's is fine.
def discover_model() -> str:
    return os.environ.get("TROVE_DISCOVER_MODEL", "claude-opus-5-5")


def discover_effort() -> str:
    return os.environ.get("TROVE_DISCOVER_EFFORT", "medium")

