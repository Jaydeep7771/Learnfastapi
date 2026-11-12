"""Application assembly: lifespan, middleware, error handlers, routers."""

from collections.abc import AsyncIterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.middleware import CorrelationTimingMiddleware
from app.core.problems import register_exception_handlers
from app.db.session import engine, init_models
from app.routers import ai, auth, concurrency, items


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Everything expensive is created ONCE here and shared via app.state.

    WHY: building an httpx.AsyncClient or a process pool per request destroys
    connection reuse and leaks file descriptors. Teardown after `yield` runs on
    shutdown, so nothing is left dangling on SIGTERM.
    """
    settings = get_settings()
    await init_models()

    app.state.http = httpx.AsyncClient(timeout=10.0)
    app.state.process_pool = ProcessPoolExecutor(max_workers=2)
    app.state.ready = True
    try:
        yield
    finally:
        app.state.ready = False
        await app.state.http.aclose()
        app.state.process_pool.shutdown(cancel_futures=True)
        await engine.dispose()
        _ = settings


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    summary="Production FastAPI patterns + RAG & LangGraph agents, runnable with uv.",
    lifespan=lifespan,
)

app.add_middleware(CorrelationTimingMiddleware)
register_exception_handlers(app)

app.include_router(auth.router)
app.include_router(items.router)
app.include_router(concurrency.router)
app.include_router(ai.router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, Any]:
    """Stays responsive under load - unless something blocks the event loop.
    Hammer /lab/async-bad and watch this endpoint stall. That is the lesson."""
    return {
        "status": "ok",
        "ready": getattr(app.state, "ready", False),
        "ai_mode": "live" if settings.ai_live else "mock",
    }
