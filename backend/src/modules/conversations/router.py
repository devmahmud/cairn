"""REST endpoints for conversation/message CRUD (BLUEPRINT.md §2, §8 step 3).

Wired via plain FastAPI `Depends` (not the `dependency-injector` container,
which is reserved for the singleton agent graph -- §3.4: "pick one wiring
model per concern and don't mix `Provide` and `Depends` for the same kind
of dependency"). `get_session` owns commit/rollback (commit-per-request,
§3.3) -- nothing in this router or the service/repository layers below it
calls `session.commit()` directly.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.engine import get_session
from core.security.current_user import get_current_user_id
from modules.conversations.repository import ConversationRepository, MessageRepository
from modules.conversations.schemas import (
    ConversationCreate,
    ConversationPage,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    MessagePage,
    MessageRead,
)
from modules.conversations.service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])


def get_conversation_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationService:
    return ConversationService(ConversationRepository(session), MessageRepository(session))


ServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]
UserIdDep = Annotated[UUID, Depends(get_current_user_id)]
CursorQuery = Annotated[str | None, Query(description="Opaque keyset-pagination cursor.")]
LimitQuery = Annotated[int | None, Query(ge=1, le=200)]


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate, service: ServiceDep, user_id: UserIdDep
) -> ConversationRead:
    return await service.create_conversation(user_id=user_id, payload=payload)


@router.get("", response_model=ConversationPage)
async def list_conversations(
    service: ServiceDep,
    user_id: UserIdDep,
    cursor: CursorQuery = None,
    limit: LimitQuery = None,
) -> ConversationPage:
    return await service.list_conversations(user_id=user_id, cursor=cursor, limit=limit)


@router.get("/{conversation_id}", response_model=ConversationRead)
async def get_conversation(
    conversation_id: UUID, service: ServiceDep, user_id: UserIdDep
) -> ConversationRead:
    return await service.get_conversation(conversation_id, user_id=user_id)


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    service: ServiceDep,
    user_id: UserIdDep,
) -> ConversationRead:
    return await service.update_conversation(conversation_id, user_id=user_id, payload=payload)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID, service: ServiceDep, user_id: UserIdDep
) -> None:
    await service.delete_conversation(conversation_id, user_id=user_id)


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_message(
    conversation_id: UUID,
    payload: MessageCreate,
    service: ServiceDep,
    user_id: UserIdDep,
) -> MessageRead:
    return await service.add_message(conversation_id, user_id=user_id, payload=payload)


@router.get("/{conversation_id}/messages", response_model=MessagePage)
async def list_messages(
    conversation_id: UUID,
    service: ServiceDep,
    user_id: UserIdDep,
    cursor: CursorQuery = None,
    limit: LimitQuery = None,
) -> MessagePage:
    return await service.list_messages(conversation_id, user_id=user_id, cursor=cursor, limit=limit)
