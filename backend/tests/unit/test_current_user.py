"""Unit tests for `core.security.current_user` (BLUEPRINT.md §3.9, §8 step 7).

Exercises `_decode_user_id` directly -- the stateless-JWT-verification core
of `get_current_user_id` -- rather than the module-level `AUTH_ENABLED`
branch itself, which is decided once at *import* time from a tier-1 static
`Settings` value (this module's own docstring) and so isn't something a
single test process can flip mid-run. The full request-level behavior
(401 without a token, 200 with one, `AUTH_ENABLED=true` being the process
default) is covered end-to-end by `tests/integration/test_auth_api.py`.
"""

from __future__ import annotations

import uuid

import jwt
import pytest

from core.config import settings
from core.errors.exceptions import UnauthorizedError
from core.security.current_user import _TOKEN_AUDIENCE, ANONYMOUS_USER_ID, _decode_user_id


def _make_token(
    *, sub: object = None, audience: str | None = _TOKEN_AUDIENCE, secret: str | None = None
) -> str:
    payload: dict[str, object] = {}
    if sub is not None:
        payload["sub"] = sub
    if audience is not None:
        payload["aud"] = [audience]
    return jwt.encode(payload, secret or settings.JWT_SECRET, algorithm="HS256")


def test_decode_user_id_round_trips_a_validly_signed_token() -> None:
    user_id = uuid.uuid4()

    token = _make_token(sub=str(user_id))

    assert _decode_user_id(token) == user_id


def test_decode_user_id_rejects_a_token_signed_with_a_different_secret() -> None:
    token = _make_token(sub=str(uuid.uuid4()), secret="a-different-secret")

    with pytest.raises(UnauthorizedError):
        _decode_user_id(token)


def test_decode_user_id_rejects_a_token_with_the_wrong_audience() -> None:
    token = _make_token(sub=str(uuid.uuid4()), audience="some-other-audience")

    with pytest.raises(UnauthorizedError):
        _decode_user_id(token)


def test_decode_user_id_rejects_a_token_with_no_subject_claim() -> None:
    token = _make_token(sub=None)

    with pytest.raises(UnauthorizedError):
        _decode_user_id(token)


def test_decode_user_id_rejects_a_non_uuid_subject() -> None:
    token = _make_token(sub="not-a-uuid")

    with pytest.raises(UnauthorizedError):
        _decode_user_id(token)


def test_decode_user_id_rejects_garbage() -> None:
    with pytest.raises(UnauthorizedError):
        _decode_user_id("not.a.jwt")


def test_anonymous_user_id_is_a_fixed_well_known_constant() -> None:
    assert str(ANONYMOUS_USER_ID) == "00000000-0000-0000-0000-000000000001"
