"""
Unit tests for group_service branches that are lightly exercised by integration tests.

These tests run DB-free with mocked session/query behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.errors import AppError, ErrorCode
from app.services import group_service


def _mock_scalars_all(session: MagicMock, rows: list) -> None:
    session.execute.return_value.scalars.return_value.all.return_value = rows


def test_get_group_or_404_raises_when_group_missing():
    session = MagicMock()
    session.get.return_value = None

    with pytest.raises(AppError) as exc_info:
        group_service._get_group_or_404(group_id=404, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.GROUP_NOT_FOUND
    assert err.http_status == 404


def test_require_member_passes_when_membership_exists():
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = object()

    group_service._require_member(group_id=1, user_id=10, session=session)

    session.execute.assert_called_once()


def test_require_member_raises_forbidden_when_missing():
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(AppError) as exc_info:
        group_service._require_member(group_id=1, user_id=999, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.FORBIDDEN
    assert err.http_status == 403


def test_list_groups_serializes_groups():
    session = MagicMock()
    ts1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(id=1, name="Trip", owner_user_id=10, created_at=ts1),
        SimpleNamespace(id=2, name="Home", owner_user_id=20, created_at=ts2),
    ]
    _mock_scalars_all(session, rows)

    result = group_service.list_groups(user_id=10, session=session)

    assert result == [
        {
            "id": 1,
            "name": "Trip",
            "owner_user_id": 10,
            "created_at": ts1.isoformat(),
        },
        {
            "id": 2,
            "name": "Home",
            "owner_user_id": 20,
            "created_at": ts2.isoformat(),
        },
    ]
    session.execute.assert_called_once()


@patch("app.services.group_service._build_group_dict")
@patch("app.services.group_service._require_member")
@patch("app.services.group_service._get_group_or_404")
def test_get_group_returns_group_with_members(
    mock_get_group_or_404,
    mock_require_member,
    mock_build_group_dict,
):
    session = MagicMock()
    group = SimpleNamespace(id=11)
    members = [
        SimpleNamespace(id=1, username="alice", email="a@example.com"),
        SimpleNamespace(id=2, username="bob", email="b@example.com"),
    ]
    _mock_scalars_all(session, members)

    mock_get_group_or_404.return_value = group
    mock_build_group_dict.return_value = {"id": 11, "members": []}

    result = group_service.get_group(group_id=11, caller_id=1, session=session)

    assert result == {"id": 11, "members": []}
    mock_get_group_or_404.assert_called_once_with(11, session)
    mock_require_member.assert_called_once_with(11, 1, session)
    mock_build_group_dict.assert_called_once_with(group, members)
    session.execute.assert_called_once()


@patch("app.services.group_service._get_group_or_404")
def test_add_member_non_owner_raises_forbidden(mock_get_group_or_404):
    session = MagicMock()
    mock_get_group_or_404.return_value = SimpleNamespace(id=1, owner_user_id=100)

    with pytest.raises(AppError) as exc_info:
        group_service.add_member(
            group_id=1,
            caller_id=200,
            target_user_id=300,
            session=session,
        )

    err = exc_info.value
    assert err.code == ErrorCode.FORBIDDEN
    assert err.http_status == 403


@patch("app.services.group_service._get_group_or_404")
def test_add_member_target_user_missing_raises_404(mock_get_group_or_404):
    session = MagicMock()
    mock_get_group_or_404.return_value = SimpleNamespace(id=1, owner_user_id=100)
    session.get.return_value = None

    with pytest.raises(AppError) as exc_info:
        group_service.add_member(
            group_id=1,
            caller_id=100,
            target_user_id=999,
            session=session,
        )

    err = exc_info.value
    assert err.code == ErrorCode.USER_NOT_FOUND
    assert err.http_status == 404


@patch("app.services.group_service._get_group_or_404")
def test_add_member_already_member_raises_409(mock_get_group_or_404):
    session = MagicMock()
    mock_get_group_or_404.return_value = SimpleNamespace(id=1, owner_user_id=100)
    session.get.return_value = SimpleNamespace(id=222, username="bob")
    session.execute.return_value.scalar_one_or_none.return_value = object()

    with pytest.raises(AppError) as exc_info:
        group_service.add_member(
            group_id=1,
            caller_id=100,
            target_user_id=222,
            session=session,
        )

    err = exc_info.value
    assert err.code == ErrorCode.ALREADY_MEMBER
    assert err.http_status == 409


@patch("app.services.group_service._require_member")
@patch("app.services.group_service._get_group_or_404")
def test_remove_member_non_owner_cannot_remove_other(
    mock_get_group_or_404,
    mock_require_member,
):
    session = MagicMock()
    mock_get_group_or_404.return_value = SimpleNamespace(id=1, owner_user_id=10)

    with pytest.raises(AppError) as exc_info:
        group_service.remove_member(
            group_id=1,
            caller_id=20,     # not owner
            target_user_id=30,  # not self
            session=session,
        )

    err = exc_info.value
    assert err.code == ErrorCode.FORBIDDEN
    assert err.http_status == 403
    mock_require_member.assert_called_once_with(1, 20, session)


@patch("app.services.group_service._require_member")
@patch("app.services.group_service._get_group_or_404")
def test_remove_member_raises_user_not_found_when_target_not_member(
    mock_get_group_or_404,
    mock_require_member,
):
    session = MagicMock()
    mock_get_group_or_404.return_value = SimpleNamespace(id=1, owner_user_id=10)
    session.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(AppError) as exc_info:
        group_service.remove_member(
            group_id=1,
            caller_id=10,      # owner
            target_user_id=30,  # remove someone not in group
            session=session,
        )

    err = exc_info.value
    assert err.code == ErrorCode.USER_NOT_FOUND
    assert err.http_status == 404
    mock_require_member.assert_called_once_with(1, 10, session)


@patch("app.services.group_service._require_member")
@patch("app.services.group_service._get_group_or_404")
def test_remove_member_owner_success_deletes_membership(
    mock_get_group_or_404,
    mock_require_member,
):
    session = MagicMock()
    membership = SimpleNamespace(user_id=30, group_id=1)
    mock_get_group_or_404.return_value = SimpleNamespace(id=1, owner_user_id=10)
    session.execute.return_value.scalar_one_or_none.return_value = membership

    group_service.remove_member(
        group_id=1,
        caller_id=10,      # owner
        target_user_id=30,
        session=session,
    )

    mock_require_member.assert_called_once_with(1, 10, session)
    session.delete.assert_called_once_with(membership)
    session.flush.assert_called_once()
