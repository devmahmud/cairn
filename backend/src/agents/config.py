"""Per-role model config; deliberately not per-role .env knobs -- OPENAI_MODEL is the one model identity this template exposes, roles only vary temperature/timeout on top of it."""

from __future__ import annotations

from dataclasses import dataclass

from core.config import settings


@dataclass(frozen=True, slots=True)
class RoleConfig:
    model: str
    temperature: float
    timeout: float


# judge isn't a graph node -- it's the eval harness's scorer, reusing the same per-role tuning pattern.
_ROLE_CONFIGS: dict[str, RoleConfig] = {
    "classify": RoleConfig(model=settings.OPENAI_MODEL, temperature=0.0, timeout=8.0),
    "answer": RoleConfig(model=settings.OPENAI_MODEL, temperature=0.3, timeout=30.0),
    "rag": RoleConfig(model=settings.OPENAI_MODEL, temperature=0.2, timeout=30.0),
    "tool": RoleConfig(model=settings.OPENAI_MODEL, temperature=0.0, timeout=20.0),
    "judge": RoleConfig(model=settings.OPENAI_MODEL, temperature=0.0, timeout=30.0),
}


def role_config(role: str) -> RoleConfig:
    try:
        return _ROLE_CONFIGS[role]
    except KeyError:
        raise ValueError(
            f"Unknown agent role {role!r}. Known roles: {sorted(_ROLE_CONFIGS)}."
        ) from None
