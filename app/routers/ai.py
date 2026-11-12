"""Streaming, RAG and agent endpoints (Module 2)."""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, File, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.problems import AppError
from app.services import rag
from app.services.agent_graph import run_agent
from app.services.llm import astream_tokens

router = APIRouter(tags=["ai"])

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)


class RagQuery(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    k: int = Field(default=4, ge=1, le=10)


class AgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


def sse(event: str, data: dict[str, Any] | str) -> str:
    """One SSE frame. The blank line terminator is mandatory - without it the
    browser's EventSource buffers forever and you will swear streaming is broken."""
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/ai/stream")
async def stream_chat(payload: ChatRequest, request: Request) -> StreamingResponse:
    """Token-by-token SSE.

    Three things make this actually stream:
      1. an async GENERATOR (yield per token, never build the full string)
      2. media_type text/event-stream
      3. X-Accel-Buffering: no, so nginx/proxies do not re-buffer it
    """

    async def gen() -> AsyncIterator[str]:
        yield sse("start", {"model": get_settings().chat_model})
        try:
            async for token in astream_tokens(payload.prompt):
                if await request.is_disconnected():
                    break  # client closed the tab - stop paying for tokens
                yield sse("token", {"t": token})
            yield sse("done", {"ok": True})
        except Exception as exc:  # errors mid-stream cannot change the status code
            yield sse("error", {"message": str(exc)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/rag/ingest", status_code=status.HTTP_201_CREATED)
async def rag_ingest(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    """Upload a .pdf / .md / .txt -> chunk -> embed -> persist."""
    raw = await file.read()
    if not raw:
        raise AppError("Uploaded file is empty", status_code=400, title="Empty upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AppError(
            f"File exceeds {MAX_UPLOAD_BYTES // 1024 // 1024} MB",
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            title="Upload too large",
        )
    try:
        return await rag.ingest(file.filename or "upload.txt", raw)
    except (ValueError, RuntimeError) as exc:
        raise AppError(str(exc), status_code=422, title="Ingestion failed") from exc


@router.post("/rag/query")
async def rag_query(payload: RagQuery) -> dict[str, Any]:
    """Semantic search -> grounded prompt -> answer + citations."""
    return await rag.query(payload.question, payload.k)


@router.get("/rag/retrieve")
async def rag_retrieve(
    q: Annotated[str, Query(min_length=2)], k: Annotated[int, Query(ge=1, le=10)] = 4
) -> dict[str, Any]:
    """Retrieval only - inspect what the LLM would have been handed."""
    hits = await rag.retrieve(q, k)
    return {"query": q, "backend": rag.backend_name(), "hits": hits}


@router.post("/agent/chat")
async def agent_chat(payload: AgentRequest) -> dict[str, Any]:
    """LangGraph StateGraph run: structured answer + per-node execution trace."""
    return await run_agent(payload.message)
