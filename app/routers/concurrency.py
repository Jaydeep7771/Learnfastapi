"""Concurrency lab: every variant the workbook's simulator visualises, runnable.

Hit each one 5x in parallel and compare wall-clock:

  seq 5 | xargs -P5 -I{} curl -s -o /dev/null -w "%{time_total}\n" \
      "http://127.0.0.1:8000/lab/async-good?seconds=1"
"""

import asyncio
import os
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Query, Request

from app.services.heavy import blocking_sleep, pbkdf2_digest

router = APIRouter(prefix="/lab", tags=["concurrency lab"])

Seconds = Annotated[float, Query(ge=0, le=5)]
Rounds = Annotated[int, Query(ge=10_000, le=2_000_000)]


def _stamp(mode: str, started: float, **extra: Any) -> dict[str, Any]:
    return {
        "mode": mode,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "pid": os.getpid(),
        "thread": asyncio.current_task().get_name() if asyncio.current_task() else None,
        **extra,
    }


@router.get("/async-good")
async def async_good(seconds: Seconds = 1.0) -> dict[str, Any]:
    """`async def` + awaited sleep. Yields to the event loop -> N requests take ~1x."""
    started = time.perf_counter()
    await asyncio.sleep(seconds)
    return _stamp("async def + await (non-blocking)", started)


@router.get("/async-bad")
async def async_bad(seconds: Seconds = 1.0) -> dict[str, Any]:
    """THE classic bug: blocking call inside `async def`.

    time.sleep never yields, so the single event-loop thread is frozen and EVERY
    other request in the process - including /health - waits. N requests ~ Nx.
    """
    started = time.perf_counter()
    blocking_sleep(seconds)
    return _stamp("async def + blocking call (event loop FROZEN)", started)


@router.get("/sync-def")
def sync_def(seconds: Seconds = 1.0) -> dict[str, Any]:
    """Plain `def`. FastAPI runs it in AnyIO's threadpool (40 workers by default),
    so blocking here is safe-ish and concurrent up to the worker count."""
    started = time.perf_counter()
    blocking_sleep(seconds)
    return _stamp("def -> AnyIO worker thread", started)


@router.get("/to-thread")
async def to_thread(seconds: Seconds = 1.0) -> dict[str, Any]:
    """Explicit offload of one blocking call, keeping the rest of the route async."""
    started = time.perf_counter()
    await asyncio.to_thread(blocking_sleep, seconds)
    return _stamp("async def + asyncio.to_thread", started)


@router.get("/cpu-in-thread")
async def cpu_in_thread(request: Request, rounds: Rounds = 400_000) -> dict[str, Any]:
    """CPU-bound in a thread: still serialised by the GIL. Threads fix I/O, not CPU."""
    started = time.perf_counter()
    digest = await asyncio.to_thread(pbkdf2_digest, b"payload", rounds)
    return _stamp("CPU-bound in a thread (GIL-bound)", started, digest=digest[:16])


@router.get("/cpu-in-process")
async def cpu_in_process(request: Request, rounds: Rounds = 400_000) -> dict[str, Any]:
    """CPU-bound in a separate process: true parallelism, at the cost of pickling
    arguments and ~tens of ms of IPC. The pool lives on app.state from lifespan."""
    started = time.perf_counter()
    pool: ProcessPoolExecutor = request.app.state.process_pool
    loop = asyncio.get_running_loop()
    digest = await loop.run_in_executor(pool, pbkdf2_digest, b"payload", rounds)
    return _stamp("CPU-bound in ProcessPoolExecutor", started, digest=digest[:16])


_AUDIT: list[dict[str, Any]] = []


@router.post("/background")
async def fire_and_forget(
    tasks: BackgroundTasks, seconds: Seconds = 1.0
) -> dict[str, Any]:
    """BackgroundTasks run AFTER the response is sent, in the same process.

    Good for audit logs and cache warms. Bad for anything that must survive a
    crash or a deploy - that needs a real queue (Celery / ARQ / Dramatiq).
    """
    started = time.perf_counter()

    def audit() -> None:
        blocking_sleep(seconds)
        _AUDIT.append({"at": time.time(), "slept": seconds})

    tasks.add_task(audit)
    return _stamp("response first, task after", started, queued=True)


@router.get("/background/log")
async def background_log() -> dict[str, Any]:
    return {"entries": _AUDIT[-10:], "count": len(_AUDIT)}
