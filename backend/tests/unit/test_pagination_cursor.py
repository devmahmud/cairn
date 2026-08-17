"""Unit tests for the conversations module's cursor codec (BLUEPRINT.md §3.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from core.errors.exceptions import ValidationAppError
from modules.conversations.pagination import decode_cursor, encode_cursor


def test_encode_decode_round_trips() -> None:
    created_at = datetime(2026, 8, 17, 12, 30, 0, tzinfo=UTC)
    id_ = uuid4()

    cursor = encode_cursor(created_at, id_)
    decoded_created_at, decoded_id = decode_cursor(cursor)

    assert decoded_created_at == created_at
    assert decoded_id == id_


def test_encode_cursor_is_url_safe() -> None:
    cursor = encode_cursor(datetime.now(UTC), uuid4())

    # base64.urlsafe_* never emits '+' or '/'.
    assert "+" not in cursor
    assert "/" not in cursor


@pytest.mark.parametrize(
    "garbage",
    [
        "not-base64-!!!",
        "",
        "dGhpcyBoYXMgbm8gc2VwYXJhdG9y",  # valid base64, no "|" separator
    ],
)
def test_decode_cursor_rejects_malformed_input(garbage: str) -> None:
    with pytest.raises(ValidationAppError):
        decode_cursor(garbage)
