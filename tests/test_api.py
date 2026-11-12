"""End-to-end smoke tests over ASGI (no network, no server process)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

ADMIN = {"email": "admin@example.com", "password": "Sup3rSecret!", "role": "admin"}


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def auth_headers(client: AsyncClient) -> dict[str, str]:
    await client.post("/auth/register", json=ADMIN)
    res = await client.post(
        "/auth/login", data={"username": ADMIN["email"], "password": ADMIN["password"]}
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def test_health(client: AsyncClient):
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert "x-correlation-id" in res.headers


async def test_crud_roundtrip(client: AsyncClient):
    headers = await auth_headers(client)

    created = await client.post(
        "/items", json={"name": "Widget", "price_cents": 2599}, headers=headers
    )
    assert created.status_code == 201
    item = created.json()
    assert item["price_display"] == "$25.99"

    listed = await client.get("/items?limit=5", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    patched = await client.patch(
        f"/items/{item['id']}", json={"price_cents": 100}, headers=headers
    )
    assert patched.json()["name"] == "Widget"  # untouched by PATCH
    assert patched.json()["price_cents"] == 100

    deleted = await client.delete(f"/items/{item['id']}", headers=headers)
    assert deleted.status_code == 204


async def test_validation_returns_problem_details(client: AsyncClient):
    headers = await auth_headers(client)
    res = await client.post("/items", json={"name": "x"}, headers=headers)
    assert res.status_code == 422
    assert res.headers["content-type"].startswith("application/problem+json")
    assert res.json()["title"] == "Request validation failed"


async def test_unauthenticated_is_401(client: AsyncClient):
    assert (await client.get("/items")).status_code == 401


async def test_rbac_blocks_non_admin(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"email": "plain@example.com", "password": "Sup3rSecret!"},
    )
    res = await client.post(
        "/auth/login", data={"username": "plain@example.com", "password": "Sup3rSecret!"}
    )
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    assert (await client.get("/auth/admin-only", headers=headers)).status_code == 403


async def test_concurrency_lab(client: AsyncClient):
    res = await client.get("/lab/async-good?seconds=0")
    assert res.status_code == 200
    assert "elapsed_ms" in res.json()


async def test_rag_and_agent(client: AsyncClient):
    ingest = await client.post(
        "/rag/ingest",
        files={"file": ("notes.md", b"# Retries\n\nThe policy document says retry 3 times with jitter.", "text/markdown")},
    )
    assert ingest.status_code == 201
    assert ingest.json()["chunks"] >= 1

    q = await client.post("/rag/query", json={"question": "What does the policy document say about retries?"})
    assert q.status_code == 200
    assert q.json()["citations"]

    agent = await client.post(
        "/agent/chat", json={"message": "According to the document, how many retries?"}
    )
    body = agent.json()
    assert body["route"] == "tool"
    assert [t["node"] for t in body["trace"]] == ["router", "tool", "synthesize"]
