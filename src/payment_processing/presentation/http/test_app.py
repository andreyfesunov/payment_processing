from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_processing.domain.models.types import JsonValue
from payment_processing.infrastructure.config.settings import Settings
from payment_processing.main import create_api
from payment_processing.version import read_version

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def client(
    database_url: str, sessions: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncClient]:
    app = create_api(Settings(api_key=SecretStr("test-key"), database_url=database_url))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as http:
            yield http


def payload() -> dict[str, JsonValue]:
    return {
        "amount": "12.50",
        "currency": "RUB",
        "description": "Order",
        "metadata": {"order": 123},
        "webhook_url": "https://example.com/hook",
    }


async def test_create_get_replay_and_conflict(client: AsyncClient) -> None:
    headers = {"Idempotency-Key": "order-123"}
    response = await client.post("/api/v1/payments", json=payload(), headers=headers)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["created_at"].endswith("Z")
    fetched = await client.get(f"/api/v1/payments/{body['payment_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["amount"] == "12.50"
    assert fetched.json()["metadata"] == {"order": 123}
    assert fetched.json()["processed_at"] is None
    replay = await client.post("/api/v1/payments", json=payload(), headers=headers)
    assert replay.status_code == 202
    assert replay.json() == body
    changed = {**payload(), "amount": "13"}
    conflict = await client.post("/api/v1/payments", json=changed, headers=headers)
    assert conflict.status_code == 409


@pytest.mark.parametrize(
    "path", ["/health", "/docs", "/redoc", "/openapi.json", "/api/v1/payments"]
)
async def test_all_routes_require_api_key(client: AsyncClient, path: str) -> None:
    client.headers.pop("X-API-Key")
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers={"X-API-Key": "wrong"})).status_code == 401


async def test_unknown_payment_and_invalid_uuid(client: AsyncClient) -> None:
    assert (await client.get(f"/api/v1/payments/{uuid4()}")).status_code == 404
    assert (await client.get("/api/v1/payments/not-a-uuid")).status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", "0"),
        ("amount", "-1"),
        ("amount", "1.001"),
        ("amount", "10000000000000000"),
        ("amount", "NaN"),
        ("currency", "GBP"),
        ("description", ""),
        ("webhook_url", "ftp://example.com"),
        ("metadata", []),
        ("unknown", "field"),
    ],
)
async def test_invalid_body_is_rejected(client: AsyncClient, field: str, value: JsonValue) -> None:
    response = await client.post(
        "/api/v1/payments", json={**payload(), field: value}, headers={"Idempotency-Key": "key"}
    )
    assert response.status_code == 422


async def test_idempotency_header_is_required(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/payments", json=payload())).status_code == 422


async def test_health_and_openapi_use_version_file(client: AsyncClient) -> None:
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": read_version()}
    schema = await client.get("/openapi.json")
    assert schema.json()["info"]["version"] == read_version()
