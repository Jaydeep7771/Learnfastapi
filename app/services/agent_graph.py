"""LangGraph agent: Router -> (Tool | Synthesize) -> END, with an execution trace.

Nodes are plain async functions over a TypedDict state. Each returns a PARTIAL
state dict; LangGraph merges it (list channels append, scalars overwrite).

If langgraph is not installed the same node functions are driven by a tiny local
runner (`_fallback_run`) that honours the identical conditional edge, so the
endpoint, the trace and the JSON shape never change.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Literal, TypedDict

from app.services.llm import acomplete
from app.services.rag import backend_name, build_prompt, retrieve


def _append(left: list[Any], right: list[Any]) -> list[Any]:
    """Reducer for an accumulating channel."""
    return (left or []) + (right or [])


class AgentState(TypedDict, total=False):
    question: str
    route: Literal["tool", "direct"]
    reason: str
    tool_name: str | None
    tool_output: list[dict[str, Any]]
    answer: str
    trace: Annotated[list[dict[str, Any]], _append]


# --------------------------------------------------------------- tools

RETRIEVAL_HINTS = (
    "doc", "document", "pdf", "according", "source", "cite", "report",
    "policy", "spec", "paper", "file", "ingested", "says",
)
STATUS_HINTS = ("status", "health", "uptime", "version", "is the api", "backend")


async def tool_vector_search(question: str) -> list[dict[str, Any]]:
    hits = await retrieve(question, k=4)
    return [
        {"source": h["source"], "chunk": h["chunk"], "score": h["score"], "text": h["text"]}
        for h in hits
    ]


async def tool_service_status(_: str) -> list[dict[str, Any]]:
    return [
        {
            "source": "live:status",
            "chunk": 0,
            "score": 1.0,
            "text": f"API healthy at {time.strftime('%Y-%m-%d %H:%M:%S')}; "
            f"retrieval backend = {backend_name()}.",
        }
    ]


TOOLS = {"vector_search": tool_vector_search, "service_status": tool_service_status}


# --------------------------------------------------------------- nodes


async def router_node(state: AgentState) -> AgentState:
    """Planner. Deterministic heuristic here so the decision is inspectable;
    swap in a structured-output LLM call and nothing downstream changes."""
    started = time.perf_counter()
    q = state["question"].lower()

    if any(h in q for h in STATUS_HINTS):
        route, tool, reason = "tool", "service_status", "question asks about live service state"
    elif any(h in q for h in RETRIEVAL_HINTS) or len(q.split()) > 6:
        route, tool, reason = "tool", "vector_search", "question likely needs grounded evidence"
    else:
        route, tool, reason = "direct", None, "short conversational turn; no evidence needed"

    return {
        "route": route,
        "tool_name": tool,
        "reason": reason,
        "trace": [
            {
                "node": "router",
                "decision": route,
                "tool": tool,
                "why": reason,
                "ms": round((time.perf_counter() - started) * 1000, 2),
            }
        ],
    }


async def tool_node(state: AgentState) -> AgentState:
    started = time.perf_counter()
    name = state.get("tool_name") or "vector_search"
    output = await TOOLS[name](state["question"])
    return {
        "tool_output": output,
        "trace": [
            {
                "node": "tool",
                "tool": name,
                "results": len(output),
                "top_score": output[0]["score"] if output else None,
                "ms": round((time.perf_counter() - started) * 1000, 2),
            }
        ],
    }


async def synthesize_node(state: AgentState) -> AgentState:
    started = time.perf_counter()
    hits = state.get("tool_output") or []
    prompt = (
        build_prompt(state["question"], hits)
        if hits
        else f"Answer concisely.\n\nQUESTION: {state['question']}\nANSWER:"
    )
    answer = await acomplete(prompt)
    return {
        "answer": answer,
        "trace": [
            {
                "node": "synthesize",
                "grounded": bool(hits),
                "context_chunks": len(hits),
                "ms": round((time.perf_counter() - started) * 1000, 2),
            }
        ],
    }


def route_decision(state: AgentState) -> Literal["tool", "synthesize"]:
    """Conditional edge: the planner's choice, read back out of the state."""
    return "tool" if state.get("route") == "tool" else "synthesize"


# --------------------------------------------------------------- graph

_compiled: Any | None = None


def build_graph() -> Any | None:
    global _compiled
    if _compiled is not None:
        return _compiled
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return None

    g = StateGraph(AgentState)
    g.add_node("router", router_node)
    g.add_node("tool", tool_node)
    g.add_node("synthesize", synthesize_node)

    g.add_edge(START, "router")
    g.add_conditional_edges(
        "router", route_decision, {"tool": "tool", "synthesize": "synthesize"}
    )
    g.add_edge("tool", "synthesize")  # tool results always flow back in -> the cycle
    g.add_edge("synthesize", END)

    _compiled = g.compile()
    return _compiled


async def _fallback_run(question: str) -> AgentState:
    state: AgentState = {"question": question, "trace": []}
    for node in (router_node,):
        state = {**state, **_merge(state, await node(state))}
    if route_decision(state) == "tool":
        state = {**state, **_merge(state, await tool_node(state))}
    state = {**state, **_merge(state, await synthesize_node(state))}
    return state


def _merge(state: AgentState, update: AgentState) -> AgentState:
    out = dict(update)
    if "trace" in update:
        out["trace"] = _append(list(state.get("trace", [])), list(update["trace"]))
    return out  # type: ignore[return-value]


async def run_agent(question: str) -> dict[str, Any]:
    graph = build_graph()
    started = time.perf_counter()
    state = (
        await graph.ainvoke({"question": question, "trace": []})
        if graph is not None
        else await _fallback_run(question)
    )
    return {
        "question": question,
        "answer": state.get("answer", ""),
        "route": state.get("route"),
        "reason": state.get("reason"),
        "citations": [
            {"source": h["source"], "chunk": h["chunk"], "score": h["score"]}
            for h in state.get("tool_output") or []
        ],
        "trace": state.get("trace", []),
        "engine": "langgraph" if graph is not None else "fallback-runner",
        "total_ms": round((time.perf_counter() - started) * 1000, 2),
    }
