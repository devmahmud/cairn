"""Idempotent -- the sample user is looked up by email first; a user that already has a conversation is left alone rather than growing a duplicate one on every run."""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import select

from core.config import settings
from core.db.engine import SessionLocal
from core.observability.logging import configure_logging
from modules.auth.models import User
from modules.auth.schemas import UserCreate
from modules.auth.users import UserManager
from modules.conversations.models import Conversation, Message

logger = structlog.get_logger(__name__)

SEED_EMAIL = "demo@example.com"
SEED_PASSWORD = "demo-password-123"
SEED_CONVERSATION_TITLE = "Getting started"


async def seed() -> None:
    async with SessionLocal() as session:
        user_db: SQLAlchemyUserDatabase[User, uuid.UUID] = SQLAlchemyUserDatabase(session, User)
        manager = UserManager(user_db)

        user = await user_db.get_by_email(SEED_EMAIL)
        if user is None:
            user = await manager.create(
                UserCreate(email=SEED_EMAIL, password=SEED_PASSWORD, is_verified=True),
                safe=False,
            )
            logger.info("seed.user_created", email=SEED_EMAIL)
        else:
            logger.info("seed.user_exists", email=SEED_EMAIL)

        has_conversation = (
            await session.execute(
                select(Conversation.id).where(Conversation.user_id == user.id).limit(1)
            )
        ).first()
        if has_conversation is not None:
            logger.info("seed.conversation_exists", user_id=str(user.id))
            await session.commit()
            return

        conversation = Conversation(user_id=user.id, title=SEED_CONVERSATION_TITLE)
        session.add(conversation)
        await session.flush()

        session.add_all(
            [
                Message(
                    conversation_id=conversation.id,
                    role="user",
                    content="How do I get started with the docs assistant?",
                ),
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=(
                        "Ask a question about the sample docs corpus and I'll answer with "
                        "citations. Run `make ingest` first to populate the retrieval index "
                        "if you haven't already."
                    ),
                ),
            ]
        )
        await session.commit()
        logger.info("seed.conversation_created", conversation_id=str(conversation.id))


def main() -> None:
    configure_logging(json_logs=settings.ENVIRONMENT != "local")
    asyncio.run(seed())
    logger.info("seed.done", email=SEED_EMAIL, password=SEED_PASSWORD)


if __name__ == "__main__":
    main()
