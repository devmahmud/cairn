"""Integration tests for the conversations REST API (BLUEPRINT.md §8 step 3).

End-to-end: the real ASGI app (`main.app`, full lifespan driven by
`asgi-lifespan`) against a real, migrated Postgres. Needs a reachable
database -- see `tests/integration/conftest.py` for how to point one at
these tests and how they skip cleanly without one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


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


@pytest_asyncio.fixture
async def user_id(db_engine: AsyncEngine) -> uuid.UUID:
    """A real `users` row -- `conversations.user_id` has a hard FK to it.

    The auth module (§8 step 7) doesn't exist yet, so this seeds the row
    directly instead of registering through an API that isn't built.
    """
    new_id = uuid.uuid4()
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, email, hashed_password) "
                "VALUES (:id, :email, :hashed_password)"
            ),
            {"id": new_id, "email": f"{new_id}@example.com", "hashed_password": "x"},
        )
    return new_id


def _auth_headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


async def test_create_and_get_conversation(client: AsyncClient, user_id: uuid.UUID) -> None:
    create_resp = await client.post(
        "/conversations", json={"title": "First chat"}, headers=_auth_headers(user_id)
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["title"] == "First chat"
    assert created["status"] == "active"
    assert created["user_id"] == str(user_id)

    get_resp = await client.get(f"/conversations/{created['id']}", headers=_auth_headers(user_id))
    assert get_resp.status_code == 200
    assert get_resp.json() == created


async def test_missing_auth_header_is_rejected(client: AsyncClient) -> None:
    resp = await client.post("/conversations", json={"title": "x"})
    assert resp.status_code == 401


async def test_get_nonexistent_conversation_is_404(client: AsyncClient, user_id: uuid.UUID) -> None:
    resp = await client.get(f"/conversations/{uuid.uuid4()}", headers=_auth_headers(user_id))
    assert resp.status_code == 404


async def test_conversation_is_not_visible_to_a_different_user(
    client: AsyncClient, user_id: uuid.UUID, db_engine: AsyncEngine
) -> None:
    other_user_id = uuid.uuid4()
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, email, hashed_password) "
                "VALUES (:id, :email, :hashed_password)"
            ),
            {"id": other_user_id, "email": f"{other_user_id}@example.com", "hashed_password": "x"},
        )

    create_resp = await client.post(
        "/conversations", json={"title": "Mine"}, headers=_auth_headers(user_id)
    )
    conversation_id = create_resp.json()["id"]

    resp = await client.get(
        f"/conversations/{conversation_id}", headers=_auth_headers(other_user_id)
    )
    assert resp.status_code == 404


async def test_update_conversation(client: AsyncClient, user_id: uuid.UUID) -> None:
    create_resp = await client.post(
        "/conversations", json={"title": "Original"}, headers=_auth_headers(user_id)
    )
    conversation_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/conversations/{conversation_id}",
        json={"status": "archived"},
        headers=_auth_headers(user_id),
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["status"] == "archived"
    assert updated["title"] == "Original"  # untouched


async def test_delete_conversation_then_404(client: AsyncClient, user_id: uuid.UUID) -> None:
    create_resp = await client.post(
        "/conversations", json={"title": "Temp"}, headers=_auth_headers(user_id)
    )
    conversation_id = create_resp.json()["id"]

    delete_resp = await client.delete(
        f"/conversations/{conversation_id}", headers=_auth_headers(user_id)
    )
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/conversations/{conversation_id}", headers=_auth_headers(user_id))
    assert get_resp.status_code == 404


async def test_list_conversations_paginates_with_a_default_limit(
    client: AsyncClient, user_id: uuid.UUID
) -> None:
    for i in range(3):
        resp = await client.post(
            "/conversations", json={"title": f"Chat {i}"}, headers=_auth_headers(user_id)
        )
        assert resp.status_code == 201

    first_page = await client.get(
        "/conversations", params={"limit": 2}, headers=_auth_headers(user_id)
    )
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"] is not None

    second_page = await client.get(
        "/conversations",
        params={"limit": 2, "cursor": first_body["next_cursor"]},
        headers=_auth_headers(user_id),
    )
    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["items"]) == 1
    assert second_body["next_cursor"] is None

    all_ids = {item["id"] for item in first_body["items"]} | {
        item["id"] for item in second_body["items"]
    }
    assert len(all_ids) == 3


async def test_create_and_list_messages(client: AsyncClient, user_id: uuid.UUID) -> None:
    conversation_id = (
        await client.post(
            "/conversations", json={"title": "With messages"}, headers=_auth_headers(user_id)
        )
    ).json()["id"]

    create_resp = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Hello there"},
        headers=_auth_headers(user_id),
    )
    assert create_resp.status_code == 201
    message = create_resp.json()
    assert message["role"] == "user"
    assert message["content"] == "Hello there"
    assert message["artifacts"] == []
    assert message["citations"] == []

    list_resp = await client.get(
        f"/conversations/{conversation_id}/messages", headers=_auth_headers(user_id)
    )
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == message["id"]


async def test_messages_require_an_owned_conversation(
    client: AsyncClient, user_id: uuid.UUID
) -> None:
    resp = await client.post(
        f"/conversations/{uuid.uuid4()}/messages",
        json={"role": "user", "content": "hi"},
        headers=_auth_headers(user_id),
    )
    assert resp.status_code == 404


async def test_idempotent_message_retry_is_a_no_op(client: AsyncClient, user_id: uuid.UUID) -> None:
    """The client `idempotency_key` (§3.3) makes a retried POST a no-op --
    never a duplicate message -- honoring the migration's partial unique
    index on `(conversation_id, idempotency_key)`.
    """
    conversation_id = (
        await client.post(
            "/conversations", json={"title": "Idempotent"}, headers=_auth_headers(user_id)
        )
    ).json()["id"]

    payload = {"role": "user", "content": "retry me", "idempotency_key": "turn-1"}

    first_resp = await client.post(
        f"/conversations/{conversation_id}/messages",
        json=payload,
        headers=_auth_headers(user_id),
    )
    second_resp = await client.post(
        f"/conversations/{conversation_id}/messages",
        json=payload,
        headers=_auth_headers(user_id),
    )
    assert first_resp.status_code == 201
    assert second_resp.status_code == 201
    assert first_resp.json()["id"] == second_resp.json()["id"]

    list_resp = await client.get(
        f"/conversations/{conversation_id}/messages", headers=_auth_headers(user_id)
    )
    assert len(list_resp.json()["items"]) == 1
