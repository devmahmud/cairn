"""Declarative base for all ORM models (BLUEPRINT.md §3.3).

Domain models (`users`, `conversations`, `messages`, `documents`/`chunks`,
`config_overrides`, ...) are added as SQLAlchemy models in a later scaffold
step (§8 step 3, "Persistence + DI + transactions"); the first migration
(this step) creates their tables directly in SQL so `alembic upgrade head`
is meaningful before any ORM model exists. This module only defines the
shared `Base` + a naming convention, so every model added on top of it (and
every future `alembic revision --autogenerate`) gets stable, predictable
constraint/index names instead of SQLAlchemy's default anonymous ones.

LangGraph's checkpoint tables are deliberately NOT modeled here -- they are
owned and created by `AsyncPostgresSaver.setup()` at app startup (§3.3).
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
