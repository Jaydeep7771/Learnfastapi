"""LLM access with a deterministic MOCK fallback.

WHY a fallback: the workbook must be runnable with zero API keys and zero network.
When OPENAI_API_KEY is empty (or langchain-openai is not installed) every AI
endpoint still streams and still returns the same shapes - just from a stub.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import get_settings


def get_chat_model() -> Any | None:
    """Returns a LangChain chat model, or None to signal mock mode."""
    s = get_settings()
    if not s.ai_live:
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None
    return ChatOpenAI(model=s.chat_model, api_key=s.openai_api_key, streaming=True)


def get_embeddings() -> Any | None:
    s = get_settings()
    if not s.ai_live:
        return None
    try:
        from langchain_openai import OpenAIEmbeddings
    except ImportError:
        return None
    return OpenAIEmbeddings(model=s.embedding_model, api_key=s.openai_api_key)


async def astream_tokens(prompt: str) -> AsyncIterator[str]:
    """Yield tokens as they arrive. Never collect into a string first - that is
    exactly what kills streaming latency (TTFT)."""
    model = get_chat_model()
    if model is None:
        for token in _mock_tokens(prompt):
            await asyncio.sleep(0.04)  # simulate inter-token latency
            yield token
        return

    async for chunk in model.astream(prompt):
        text = getattr(chunk, "content", "") or ""
        if text:
            yield text


async def acomplete(prompt: str) -> str:
    model = get_chat_model()
    if model is None:
        return "".join(_mock_tokens(prompt)).strip()
    result = await model.ainvoke(prompt)
    return getattr(result, "content", str(result))


def _mock_tokens(prompt: str) -> list[str]:
    head = prompt.strip().replace("\n", " ")[:160]
    sentence = (
        f"[mock] I received your prompt ({len(prompt)} chars). "
        f"Set OPENAI_API_KEY in .env for live generation. You asked: {head}"
    )
    return [w + " " for w in sentence.split(" ")]
