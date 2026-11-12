# FastAPI Mastery — runnable reference project

Production FastAPI patterns plus RAG and LangGraph agents, managed entirely with **uv** on macOS (Apple Silicon, zsh, Python 3.13).

Open **[`index.html`](index.html)** in Safari or Chrome for the interactive workbook — 13 lessons, each one *What / Why / How*, with the request-lifecycle concurrency simulator. Every snippet in it is real code from `app/`.

---

## Quick start

```zsh
brew install uv            # one binary: interpreters, locking, execution
cd fastapi-mastery
cp .env.example .env       # JWT secret, DB URL, optional OPENAI_API_KEY
uv sync                    # creates .venv from the lockfile — never activate it
uv run fastapi dev app/main.py
```

Then open <http://127.0.0.1:8000/docs>.

> **No `pip`, no `poetry`, no `source .venv/bin/activate`.** Prefix everything with `uv run`.

### Optional: Module 2 AI stack

The AI endpoints run **without any API key** in deterministic mock mode (in-process cosine store + stub LLM), so `/ai/stream`, `/rag/*` and `/agent/chat` all work offline. For live embeddings and generation:

```zsh
uv add langchain langchain-openai langchain-community langgraph chromadb pypdf
echo 'OPENAI_API_KEY="sk-..."' >> .env
```

Every AI response reports which backend answered (`"backend"` / `"engine"`).

---

## Daily commands

| Task | Command |
| --- | --- |
| Sync env to lockfile | `uv sync` |
| Run dev server | `uv run fastapi dev app/main.py` |
| Run tests | `uv run pytest -q` |
| Lint + format | `uv run ruff check . --fix && uv run ruff format .` |
| Add a dependency | `uv add <pkg>` |
| Add a dev dependency | `uv add --dev <pkg>` |
| Drop into the env | `uv run python` |
| Production-ish run | `uv run uvicorn app.main:app --workers 4` |

---

## Layout

```
app/
├── main.py              # assembly: lifespan, middleware, handlers, include_router
├── dependencies.py      # SessionDep, CurrentUser, Pagination, require_role()
├── core/
│   ├── config.py        # pydantic-settings, @lru_cache
│   ├── security.py      # Argon2 (pwdlib) + JWT access/refresh (PyJWT)
│   ├── problems.py      # RFC 9457 Problem Details handlers
│   └── middleware.py    # pure-ASGI timing + correlation id
├── db/session.py        # async engine, sessionmaker, get_session()
├── models/              # User, Item  (database truth)
├── schemas/             # Pydantic in/out  (wire truth)
├── routers/             # auth · items · concurrency lab · ai
└── services/            # items · heavy · llm · rag · agent_graph
tests/test_api.py        # end-to-end over ASGI transport — no live server needed
```

**The rule:** imports point downward only. Routers import services; services never import routers.

---

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | liveness + current AI mode |
| POST | `/auth/register` | 201, returns `UserRead` (never the hash) |
| POST | `/auth/login` | **form-encoded** OAuth2 password grant → access + refresh |
| POST | `/auth/refresh` | refresh token → new pair |
| GET | `/auth/me` · `/auth/admin-only` | authn vs authz (401 vs 403) |
| POST/GET/PATCH/DELETE | `/items[/{id}]` | async CRUD, pagination, filters; DELETE is admin-only |
| GET | `/lab/async-good` · `async-bad` · `sync-def` · `to-thread` | concurrency lab |
| GET | `/lab/cpu-in-thread` · `cpu-in-process` | GIL vs real parallelism |
| POST | `/lab/background` | `BackgroundTasks`, response first |
| POST | `/ai/stream` | SSE token stream (`text/event-stream`) |
| POST | `/rag/ingest` · `/rag/query` · GET `/rag/retrieve` | chunk → embed → retrieve → ground |
| POST | `/agent/chat` | LangGraph StateGraph + execution trace |

---

## curl cheat sheet

### Auth

```zsh
curl -s localhost:8000/health | python3 -m json.tool
```

```zsh
curl -s -X POST localhost:8000/auth/register -H "content-type: application/json" \
  -d '{"email":"admin@example.com","password":"Sup3rSecret!","role":"admin"}'
```

The OAuth2 password flow is **form-encoded**, and the field is `username` even though it holds an email:

```zsh
TOKEN=$(curl -s -X POST localhost:8000/auth/login \
  -d "username=admin@example.com&password=Sup3rSecret!" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
```

```zsh
curl -s localhost:8000/auth/me -H "authorization: Bearer $TOKEN" | python3 -m json.tool
```

### CRUD

```zsh
curl -s -X POST localhost:8000/items -H "authorization: Bearer $TOKEN" \
  -H "content-type: application/json" \
  -d '{"name":"Mechanical keyboard","price_cents":12900}' | python3 -m json.tool
```

```zsh
curl -s "localhost:8000/items?limit=5&q=key&min_price=1000" -H "authorization: Bearer $TOKEN"
```

PATCH touches only the fields you send:

```zsh
curl -s -X PATCH localhost:8000/items/1 -H "authorization: Bearer $TOKEN" \
  -H "content-type: application/json" -d '{"price_cents":9900}'
```

### Concurrency lab

Six parallel requests, non-blocking — all finish in about one second:

```zsh
seq 6 | xargs -P6 -I{} curl -s -o /dev/null -w "%{time_total}\n" "localhost:8000/lab/async-good?seconds=1"
```

The same six against a blocking `async def` — they serialize to 1, 2, 3, 4, 5, 6 seconds:

```zsh
seq 6 | xargs -P6 -I{} curl -s -o /dev/null -w "%{time_total}\n" "localhost:8000/lab/async-bad?seconds=1"
```

While that runs, in another tab — this is the whole lesson:

```zsh
time curl -s localhost:8000/health
```

### Streaming, RAG, agent

`-N` disables curl's buffering so you see frames arrive:

```zsh
curl -N -X POST localhost:8000/ai/stream -H "content-type: application/json" \
  -d '{"prompt":"Explain backpressure in two sentences."}'
```

```zsh
curl -s -X POST localhost:8000/rag/ingest -F "file=@README.md" | python3 -m json.tool
```

Inspect retrieval before blaming the prompt:

```zsh
curl -s "localhost:8000/rag/retrieve?q=how%20do%20I%20run%20the%20app&k=3" | python3 -m json.tool
```

```zsh
curl -s -X POST localhost:8000/rag/query -H "content-type: application/json" \
  -d '{"question":"How do I start the dev server?","k":4}' | python3 -m json.tool
```

```zsh
curl -s -X POST localhost:8000/agent/chat -H "content-type: application/json" \
  -d '{"message":"According to the document, how do I run the server?"}' | python3 -m json.tool
```

### Observability

```zsh
curl -si localhost:8000/health | grep -iE "x-correlation-id|x-process-time"
```

Errors come back as RFC 9457 Problem Details, carrying the correlation id you sent:

```zsh
curl -s localhost:8000/items/999999 -H "authorization: Bearer $TOKEN" \
  -H "x-correlation-id: trace-abc-123" | python3 -m json.tool
```

---

## `.env`

Copy `.env.example` to `.env`. Generate a real secret with:

```zsh
openssl rand -hex 32
```

| Key | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite+aiosqlite:///./app.db` | async SQLite; swap for `postgresql+asyncpg://…` |
| `JWT_SECRET` | dev placeholder | **change it**; keep it out of git |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | short by design |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | the revocable half |
| `OPENAI_API_KEY` | empty | empty ⇒ AI endpoints run in mock mode |
| `CHROMA_DIR` | `./chroma_data` | persisted vectors |

---

## Tests

```zsh
uv run pytest -q
```

Seven end-to-end tests run the real app over `httpx.ASGITransport` — no server process, no network. They cover CRUD round-trip, PATCH semantics, 401 vs 403, Problem Details on validation failure, the concurrency lab, RAG ingest/query with citations, and the agent's `router → tool → synthesize` trace.

## Known gaps (deliberate)

`create_all()` instead of Alembic · SQLite instead of Postgres · HS256 with no revocation list · no rate limiting · in-process background tasks. The final section of `index.html` lists what each one becomes in production.
