"""Unit tests for `core.observability.logging.censor_sensitive_data` (BLUEPRINT.md §3.9).

Pure-function tests against the processor directly -- no `structlog.configure`
call, no renderer involved (§3.11: unit tests are fixture-backed, no network).
"""

from __future__ import annotations

from core.observability.logging import censor_sensitive_data

_REDACTED = "***REDACTED***"


def test_redacts_a_top_level_sensitive_key() -> None:
    out = censor_sensitive_data(None, "info", {"event": "login", "password": "hunter2"})

    assert out["password"] == _REDACTED
    assert out["event"] == "login"


def test_redacts_case_insensitively_and_by_substring() -> None:
    out = censor_sensitive_data(
        None,
        "info",
        {"Authorization": "Bearer abc", "refresh_token": "xyz", "x-api-key": "k"},
    )

    assert out["Authorization"] == _REDACTED
    assert out["refresh_token"] == _REDACTED
    assert out["x-api-key"] == _REDACTED


def test_redacts_nested_mappings_but_leaves_other_values_alone() -> None:
    out = censor_sensitive_data(
        None,
        "info",
        {"user": {"email": "a@b.com", "hashed_password": "$2b$..."}, "count": 3},
    )

    assert out["user"]["email"] == "a@b.com"
    assert out["user"]["hashed_password"] == _REDACTED
    assert out["count"] == 3


def test_redacts_sensitive_values_inside_a_list() -> None:
    out = censor_sensitive_data(None, "info", {"secret": ["a", "b"]})

    assert out["secret"] == [_REDACTED, _REDACTED]


def test_does_not_touch_a_plain_string_value_as_if_it_were_a_sequence() -> None:
    out = censor_sensitive_data(None, "info", {"message": "hello world"})

    assert out["message"] == "hello world"
