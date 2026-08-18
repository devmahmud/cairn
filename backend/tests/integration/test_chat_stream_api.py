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

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from dependency_injector import providers
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncEngine

from agents.chat.schemas import ClassifyResult
from tests.unit.fakes import FakeChatModel

pytestmark = pytest.mark.integration

_PASSWORD = "correct horse battery staple"


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


@dataclass(frozen=True, slots=True)
class AuthedUser:
    id: uuid.UUID
    access_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


async def _register_user(client: AsyncClient) -> AuthedUser:
    email = f"{uuid.uuid4()}@example.com"
    register_resp = await client.post(
        "/auth/register", json={"email": email, "password": _PASSWORD}
    )
    assert register_resp.status_code == 201, register_resp.text
    user_id = uuid.UUID(register_resp.json()["id"])

    login_resp = await client.post("/auth/login", data={"username": email, "password": _PASSWORD})
    assert login_resp.status_code == 200, login_resp.text

    return AuthedUser(id=user_id, access_token=login_resp.json()["access_token"])


@pytest_asyncio.fixture
async def user(client: AsyncClient) -> AuthedUser:
    """Registers + logs in a real user through the auth API (§8 step 7) --
    not a raw `users` row insert, same reasoning as
    `tests/integration/test_conversations_api.py`'s identical fixture."""
    return await _register_user(client)


@pytest_asyncio.fixture
async def other_user(client: AsyncClient) -> AuthedUser:
    """A second, independent authed user -- for ownership-boundary tests
    (someone who is *not* the owner of a conversation/stream)."""
    return await _register_user(client)


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
    from tests.unit.fakes import FakeChatModel

    return {
        "classify": FakeChatModel(
            structured_response=ClassifyResult(intent="greeting", confidence=0.95)
        ),
        "answer": FakeChatModel(responses=[AIMessage(content="Hi there! How can I help?")]),
    }


async def test_chat_turn_streams_a_well_formed_sequence_and_persists_both_messages(
    client: AsyncClient, user: AuthedUser, fake_chat_agent: Any
) -> None:
    fake_chat_agent(_greeting_fakes())

    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=user.headers)
    ).json()["id"]

    resp = await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "hello!"},
        headers=user.headers,
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
        f"/conversations/{conversation_id}/messages", headers=user.headers
    )
    items = messages_resp.json()["items"]
    assert [m["role"] for m in items] == ["assistant", "user"]  # newest-first (§3.3)
    assert items[0]["content"] == "Hi there! How can I help?"
    assert items[1]["content"] == "hello!"


async def test_chat_turn_requires_an_owned_conversation(
    client: AsyncClient, user: AuthedUser, fake_chat_agent: Any
) -> None:
    fake_chat_agent(_greeting_fakes())

    resp = await client.post(
        "/chat",
        json={"conversation_id": str(uuid.uuid4()), "text": "hello!"},
        headers=user.headers,
    )

    assert resp.status_code == 404


async def test_idempotent_retry_replays_instead_of_rerunning_the_graph(
    client: AsyncClient, user: AuthedUser, fake_chat_agent: Any
) -> None:
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
        await client.post("/conversations", json={"title": "Chat"}, headers=user.headers)
    ).json()["id"]
    payload = {"conversation_id": conversation_id, "text": "hello!", "idempotency_key": "turn-1"}

    first = await client.post("/chat", json=payload, headers=user.headers)
    second = await client.post("/chat", json=payload, headers=user.headers)

    assert first.status_code == second.status_code == 200
    first_events = _parse_sse(first.text)
    second_events = _parse_sse(second.text)

    assert [e["event"] for e in second_events] == ["message_start", "message_delta", "message_end"]
    assert second_events[1]["data"]["text"] == first_events[3]["data"]["text"]

    messages_resp = await client.get(
        f"/conversations/{conversation_id}/messages", headers=user.headers
    )
    # Exactly one user + one assistant message -- the retry never re-ran the
    # graph or double-inserted (§3.3).
    assert len(messages_resp.json()["items"]) == 2


async def test_stale_retry_replays_its_own_turns_reply_not_a_later_turns(
    client: AsyncClient, user: AuthedUser, fake_chat_agent: Any
) -> None:
    """A retry must be correlated to the *specific* user message it retried,
    not "whichever assistant message is newest in the conversation right
    now" -- otherwise a delayed/stale retry of an old idempotency_key,
    arriving after the conversation has already moved on to a later turn,
    would replay that unrelated later turn's reply instead (§3.3)."""

    fake_chat_agent(
        {
            "classify": FakeChatModel(
                structured_response=ClassifyResult(intent="greeting", confidence=0.95)
            ),
            "answer": FakeChatModel(
                responses=[
                    AIMessage(content="First reply."),
                    AIMessage(content="Second reply."),
                ]
            ),
        }
    )

    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=user.headers)
    ).json()["id"]

    first = await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "hello!", "idempotency_key": "turn-1"},
        headers=user.headers,
    )
    assert _parse_sse(first.text)[3]["data"]["text"] == "First reply."

    await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "again!", "idempotency_key": "turn-2"},
        headers=user.headers,
    )

    # A stale retry of the *first* turn's key, arriving after the
    # conversation has moved on -- must still replay "First reply.", not the
    # conversation's now-most-recent "Second reply.".
    stale_retry = await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "hello!", "idempotency_key": "turn-1"},
        headers=user.headers,
    )
    retry_events = _parse_sse(stale_retry.text)
    assert [e["event"] for e in retry_events] == ["message_start", "message_delta", "message_end"]
    assert retry_events[1]["data"]["text"] == "First reply."


class _BlockingClassifyLLM:
    """Enough of the `classify` node's LLM surface
    (`agents/chat/nodes/classify.py`: `llm.with_structured_output(...).ainvoke(...)`)
    to deliberately land a request's graph run mid-generation -- blocked
    *before* anything is persisted -- so a concurrent retry can be fired
    while the original attempt genuinely hasn't finished yet. Not a
    `FakeChatModel`: blocking needs an async hook, and `BaseChatModel`'s
    default `with_structured_output` bridges through a sync `_generate`.
    """

    def __init__(self, response: Any, *, ready: asyncio.Event, release: asyncio.Event) -> None:
        self._response = response
        self._ready = ready
        self._release = release
        self.call_count = 0

    def with_structured_output(self, schema: Any = None, **kwargs: Any) -> _BlockingClassifyLLM:
        return self

    async def ainvoke(self, prompt: Any, **kwargs: Any) -> Any:
        self.call_count += 1
        self._ready.set()
        await self._release.wait()
        return self._response


async def test_concurrent_retry_while_the_original_turn_is_still_generating_replays_instead_of_rerunning(
    client: AsyncClient, user: AuthedUser, fake_chat_agent: Any
) -> None:
    """The race the idempotency key exists for: a client retries because the
    SSE response looks hung while the server is still streaming. Pre-fix,
    `_existing_reply` only ever checked "is the most recent message in the
    conversation an assistant reply" -- while the original attempt is still
    generating, no assistant reply is persisted yet, so the retry fell
    through to running the whole graph a second time, concurrently
    (§3.3's "a retry never re-runs the graph" guarantee, broken)."""

    ready = asyncio.Event()
    release = asyncio.Event()
    classify_llm = _BlockingClassifyLLM(
        ClassifyResult(intent="greeting", confidence=0.95), ready=ready, release=release
    )
    fake_chat_agent(
        {
            "classify": classify_llm,
            "answer": FakeChatModel(responses=[AIMessage(content="Hi there! How can I help?")]),
        }
    )

    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=user.headers)
    ).json()["id"]
    payload = {"conversation_id": conversation_id, "text": "hello!", "idempotency_key": "turn-1"}

    first_task = asyncio.create_task(client.post("/chat", json=payload, headers=user.headers))
    await asyncio.wait_for(ready.wait(), timeout=5)

    second_task = asyncio.create_task(client.post("/chat", json=payload, headers=user.headers))
    # Give the retry's own `begin_turn` a real chance to run its short
    # transaction and reach the in-flight wait before releasing the
    # original -- a generous margin against real (if localhost-fast)
    # Postgres round trips, so this reliably exercises "retry lands while
    # still generating," not just the already-covered sequential case.
    await asyncio.sleep(0.1)
    release.set()

    first = await first_task
    second = await second_task

    assert first.status_code == second.status_code == 200
    assert classify_llm.call_count == 1  # the graph ran exactly once

    first_events = _parse_sse(first.text)
    second_events = _parse_sse(second.text)
    assert [e["event"] for e in second_events] == ["message_start", "message_delta", "message_end"]
    assert second_events[1]["data"]["text"] == first_events[3]["data"]["text"]

    messages_resp = await client.get(
        f"/conversations/{conversation_id}/messages", headers=user.headers
    )
    # Exactly one user + one assistant message -- the concurrent retry waited
    # for the original attempt instead of independently re-running the graph.
    assert len(messages_resp.json()["items"]) == 2


async def test_durable_endpoints_404_when_stream_durable_is_disabled(
    client: AsyncClient, user: AuthedUser
) -> None:
    stream_id = uuid.uuid4().hex

    resume_resp = await client.get(f"/chat/stream/{stream_id}", headers=user.headers)
    stop_resp = await client.post(f"/chat/stream/{stream_id}/stop", headers=user.headers)

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
    client: AsyncClient, user: AuthedUser, durable_streamer: None
) -> None:
    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=user.headers)
    ).json()["id"]

    resp = await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "hello!"},
        headers=user.headers,
    )

    assert resp.status_code == 200
    stream_id = resp.headers["x-stream-id"]
    assert stream_id

    events = _parse_sse(resp.text)
    start = next(e for e in events if e["event"] == "message_start")
    assert start["data"]["streamId"] == stream_id


async def test_durable_resume_from_last_event_id_skips_already_seen_events(
    client: AsyncClient, user: AuthedUser, durable_streamer: None
) -> None:
    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=user.headers)
    ).json()["id"]

    first = await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "hello!"},
        headers=user.headers,
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
        headers=user.headers,
    )

    assert resumed.status_code == 200
    resumed_events = _parse_sse(resumed.text)
    # Only the events *after* id "2" (`agent_switch`) -- the client already
    # has "decision"/"agent_switch" from its first connection.
    assert [e["event"] for e in resumed_events] == ["message_start", "message_delta", "message_end"]
    assert [e["id"] for e in resumed_events] == ["3", "4", "5"]


async def test_durable_stop_then_unknown_stream_id_is_404(
    client: AsyncClient, user: AuthedUser, durable_streamer: None
) -> None:
    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=user.headers)
    ).json()["id"]
    started = await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "hello!"},
        headers=user.headers,
    )
    stream_id = started.headers["x-stream-id"]

    # The (fake-LLM-backed, near-instant) turn has already finished by the
    # time the response body is fully read -- stopping it now exercises
    # "stream known, producer already done" rather than a live cancel, but
    # still proves `/stop` resolves a real `stream_id` to `204`.
    stop_resp = await client.post(f"/chat/stream/{stream_id}/stop", headers=user.headers)
    assert stop_resp.status_code == 204

    unknown_resp = await client.post(f"/chat/stream/{uuid.uuid4().hex}/stop", headers=user.headers)
    assert unknown_resp.status_code == 404


async def test_durable_resume_and_stop_404_for_a_stream_owned_by_another_user(
    client: AsyncClient, user: AuthedUser, other_user: AuthedUser, durable_streamer: None
) -> None:
    """A `stream_id` is 128 bits of unguessable entropy, but anyone who does
    obtain one (a shared link, a logged request, ...) must not be able to
    tail or terminate someone else's in-progress chat stream -- the same
    ownership boundary `conversations`/`messages` REST already enforces
    (§3.9), extended to the stream tail/stop endpoints."""
    conversation_id = (
        await client.post("/conversations", json={"title": "Chat"}, headers=user.headers)
    ).json()["id"]
    started = await client.post(
        "/chat",
        json={"conversation_id": conversation_id, "text": "hello!"},
        headers=user.headers,
    )
    stream_id = started.headers["x-stream-id"]

    resume_resp = await client.get(f"/chat/stream/{stream_id}", headers=other_user.headers)
    stop_resp = await client.post(f"/chat/stream/{stream_id}/stop", headers=other_user.headers)

    assert resume_resp.status_code == 404
    assert stop_resp.status_code == 404

    # The rightful owner can still resume/stop the very same stream --
    # proves the rejection above is a real ownership check, not the stream
    # having become unknown/expired for everyone.
    owner_resume_resp = await client.get(f"/chat/stream/{stream_id}", headers=user.headers)
    assert owner_resume_resp.status_code == 200
