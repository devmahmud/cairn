"""Owns the cursor encoding _paginate_keyset (type-agnostic) has no opinion on: the (created_at, id) pair both repositories in this module use."""

from __future__ import annotations

import base64
from datetime import datetime
from uuid import UUID

from core.errors.exceptions import ValidationAppError

_SEPARATOR = "|"


def encode_cursor(created_at: datetime, id_: UUID) -> str:
    raw = f"{created_at.isoformat()}{_SEPARATOR}{id_}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        created_at_raw, id_raw = raw.split(_SEPARATOR, 1)
        return datetime.fromisoformat(created_at_raw), UUID(id_raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationAppError(f"Invalid pagination cursor: {cursor!r}") from exc
