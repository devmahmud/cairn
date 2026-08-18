"""Each modules/<name> vertical slice owns its own router.py; this is the single place they get mounted onto the app."""

from __future__ import annotations

from fastapi import APIRouter

from modules.auth.router import router as auth_router
from modules.chat.router import router as chat_router
from modules.conversations.router import router as conversations_router
from modules.health.router import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(conversations_router)
api_router.include_router(chat_router)
