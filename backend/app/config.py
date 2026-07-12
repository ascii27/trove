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
