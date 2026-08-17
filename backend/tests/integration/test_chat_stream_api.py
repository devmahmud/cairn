"""Integration tests for `POST /chat` and the durable-mode endpoints (BLUEPRINT.md §3.7, §8 step 6).

End-to-end: the real ASGI app (`main.app`, full lifespan via `asgi-lifespan`)
against a real, migrated Postgres -- same pattern as
`tests/integration/test_conversations_api.py`; see
`tests/integration/conftest.py` for how to point one at these tests and how
they skip cleanly without one.

The LLM is the one thing swapped for a fake: `container.chat_agent` is
overridden (`dependency-injector`'s `.override()`) with a `ChatAgent` built
from `FakeChatModel`s and `LocalFixtureRetrievalService`, exactly like
`tests/unit/test_chat_graph_offline.py` -- everything downstream of that
(the real graph, the real streamer/translator, the real two-transaction
persistence, the real `/conversations` REST surface used to verify it) runs
for real.

Most of this file runs in simple mode (`STREAM_DURABLE` off, the default).
The `test_durable_*` tests at the bottom need a real, reachable Redis --
point `TEST_REDIS_URL` at one (default `redis://localhost:6379/0`) the same
way `DATABASE_URL` points at the scratch Postgres; they skip cleanly,
individually, without one (a `chat_streamer` override, not a process-wide
env var, so simple-mode tests in this same file are unaffected either way).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from dependency_injector import providers
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


def _parse_sse(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.strip("\n").split("\n\n"):
        if not block.strip():
            continue
        record: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith(":"):
                continue  # heartbeat comment
            field, _, value = line.partition(": ")
            if field == "data":
                record["data"] = json.loads(value)
            else:
                record[field] = value
        if record:
            events.append(record)
    return events


@pytest_asyncio.fixture
async def client(db_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    from main import app

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client


@pytest_asyncio.fixture
async def user_id(db_engine: AsyncEngine) -> uuid.UUID:
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


@pytest.fixture
def fake_chat_agent() -> Any:
    """Overrides `container.chat_agent` with a fake-LLM-backed instance for
    the duration of one test, then restores the real provider."""
    from agents.chat.agent import ChatAgent
    from core.behavior.loader import BehaviorConfig
    from core.di.container import container
    from core.prompts.engine import PromptEngine
    from core.prompts.loader import FileSystemJ2Loader
    from modules.retrieval.fixture import LocalFixtureRetrievalService
    from tests.unit.fakes import FakeChatModel

    def _build(fakes: dict[str, FakeChatModel]) -> None:
        def llm_factory(role: str) -> FakeChatModel:
            try:
                return fakes[role]
            except KeyError:
                raise AssertionError(f"No fake LLM configured for role {role!r}.") from None

        agent = ChatAgent(
            prompt_engine=PromptEngine(loader=FileSystemJ2Loader(base_path="config/prompts")),
            retrieval_service=LocalFixtureRetrievalService(),
            checkpointer=None,
            behavior_config=BehaviorConfig(base_path="config/behavior"),
            llm_factory=llm_factory,
        )
        container.chat_agent.override(providers.Object(agent))

    yield _build
    container.chat_agent.reset_override()


def _greeting_fakes() -> dict[str, Any]:
    from agents.chat.schemas import ClassifyResult
    from tests.unit.fakes import FakeChatModel

    return {
        "classify": FakeChatModel(
            structured_response=ClassifyResult(intent="greeting", confidence=0.95)
        ),
        "answer": FakeChatModel(responses=[AIMessage(content="Hi there! How can I help?")]),
    }


async def test_chat_turn_streams_a_well_formed_sequence_and_persists_both_messages(
    client: AsyncClient, user_id: uuid.UUID, fake_chat_agent: Any
) -> None:
    fake_chat_agent(_greeting_fakes())

    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=_auth_headers(user_id))
    ).json()["id"]

    resp = await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "hello!"},
        headers=_auth_headers(user_id),
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    types = [e["event"] for e in events]
    assert types == ["decision", "agent_switch", "message_start", "message_delta", "message_end"]
    # `id:` is monotonic across the whole turn (§3.7).
    assert [e["id"] for e in events] == ["1", "2", "3", "4", "5"]
    assert events[3]["data"]["text"] == "Hi there! How can I help?"

    messages_resp = await client.get(
        f"/conversations/{conversation_id}/messages", headers=_auth_headers(user_id)
    )
    items = messages_resp.json()["items"]
    assert [m["role"] for m in items] == ["assistant", "user"]  # newest-first (§3.3)
    assert items[0]["content"] == "Hi there! How can I help?"
    assert items[1]["content"] == "hello!"


async def test_chat_turn_requires_an_owned_conversation(
    client: AsyncClient, user_id: uuid.UUID, fake_chat_agent: Any
) -> None:
    fake_chat_agent(_greeting_fakes())

    resp = await client.post(
        "/chat",
        json={"conversation_id": str(uuid.uuid4()), "text": "hello!"},
        headers=_auth_headers(user_id),
    )

    assert resp.status_code == 404


async def test_idempotent_retry_replays_instead_of_rerunning_the_graph(
    client: AsyncClient, user_id: uuid.UUID, fake_chat_agent: Any
) -> None:
    from agents.chat.schemas import ClassifyResult
    from tests.unit.fakes import FakeChatModel

    # Only one canned response each -- a second graph run would raise
    # `AssertionError("no more canned responses queued")` inside the node,
    # degrading to a fallback message. Asserting the *original* reply comes
    # back proves the retry replayed rather than re-invoked the LLM.
    fake_chat_agent(
        {
            "classify": FakeChatModel(
                structured_response=ClassifyResult(intent="greeting", confidence=0.95)
            ),
            "answer": FakeChatModel(responses=[AIMessage(content="Hi there! How can I help?")]),
        }
    )

    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=_auth_headers(user_id))
    ).json()["id"]
    payload = {"conversation_id": conversation_id, "text": "hello!", "idempotency_key": "turn-1"}

    first = await client.post("/chat", json=payload, headers=_auth_headers(user_id))
    second = await client.post("/chat", json=payload, headers=_auth_headers(user_id))

    assert first.status_code == second.status_code == 200
    first_events = _parse_sse(first.text)
    second_events = _parse_sse(second.text)

    assert [e["event"] for e in second_events] == ["message_start", "message_delta", "message_end"]
    assert second_events[1]["data"]["text"] == first_events[3]["data"]["text"]

    messages_resp = await client.get(
        f"/conversations/{conversation_id}/messages", headers=_auth_headers(user_id)
    )
    # Exactly one user + one assistant message -- the retry never re-ran the
    # graph or double-inserted (§3.3).
    assert len(messages_resp.json()["items"]) == 2


async def test_durable_endpoints_404_when_stream_durable_is_disabled(
    client: AsyncClient, user_id: uuid.UUID
) -> None:
    stream_id = uuid.uuid4().hex

    resume_resp = await client.get(f"/chat/stream/{stream_id}", headers=_auth_headers(user_id))
    stop_resp = await client.post(f"/chat/stream/{stream_id}/stop", headers=_auth_headers(user_id))

    assert resume_resp.status_code == 404
    assert stop_resp.status_code == 404


# --- Durable mode (needs a real, reachable Redis) --------------------------


@pytest_asyncio.fixture
async def durable_streamer(fake_chat_agent: Any) -> AsyncIterator[None]:
    """Overrides `container.chat_streamer` with one built against a real
    Redis and `STREAM_DURABLE=True`, independent of process env vars (a
    fresh `Settings(...)` instance, not the process-wide `core.config.settings`
    singleton `STREAM_DURABLE` normally reads from) -- skips cleanly, like
    the Postgres fixtures, when `TEST_REDIS_URL` isn't reachable.

    Depends on `fake_chat_agent` (not just declares it as a sibling
    parameter) so the fake-LLM override is already active before this
    resolves `container.chat_agent()` to build the streamer around it --
    fixture parameter order alone wouldn't guarantee that.
    """
    import os

    import redis.asyncio as redis_asyncio
    from dependency_injector import providers

    from core.config import Settings
    from core.di.container import container
    from core.stream.resume import RedisStreamBus
    from modules.chat.chat_stream import ChatStreamer

    url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")
    redis_client = redis_asyncio.from_url(url, decode_responses=True)
    try:
        await redis_client.ping()
    except Exception:
        await redis_client.aclose()
        pytest.skip(f"No reachable Redis for durable-mode tests (TEST_REDIS_URL={url!r}).")

    fake_chat_agent(_greeting_fakes())
    durable_settings = Settings(STREAM_DURABLE=True, REDIS_URL=url)
    streamer = ChatStreamer(
        chat_agent=container.chat_agent(),
        sessionmaker=container.sessionmaker(),
        stream_bus=RedisStreamBus(redis_client),
        app_settings=durable_settings,
    )
    container.chat_streamer.override(providers.Object(streamer))

    yield

    container.chat_streamer.reset_override()
    await redis_client.aclose()


async def test_durable_chat_turn_returns_a_stream_id_and_embeds_it_in_message_start(
    client: AsyncClient, user_id: uuid.UUID, durable_streamer: None
) -> None:
    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=_auth_headers(user_id))
    ).json()["id"]

    resp = await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "hello!"},
        headers=_auth_headers(user_id),
    )

    assert resp.status_code == 200
    stream_id = resp.headers["x-stream-id"]
    assert stream_id

    events = _parse_sse(resp.text)
    start = next(e for e in events if e["event"] == "message_start")
    assert start["data"]["streamId"] == stream_id


async def test_durable_resume_from_last_event_id_skips_already_seen_events(
    client: AsyncClient, user_id: uuid.UUID, durable_streamer: None
) -> None:
    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=_auth_headers(user_id))
    ).json()["id"]

    first = await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "hello!"},
        headers=_auth_headers(user_id),
    )
    stream_id = first.headers["x-stream-id"]
    first_events = _parse_sse(first.text)
    assert [e["event"] for e in first_events] == [
        "decision",
        "agent_switch",
        "message_start",
        "message_delta",
        "message_end",
    ]

    resumed = await client.get(
        f"/chat/stream/{stream_id}",
        params={"last_event_id": "2"},
        headers=_auth_headers(user_id),
    )

    assert resumed.status_code == 200
    resumed_events = _parse_sse(resumed.text)
    # Only the events *after* id "2" (`agent_switch`) -- the client already
    # has "decision"/"agent_switch" from its first connection.
    assert [e["event"] for e in resumed_events] == ["message_start", "message_delta", "message_end"]
    assert [e["id"] for e in resumed_events] == ["3", "4", "5"]


async def test_durable_stop_then_unknown_stream_id_is_404(
    client: AsyncClient, user_id: uuid.UUID, durable_streamer: None
) -> None:
    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=_auth_headers(user_id))
    ).json()["id"]
    started = await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "hello!"},
        headers=_auth_headers(user_id),
    )
    stream_id = started.headers["x-stream-id"]

    # The (fake-LLM-backed, near-instant) turn has already finished by the
    # time the response body is fully read -- stopping it now exercises
    # "stream known, producer already done" rather than a live cancel, but
    # still proves `/stop` resolves a real `stream_id` to `204`.
    stop_resp = await client.post(f"/chat/stream/{stream_id}/stop", headers=_auth_headers(user_id))
    assert stop_resp.status_code == 204

    unknown_resp = await client.post(
        f"/chat/stream/{uuid.uuid4().hex}/stop", headers=_auth_headers(user_id)
    )
    assert unknown_resp.status_code == 404
