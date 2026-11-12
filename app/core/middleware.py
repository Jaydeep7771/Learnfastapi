"""Pure-ASGI middleware: request timing + correlation IDs.

WHY raw ASGI instead of BaseHTTPMiddleware? BaseHTTPMiddleware pipes the response
through an anyio memory stream, which adds a task-group hop per request and can
buffer/stall StreamingResponse (our SSE endpoints). Raw ASGI only touches headers.
"""

import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CORRELATION_HEADER = b"x-correlation-id"


class CorrelationTimingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(CORRELATION_HEADER)
        correlation_id = incoming.decode() if incoming else uuid.uuid4().hex
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                elapsed_ms = (time.perf_counter() - started) * 1000
                headers = message.setdefault("headers", [])
                headers.append((CORRELATION_HEADER, correlation_id.encode()))
                headers.append((b"x-process-time-ms", f"{elapsed_ms:.2f}".encode()))
            await send(message)

        await self.app(scope, receive, send_wrapper)
