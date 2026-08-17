"""Integration tests for the auth module (BLUEPRINT.md §3.9, §8 step 7).

End-to-end: the real ASGI app (`main.app`, full lifespan via `asgi-lifespan`)
against a real, migrated Postgres -- same pattern as
`tests/integration/test_conversations_api.py`; see
`tests/integration/conftest.py` for how to point one at these tests and how
they skip cleanly without one. `AUTH_ENABLED=true` is this template's
process-wide default (`core/config.py`), so these tests exercise the actual
default configuration, not a special test-only mode.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_PASSWORD = "correct horse battery staple"


@pytest_asyncio.fixture
async def client(db_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    from main import app

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client


def _unique_email() -> str:
    return f"{uuid.uuid4()}@example.com"


async def _register(
    client: AsyncClient, *, email: str, password: str = _PASSWORD
) -> dict[str, object]:
    resp = await client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    body: dict[str, object] = resp.json()
    return body


async def _login(client: AsyncClient, *, email: str, password: str = _PASSWORD) -> dict[str, str]:
    resp = await client.post("/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    body: dict[str, str] = resp.json()
    return body


async def test_register_then_login_returns_a_token_pair(client: AsyncClient) -> None:
    email = _unique_email()
    registered = await _register(client, email=email)
    assert registered["email"] == email

    tokens = await _login(client, email=email)

    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]


async def test_login_with_wrong_password_is_rejected(client: AsyncClient) -> None:
    email = _unique_email()
    await _register(client, email=email)

    resp = await client.post("/auth/login", data={"username": email, "password": "wrong password"})

    assert resp.status_code == 401


async def test_protected_route_401s_without_a_token(client: AsyncClient) -> None:
    resp = await client.get("/conversations")

    assert resp.status_code == 401


async def test_protected_route_200s_with_a_valid_token(client: AsyncClient) -> None:
    email = _unique_email()
    await _register(client, email=email)
    tokens = await _login(client, email=email)

    resp = await client.get(
        "/conversations", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert resp.status_code == 200


async def test_me_returns_the_authenticated_user(client: AsyncClient) -> None:
    email = _unique_email()
    registered = await _register(client, email=email)
    tokens = await _login(client, email=email)

    resp = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == registered["id"]
    assert resp.json()["email"] == email


async def test_refresh_rotates_the_refresh_token_and_mints_a_new_access_token(
    client: AsyncClient,
) -> None:
    email = _unique_email()
    await _register(client, email=email)
    tokens = await _login(client, email=email)

    refreshed_resp = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed_resp.status_code == 200
    refreshed = refreshed_resp.json()

    assert refreshed["access_token"]
    assert refreshed["refresh_token"] != tokens["refresh_token"]

    # The new access token works against a protected route.
    resp = await client.get(
        "/conversations", headers={"Authorization": f"Bearer {refreshed['access_token']}"}
    )
    assert resp.status_code == 200

    # The old refresh token was rotated out -- single-use.
    reused_resp = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reused_resp.status_code == 401


async def test_logout_revokes_the_refresh_token(client: AsyncClient) -> None:
    email = _unique_email()
    await _register(client, email=email)
    tokens = await _login(client, email=email)

    logout_resp = await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout_resp.status_code == 204

    refresh_resp = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_resp.status_code == 401


async def test_logout_with_an_unknown_token_is_a_harmless_no_op(client: AsyncClient) -> None:
    resp = await client.post("/auth/logout", json={"refresh_token": "not-a-real-token"})

    assert resp.status_code == 204
