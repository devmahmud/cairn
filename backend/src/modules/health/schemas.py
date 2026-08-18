"""Response contracts for the health endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ComponentCheck(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: list[ComponentCheck]
