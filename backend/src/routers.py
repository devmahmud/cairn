"""Top-level API router aggregation (BLUEPRINT.md §2).

Each `modules/<name>` vertical slice owns its own `router.py`; this is the
single place they get mounted onto the app. Later scaffold steps (chat,
auth, ...) add their routers here as those modules land (§8 steps 6, 7).
"""

from __future__ import annotations

from fastapi import APIRouter

from modules.conversations.router import router as conversations_router
from modules.health.router import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(conversations_router)
