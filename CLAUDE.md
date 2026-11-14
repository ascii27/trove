# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Trove is

A personal read-later, research, and feed-reading tool (self-hosted, single user).

- **Phase 1** — Pocket replacement: capture a URL → server-side extraction → calm typography-first reader → AI metadata (summary, topics, source type, key claims) → read/unread + delete.
- **Phase 2a (Feeds)** — the second, "streamed" lane: add RSS/Atom feeds (paste a feed URL *or* a site URL and it auto-discovers the feed), a background poller pulls new items in as `lane='feed'`, the newest 10 per poll are fetched and extracted while the rest are `deferred` (fetch on first open), no feed item is enriched until you open it (`enrichment_status='deferred'`, so polling spends no AI tokens), unread feed items auto-archive after 30 days, and you can promote (save) a feed item into the Saved lane. Lanes stay strictly separate.

- **Phase 2b (Lens)** — the "read about X" query surface: a live query bar expands an interest into related terms (`lens.py`) and scores every non-archived item across **both lanes** — normalized topics weighted highest, then title/summary/claims/category — returning ranked, cross-lane results tagged Saved/Feed with matched topics highlighted in the reader. Keyword + topic + metadata matching (no embeddings). `GET /api/lens?q=…`. Ephemeral; "save as collection" is 2c.

- **Phase 2c (Collections)** — persist a lens as a durable research collection: a curated, revisitable set of items (an item can belong to several). Two new tables (`collections`, `item_collections`). "Save as collection" from an active lens snapshots its results in; the reader's "Add to collection" popover toggles membership and creates new collections; a Research-collections group nests under Saved. `POST/GET/DELETE /api/collections`, add/remove item endpoints; item detail carries `collection_ids`. The saved `query` is stored for a future "refresh from lens."

- **X (Twitter) lane** — follow people on X (`lane='x'`, table `x_accounts`) and read their posts as a calm, blog-style stream grouped by **date** (default), **theme**, or **tag**. `xsource.py` pulls posts either from the official X API v2 (`TROVE_X_BEARER_TOKEN`; gives threads, long-form text, images) or from an RSS bridge you run (`TROVE_X_RSS_TEMPLATE`, e.g. RSSHub/Nitter, URL with `{handle}`). An author's self-thread is stitched into one item keyed by conversation id (`items.post_id`); later parts are appended. Posts are never enriched per item (`enrichment_status='skipped'`); instead `xthemes.py` assigns a short `theme` to batches of 40 in one Haiku call, reusing existing theme names (worker maintenance pass; you can override a theme by hand). Posts are ordinary items, so tags (`/api/items/{id}/tags`) and highlights reuse the existing endpoints. Unread posts auto-archive after `TROVE_FEED_AGE_DAYS` unless tagged/highlighted; unfollowing keeps tagged/highlighted posts. API: `/api/x/status`, `/api/x/accounts` (GET/POST/DELETE, `/{id}/refresh`), `/api/x/posts`, `/api/x/posts/read`, `PUT /api/x/posts/{id}/theme`. Data ops live in `xstore.py`; UI in `XStream.tsx` + `xgroup.ts`.

- **Discover** — suggests blogs and X accounts to follow. `discover.py` makes one on-demand Claude call (`TROVE_DISCOVER_MODEL`, default `claude-haiku-5-5` at `low` effort — in a live comparison it picked as well as Sonnet/Opus for ~0.25¢ a search vs ~9¢ for Opus medium) with structured JSON output; the prompt carries an interest profile built from the library (`discoverstore.build_profile`: topics weighted by saved/read/highlighted/collected, followed feeds and X accounts, X themes, collections, recent saves) and optional free-text context ("I'm interested in wine"), which then sets the subject while the profile only signals taste. The model over-asks (12 blogs, 10 people) and Trove verifies instead of trusting: each blog must resolve to a non-empty RSS/Atom feed via `feedfetch` (falling back to common paths like `/feed/`) whose newest post is under `STALE_DAYS` old, handles must be valid, and anything already followed or previously suggested is filtered (unique `(kind, key)` on `suggestions`, so dismissed ones never return); the first 8 of each kind are kept. No web search tool: in live runs Opus 5.5 routed searches through code execution, couldn't read the results, and returned one pick or none. Runs take about a minute, so `POST /api/discover` (202) records a `discovery_runs` row and runs it in a background thread; the UI polls `GET /api/discover`, which also returns the last 10 runs with what each did (`proposed` by the model, `passed` checks, `found` new, token usage) so the history can say why a search came back empty; a restart fails any run left `running`. Follow (`POST /api/discover/suggestions/{id}/follow`) reuses the add-feed / follow-X routes; `/dismiss` hides one for good. UI in `Discover.tsx`.

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

`ANTHROPIC_API_KEY` (enrichment), `TROVE_ENRICH_MODEL` (default `claude-haiku-4-5`), `TROVE_DB_PATH` (default `./trove.db`; container uses `/data/trove.db`), `TROVE_STATIC_DIR` (built SPA dir; set in the container), `TROVE_DISABLE_WORKER=1` (tests only — skips the background worker). Feed poller tuning (all in `config.py`): `TROVE_FEED_POLL_SECONDS` (default 1800 / 30 min), `TROVE_FEED_AGE_DAYS` (default 30 — unread feed items auto-archive past this), `TROVE_FEED_AGE_SWEEP_SECONDS` (default 3600 / hourly). X: `TROVE_X_BEARER_TOKEN` (X API v2; reads are billed per post) or `TROVE_X_RSS_TEMPLATE` (bridge URL containing `{handle}`), `TROVE_X_POLL_SECONDS` (default 3600), `TROVE_X_MAX_RESULTS` (posts per poll, 5–100, default 50), `TROVE_X_API_BASE` (tests/mocks). Discover: `TROVE_DISCOVER_MODEL` (default `claude-haiku-5-5`), `TROVE_DISCOVER_EFFORT` (default `low`).

## Conventions

- Content is stored as **Markdown** in `items.content_text` (not HTML); the reader renders it client-side.
- Extraction failures are terminal with a user-facing message + manual retry (`POST /api/items/{id}/retry`); enrichment failures auto-retry up to `store.MAX_ATTEMPTS`, then mark `enrichment_status='failed'` without blocking reading.
- UI voice: active voice, sentence case, buttons name the action, errors say what happened and how to fix, empty states invite.
