"""Integration tests for the conversations REST API (BLUEPRINT.md §8 step 3, §8 step 7).

End-to-end: the real ASGI app (`main.app`, full lifespan driven by
`asgi-lifespan`) against a real, migrated Postgres. Needs a reachable
database -- see `tests/integration/conftest.py` for how to point one at
these tests and how they skip cleanly without one.

Authenticates through the real `/auth/register` + `/auth/login` endpoints
(§8 step 7) -- not a client-supplied `X-User-Id` header (phase 1's interim
stub, `core/security/current_user.py`'s previous revision). This is what
makes `test_conversation_is_not_visible_to_a_different_user` below a
genuine test of ownership scoping against a *real* authenticated identity,
not just a header a malicious client could equally well have forged.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_PASSWORD = "correct horse battery staple"


@pytest_asyncio.fixture
async def client(db_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    # Imported lazily, inside the fixture: `main` (transitively) instantiates
    # `core.config.Settings` at import time, which must see the test
    # `DATABASE_URL` from the environment -- importing at module scope could
    # race a differently-configured earlier import in the same test session.
    from main import app

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client


@dataclass(frozen=True, slots=True)
class AuthedUser:
    id: uuid.UUID
    access_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


#: `register_user`'s type -- `...` (not a fixed arg list) since `_register`
#: below takes an optional `email` with a default, and `Callable[[str |
#: None], ...]` would force every call site to pass one anyway.
RegisterUser = Callable[..., Awaitable[AuthedUser]]


@pytest_asyncio.fixture
async def register_user(client: AsyncClient) -> RegisterUser:
    """A factory (not a single value) so tests that need >1 real user
    (`test_conversation_is_not_visible_to_a_different_user`) can call this
    more than once, each time registering + logging in through the real
    API rather than seeding a `users` row directly.
    """

    async def _register(email: str | None = None) -> AuthedUser:
        email = email or f"{uuid.uuid4()}@example.com"
        register_resp = await client.post(
            "/auth/register", json={"email": email, "password": _PASSWORD}
        )
        assert register_resp.status_code == 201, register_resp.text
        user_id = uuid.UUID(register_resp.json()["id"])

        login_resp = await client.post(
            "/auth/login", data={"username": email, "password": _PASSWORD}
        )
        assert login_resp.status_code == 200, login_resp.text
        access_token: str = login_resp.json()["access_token"]

        return AuthedUser(id=user_id, access_token=access_token)

    return _register


@pytest_asyncio.fixture
async def user(register_user: RegisterUser) -> AuthedUser:
    return await register_user()


async def test_create_and_get_conversation(client: AsyncClient, user: AuthedUser) -> None:
    create_resp = await client.post(
        "/conversations", json={"title": "First chat"}, headers=user.headers
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["title"] == "First chat"
    assert created["status"] == "active"
    assert created["user_id"] == str(user.id)

    get_resp = await client.get(f"/conversations/{created['id']}", headers=user.headers)
    assert get_resp.status_code == 200
    assert get_resp.json() == created


async def test_missing_auth_header_is_rejected(client: AsyncClient) -> None:
    resp = await client.post("/conversations", json={"title": "x"})
    assert resp.status_code == 401


async def test_get_nonexistent_conversation_is_404(client: AsyncClient, user: AuthedUser) -> None:
    resp = await client.get(f"/conversations/{uuid.uuid4()}", headers=user.headers)
    assert resp.status_code == 404


async def test_conversation_is_not_visible_to_a_different_user(
    client: AsyncClient, user: AuthedUser, register_user: RegisterUser
) -> None:
    other = await register_user()

    create_resp = await client.post("/conversations", json={"title": "Mine"}, headers=user.headers)
    conversation_id = create_resp.json()["id"]

    resp = await client.get(f"/conversations/{conversation_id}", headers=other.headers)
    assert resp.status_code == 404


async def test_update_conversation(client: AsyncClient, user: AuthedUser) -> None:
    create_resp = await client.post(
        "/conversations", json={"title": "Original"}, headers=user.headers
    )
    conversation_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/conversations/{conversation_id}",
        json={"status": "archived"},
        headers=user.headers,
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["status"] == "archived"
    assert updated["title"] == "Original"  # untouched


async def test_delete_conversation_then_404(client: AsyncClient, user: AuthedUser) -> None:
    create_resp = await client.post("/conversations", json={"title": "Temp"}, headers=user.headers)
    conversation_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/conversations/{conversation_id}", headers=user.headers)
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/conversations/{conversation_id}", headers=user.headers)
    assert get_resp.status_code == 404


async def test_list_conversations_paginates_with_a_default_limit(
    client: AsyncClient, user: AuthedUser
) -> None:
    for i in range(3):
        resp = await client.post(
            "/conversations", json={"title": f"Chat {i}"}, headers=user.headers
        )
        assert resp.status_code == 201

    first_page = await client.get("/conversations", params={"limit": 2}, headers=user.headers)
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"] is not None

    second_page = await client.get(
        "/conversations",
        params={"limit": 2, "cursor": first_body["next_cursor"]},
        headers=user.headers,
    )
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["items"]) == 1
    assert second_body["next_cursor"] is None

    all_ids = {item["id"] for item in first_body["items"]} | {
        item["id"] for item in second_body["items"]
    }
    assert len(all_ids) == 3


async def test_create_and_list_messages(client: AsyncClient, user: AuthedUser) -> None:
    conversation_id = (
        await client.post("/conversations", json={"title": "With messages"}, headers=user.headers)
    ).json()["id"]

    create_resp = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Hello there"},
        headers=user.headers,
    )
    assert create_resp.status_code == 201
    message = create_resp.json()
    assert message["role"] == "user"
    assert message["content"] == "Hello there"
    assert message["artifacts"] == []
    assert message["citations"] == []

    list_resp = await client.get(f"/conversations/{conversation_id}/messages", headers=user.headers)
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == message["id"]


async def test_messages_require_an_owned_conversation(
    client: AsyncClient, user: AuthedUser
) -> None:
    resp = await client.post(
        f"/conversations/{uuid.uuid4()}/messages",
        json={"role": "user", "content": "hi"},
        headers=user.headers,
    )
    assert resp.status_code == 404


async def test_idempotent_message_retry_is_a_no_op(client: AsyncClient, user: AuthedUser) -> None:
    """The client `idempotency_key` (§3.3) makes a retried POST a no-op --
    never a duplicate message -- honoring the migration's partial unique
    index on `(conversation_id, idempotency_key)`.
    """
    conversation_id = (
        await client.post("/conversations", json={"title": "Idempotent"}, headers=user.headers)
    ).json()["id"]

    payload = {"role": "user", "content": "retry me", "idempotency_key": "turn-1"}

    first_resp = await client.post(
        f"/conversations/{conversation_id}/messages",
        json=payload,
        headers=user.headers,
    )
    second_resp = await client.post(
        f"/conversations/{conversation_id}/messages",
        json=payload,
        headers=user.headers,
    )
    assert first_resp.status_code == 201
    assert second_resp.status_code == 201
    assert first_resp.json()["id"] == second_resp.json()["id"]

    list_resp = await client.get(f"/conversations/{conversation_id}/messages", headers=user.headers)
    assert len(list_resp.json()["items"]) == 1
