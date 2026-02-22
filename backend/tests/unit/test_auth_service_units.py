"""
Unit tests for auth_service branches not naturally hit in integration flow.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.errors import AppError, ErrorCode
from app.services import auth_service


def test_get_current_user_returns_serialized_user():
    session = MagicMock()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session.get.return_value = SimpleNamespace(
        id=7,
        username="alice",
        email="alice@example.com",
        created_at=created_at,
    )

    result = auth_service.get_current_user(user_id=7, session=session)

    assert result == {
        "id": 7,
        "username": "alice",
        "email": "alice@example.com",
        "created_at": created_at.isoformat(),
    }


def test_get_current_user_raises_user_not_found():
    session = MagicMock()
    session.get.return_value = None

    with pytest.raises(AppError) as exc_info:
        auth_service.get_current_user(user_id=99999, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.USER_NOT_FOUND
    assert err.http_status == 404
