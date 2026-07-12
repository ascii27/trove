"""FastAPI application: API + background worker + built SPA.

Access is gated by the exe.dev platform (private VM), so there is no app-level
auth here.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config, db
from .routes import router
from .worker import Worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    worker = None
    # Tests set TROVE_DISABLE_WORKER=1 so capture doesn't trigger real fetch/enrich.
    if os.environ.get("TROVE_DISABLE_WORKER") != "1":
        worker = Worker()
        worker.start()
    app.state.worker = worker
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Trove", version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    static = config.static_dir()
    if static and os.path.isdir(static):
        # Mounted last so /api/* routes take precedence. html=True serves index.html.
        app.mount("/", StaticFiles(directory=static, html=True), name="spa")

    return app


app = create_app()
