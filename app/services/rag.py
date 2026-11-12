"""RAG pipeline: chunk -> embed -> persist -> retrieve -> ground.

Backends, chosen at runtime:
  * ChromaDB + OpenAI embeddings when both are available (persisted in CHROMA_DIR)
  * an in-process cosine-similarity store over hashed bag-of-words vectors otherwise

The second one is not production retrieval - it exists so the endpoints, the
citations and the trade-offs are inspectable with no key and no network.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.services.llm import acomplete, get_embeddings

# ---------------------------------------------------------------- chunking

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """RecursiveCharacterTextSplitter when langchain is installed, else a faithful
    fallback: split on the biggest separator that fits, keep `overlap` chars of
    tail context so a sentence cut across a boundary is still retrievable."""
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=size,
            chunk_overlap=overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        return [c for c in splitter.split_text(text) if c.strip()]
    except ImportError:
        pass

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        window = text[start:end]
        if end < len(text):
            cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "))
            if cut > size * 0.5:
                end = start + cut + 1
                window = text[start:end]
        if window.strip():
            chunks.append(window.strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def extract_text(filename: str, raw: bytes) -> str:
    """PDF via pypdf when present; .md/.txt decoded directly."""
    if filename.lower().endswith(".pdf"):
        try:
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            return "\n\n".join((p.extract_text() or "") for p in reader.pages)
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "PDF ingestion needs pypdf: uv add pypdf"
            ) from exc
    return raw.decode("utf-8", errors="replace")


# ------------------------------------------------- fallback vector store

_DIM = 512
_TOKEN = re.compile(r"[a-z0-9]+")


def _hash_embed(text: str) -> list[float]:
    """Hashing trick: deterministic, dependency-free, good enough for keyword-ish
    similarity. Real embeddings capture semantics; this captures vocabulary."""
    vec = [0.0] * _DIM
    for tok in _TOKEN.findall(text.lower()):
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=4).digest(), "big")
        vec[h % _DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


@dataclass
class MemoryStore:
    """Cosine similarity over unit vectors == plain dot product."""

    texts: list[str] = field(default_factory=list)
    metas: list[dict[str, Any]] = field(default_factory=list)
    vectors: list[list[float]] = field(default_factory=list)

    def add(self, texts: list[str], metas: list[dict[str, Any]]) -> None:
        for t, m in zip(texts, metas, strict=True):
            self.texts.append(t)
            self.metas.append(m)
            self.vectors.append(_hash_embed(t))

    def search(self, query: str, k: int) -> list[tuple[str, dict[str, Any], float]]:
        if not self.vectors:
            return []
        qv = _hash_embed(query)
        scored = [
            (self.texts[i], self.metas[i], cosine(qv, self.vectors[i]))
            for i in range(len(self.vectors))
        ]
        scored.sort(key=lambda row: row[2], reverse=True)
        return scored[:k]

    def __len__(self) -> int:
        return len(self.texts)


_memory = MemoryStore()
_chroma: Any | None = None


def _get_chroma() -> Any | None:
    """Lazily build a persistent Chroma collection; None when unavailable."""
    global _chroma
    if _chroma is not None:
        return _chroma
    embeddings = get_embeddings()
    if embeddings is None:
        return None
    try:
        from langchain_chroma import Chroma
    except ImportError:
        try:
            from langchain_community.vectorstores import Chroma  # type: ignore
        except ImportError:
            return None
    s = get_settings()
    _chroma = Chroma(
        collection_name="workbook",
        embedding_function=embeddings,
        persist_directory=s.chroma_dir,
    )
    return _chroma


def backend_name() -> str:
    return "chromadb+openai" if _get_chroma() is not None else "in-memory-hashing"


# -------------------------------------------------------------- pipeline


async def ingest(filename: str, raw: bytes) -> dict[str, Any]:
    # Parsing is CPU-bound -> off the event loop.
    text = await asyncio.to_thread(extract_text, filename, raw)
    chunks = await asyncio.to_thread(split_text, text)
    if not chunks:
        raise ValueError("no extractable text in document")

    metas = [{"source": filename, "chunk": i} for i in range(len(chunks))]
    store = _get_chroma()
    if store is not None:
        await asyncio.to_thread(store.add_texts, chunks, metas)
        count = None
    else:
        _memory.add(chunks, metas)
        count = len(_memory)

    return {
        "source": filename,
        "characters": len(text),
        "chunks": len(chunks),
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "backend": backend_name(),
        "total_chunks_in_store": count,
    }


async def retrieve(query: str, k: int = 4) -> list[dict[str, Any]]:
    store = _get_chroma()
    if store is not None:
        hits = await asyncio.to_thread(store.similarity_search_with_score, query, k)
        return [
            {
                "text": doc.page_content,
                "source": doc.metadata.get("source"),
                "chunk": doc.metadata.get("chunk"),
                # Chroma returns DISTANCE (lower = closer); flip it for readability.
                "score": round(1.0 - float(score), 4),
            }
            for doc, score in hits
        ]
    return [
        {"text": t, "source": m.get("source"), "chunk": m.get("chunk"), "score": round(s, 4)}
        for t, m, s in _memory.search(query, k)
    ]


GROUNDED_PROMPT = """You answer strictly from the CONTEXT below.
If the context does not contain the answer, reply exactly: "Not in the provided sources."
Cite sources inline as [source#chunk].

CONTEXT:
{context}

QUESTION: {question}
ANSWER:"""


def build_prompt(question: str, hits: list[dict[str, Any]]) -> str:
    context = "\n\n".join(
        f"[{h['source']}#{h['chunk']}] {h['text']}" for h in hits
    ) or "(empty)"
    return GROUNDED_PROMPT.format(context=context, question=question)


async def query(question: str, k: int = 4) -> dict[str, Any]:
    hits = await retrieve(question, k)
    if not hits:
        return {
            "answer": "Nothing has been ingested yet - POST a document to /rag/ingest first.",
            "citations": [],
            "backend": backend_name(),
        }
    answer = await acomplete(build_prompt(question, hits))
    return {
        "answer": answer,
        "citations": [
            {"source": h["source"], "chunk": h["chunk"], "score": h["score"]} for h in hits
        ],
        "backend": backend_name(),
    }
