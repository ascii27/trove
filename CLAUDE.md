# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Trove is

A personal read-later, research, and feed-reading tool (self-hosted, single user).

- **Phase 1** — Pocket replacement: capture a URL → server-side extraction → calm typography-first reader → AI metadata (summary, topics, source type, key claims) → read/unread + delete.
- **Phase 2a (Feeds)** — the second, "streamed" lane: add RSS/Atom feeds (paste a feed URL *or* a site URL and it auto-discovers the feed), a background poller pulls new items in as `lane='feed'`, the newest 10 per poll get the full extract+enrich pipeline while the rest are `deferred` (load on first open), unread feed items auto-archive after 30 days, and you can promote (save) a feed item into the Saved lane. Lanes stay strictly separate.

- **Phase 2b (Lens)** — the "read about X" query surface: a live query bar expands an interest into related terms (`lens.py`) and scores every non-archived item across **both lanes** — normalized topics weighted highest, then title/summary/claims/category — returning ranked, cross-lane results tagged Saved/Feed with matched topics highlighted in the reader. Keyword + topic + metadata matching (no embeddings). `GET /api/lens?q=…`. Ephemeral; "save as collection" is 2c.

- **Phase 2c (Collections)** — persist a lens as a durable research collection: a curated, revisitable set of items (an item can belong to several). Two new tables (`collections`, `item_collections`). "Save as collection" from an active lens snapshots its results in; the reader's "Add to collection" popover toggles membership and creates new collections; a Research-collections group nests under Saved. `POST/GET/DELETE /api/collections`, add/remove item endpoints; item detail carries `collection_ids`. The saved `query` is stored for a future "refresh from lens."

Still to come: **3** cross-source synthesis (per-collection consensus/contradictions/gaps). The `lane` column, durable `jobs` worker, and canonical `topics` table were built in Phase 1 so these extend rather than rewrite.

Full design + rationale: `~/.claude/plans/staged-noodling-sparkle.md`. Product spec (external): `~/Downloads/files/trove-prd.md`; IA mockup: `~/Downloads/files/reader-ia-mockup.html`.

## Architecture (big picture)

One container serves everything at the root of the deploy URL:

- **Backend** (`backend/app/`): FastAPI. `main.py` wires the API router + serves the built SPA (`StaticFiles`, `TROVE_STATIC_DIR`) + starts the background `Worker` in `lifespan`. Access is gated by the exe.dev platform, so there is **no app-level auth**.
- **Capture → jobs → worker pipeline**: `routes.py` `POST /api/items` dedupes on a canonicalized URL (`urls.py`) and enqueues an `extract` job. The single-threaded `Worker` (`worker.py`) polls the durable `jobs` table and runs `process_job`, which calls `extract.fetch_and_extract` (httpx + trafilatura → Markdown) then enqueues an `enrich` job → `enrich.enrich` (Anthropic Claude Haiku 4.5, structured output). All item/job state transitions live in `store.py`. Content is readable before enrichment finishes; enrichment failure is non-blocking.
- **Tag normalization** (`topics.py`): AI topics fold through a synonym map + a case-insensitive unique index so "AI"/"ML"/"artificial intelligence" become one canonical tag. This is load-bearing for later interest-lenses.
- **Data** (`db.py`): stdlib `sqlite3`, WAL mode, one connection per request/op (no ORM). Schema in `SCHEMA`.
- **Frontend** (`frontend/src/`): React + Vite + TS. `App.tsx` holds all state and polls while any visible item is still extracting/enriching. Three panes: `Nav` / `List` / `Reader` (+ `Capture`). Reader renders extracted Markdown via `render.ts` (marked + DOMPurify). Auto-marks read on open (`markRead`) with a "Mark unread" affordance.

The seams are deliberate and testable: `extract.extract_from_html` is pure (fixtures, no network); the Anthropic client is injected into `enrich.enrich` (mocked in tests); `worker.process_job` takes injectable extract/enrich callables.

## Commands

Backend (from `backend/`, needs the venv):
```bash
uv venv --python 3.11 .venv && uv pip install -e ".[dev]"   # first-time setup
.venv/bin/pytest                    # run all backend tests
.venv/bin/pytest tests/test_worker.py::test_enrich_job_stores_metadata   # single test
# run locally (serves API; set TROVE_STATIC_DIR to serve the built SPA too):
TROVE_DB_PATH=/tmp/trove.db .venv/bin/uvicorn app.main:app --port 8000
```

Frontend (from `frontend/`):
```bash
npm install
npm test            # Vitest + React Testing Library
npm run build       # tsc typecheck + Vite build → dist/  (served by FastAPI in prod)
npm run dev         # Vite dev server (proxies /api to localhost:8000)
```

Container / deploy:
```bash
docker compose build && docker compose up -d     # one container, /data volume, port 8000
```

## Deploy target

Runs at **https://trove-app.exe.xyz** (exe.dev VM `trove-app`, private — gated by exe.dev auth; never `share set-public`). Deploy = rsync the tree to `~/trove` on the VM, then `docker compose up -d --build`, then `ssh exe.dev share port trove-app 8000`. The Anthropic API key lives in `~/trove/.env` on the VM (not committed). SQLite persists on the `trove-data` volume. See the memory notes and the plan file for the exact flow; a change isn't "done" until it's validated on the live host.

## Key environment variables

`ANTHROPIC_API_KEY` (enrichment), `TROVE_ENRICH_MODEL` (default `claude-haiku-4-5`), `TROVE_DB_PATH` (default `./trove.db`; container uses `/data/trove.db`), `TROVE_STATIC_DIR` (built SPA dir; set in the container), `TROVE_DISABLE_WORKER=1` (tests only — skips the background worker). Feed poller tuning (all in `config.py`): `TROVE_FEED_POLL_SECONDS` (default 1800 / 30 min), `TROVE_FEED_AGE_DAYS` (default 30 — unread feed items auto-archive past this), `TROVE_FEED_AGE_SWEEP_SECONDS` (default 3600 / hourly).

## Conventions

- Content is stored as **Markdown** in `items.content_text` (not HTML); the reader renders it client-side.
- Extraction failures are terminal with a user-facing message + manual retry (`POST /api/items/{id}/retry`); enrichment failures auto-retry up to `store.MAX_ATTEMPTS`, then mark `enrichment_status='failed'` without blocking reading.
- UI voice: active voice, sentence case, buttons name the action, errors say what happened and how to fix, empty states invite.
