"""
Unit tests for balance_service data-access helpers and get_balance_response.

These tests intentionally avoid Flask and real DB access. Every DB interaction is
mocked through a fake SQLAlchemy session object.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.app.errors import AppError, ErrorCode
from backend.app.models.expense import Category
from backend.app.services import balance_service


def _mock_scalars_all(session: MagicMock, rows: list) -> None:
    session.execute.return_value.scalars.return_value.all.return_value = rows


def test_get_active_expenses_applies_deleted_filter_and_optional_category():
    session = MagicMock()
    rows = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    _mock_scalars_all(session, rows)

    result = balance_service.get_active_expenses(
        group_id=10,
        session=session,
        category=Category.FOOD,
    )

    assert result == rows
    session.execute.assert_called_once()


def test_get_splits_for_active_expenses_applies_optional_category():
    session = MagicMock()
    rows = [SimpleNamespace(id=11), SimpleNamespace(id=12)]
    _mock_scalars_all(session, rows)

    result = balance_service.get_splits_for_active_expenses(
        group_id=7,
        session=session,
        category=Category.TRANSPORT,
    )

    assert result == rows
    session.execute.assert_called_once()


def test_get_settlements_returns_all_rows():
    session = MagicMock()
    rows = [SimpleNamespace(id=101)]
    _mock_scalars_all(session, rows)

    result = balance_service.get_settlements(group_id=3, session=session)

    assert result == rows
    session.execute.assert_called_once()


def test_get_member_ids_returns_scalars():
    session = MagicMock()
    member_ids = [1, 2, 5]
    _mock_scalars_all(session, member_ids)

    result = balance_service.get_member_ids(group_id=9, session=session)

    assert result == member_ids
    session.execute.assert_called_once()


def test_get_members_returns_user_rows():
    session = MagicMock()
    members = [SimpleNamespace(id=1, username="alice"), SimpleNamespace(id=2, username="bob")]
    _mock_scalars_all(session, members)

    result = balance_service.get_members(group_id=9, session=session)

    assert result == members
    session.execute.assert_called_once()


def test_get_balance_response_raises_group_not_found():
    session = MagicMock()
    session.get.return_value = None

    with pytest.raises(AppError) as exc_info:
        balance_service.get_balance_response(group_id=999, caller_id=1, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.GROUP_NOT_FOUND
    assert err.http_status == 404


@patch("backend.app.services.balance_service.get_member_ids", return_value=[2, 3])
def test_get_balance_response_raises_forbidden_for_non_member(mock_member_ids):
    session = MagicMock()
    session.get.return_value = SimpleNamespace(id=42)

    with pytest.raises(AppError) as exc_info:
        balance_service.get_balance_response(group_id=42, caller_id=1, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.FORBIDDEN
    assert err.http_status == 403
    mock_member_ids.assert_called_once()


@patch("backend.app.services.balance_service.simplify_debts")
@patch("backend.app.services.balance_service.get_members")
@patch("backend.app.services.balance_service.compute_balances")
@patch("backend.app.services.balance_service.get_member_ids", return_value=[1, 2])
def test_get_balance_response_unfiltered_happy_path(
    mock_member_ids,
    mock_compute_balances,
    mock_get_members,
    mock_simplify_debts,
):
    session = MagicMock()
    session.get.return_value = SimpleNamespace(id=1)

    mock_compute_balances.return_value = {
        1: Decimal("10.00"),
        2: Decimal("-10.00"),
    }
    mock_get_members.return_value = [
        SimpleNamespace(id=1, username="alice"),
        SimpleNamespace(id=2, username="bob"),
    ]
    mock_simplify_debts.return_value = [
        {"from_user_id": 2, "to_user_id": 1, "amount": Decimal("10.00")}
    ]

    payload = balance_service.get_balance_response(group_id=1, caller_id=1, session=session)

    assert payload["group_id"] == 1
    assert payload["balance_sum"] == "0.00"
    assert payload["balances"] == [
        {"user_id": 1, "name": "alice", "balance": "10.00"},
        {"user_id": 2, "name": "bob", "balance": "-10.00"},
    ]
    assert payload["simplified_debts"] == [
        {
            "from_user_id": 2,
            "from_name": "bob",
            "to_user_id": 1,
            "to_name": "alice",
            "amount": "10.00",
        }
    ]

    mock_member_ids.assert_called_once()
    mock_compute_balances.assert_called_once()
    mock_get_members.assert_called_once()
    mock_simplify_debts.assert_called_once()


@patch("backend.app.services.balance_service.get_members")
@patch("backend.app.services.balance_service.compute_balances")
@patch("backend.app.services.balance_service.get_member_ids", return_value=[1, 2])
def test_get_balance_response_unfiltered_raises_internal_error_on_nonzero_sum(
    mock_member_ids,
    mock_compute_balances,
    mock_get_members,
):
    session = MagicMock()
    session.get.return_value = SimpleNamespace(id=1)

    mock_compute_balances.return_value = {
        1: Decimal("10.00"),
        2: Decimal("-9.99"),
    }
    mock_get_members.return_value = [
        SimpleNamespace(id=1, username="alice"),
        SimpleNamespace(id=2, username="bob"),
    ]

    with pytest.raises(AppError) as exc_info:
        balance_service.get_balance_response(group_id=1, caller_id=1, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.INTERNAL_ERROR
    assert err.http_status == 500

    mock_member_ids.assert_called_once()
    mock_compute_balances.assert_called_once()
    mock_get_members.assert_called_once()


@patch("backend.app.services.balance_service.simplify_debts")
@patch("backend.app.services.balance_service.get_members")
@patch("backend.app.services.balance_service.compute_balances")
@patch("backend.app.services.balance_service.get_member_ids", return_value=[1, 2])
def test_get_balance_response_category_filtered_skips_simplification(
    mock_member_ids,
    mock_compute_balances,
    mock_get_members,
    mock_simplify_debts,
):
    session = MagicMock()
    session.get.return_value = SimpleNamespace(id=1)

    mock_compute_balances.return_value = {
        1: Decimal("7.00"),
        2: Decimal("-3.00"),
    }
    mock_get_members.return_value = [
        SimpleNamespace(id=1, username="alice"),
        SimpleNamespace(id=2, username="bob"),
    ]

    payload = balance_service.get_balance_response(
        group_id=1,
        caller_id=1,
        session=session,
        category=Category.FOOD,
    )

    assert payload["simplified_debts"] == []
    assert payload["balance_sum"] == "4.00"
    mock_simplify_debts.assert_not_called()
    mock_member_ids.assert_called_once()
    mock_compute_balances.assert_called_once()
    mock_get_members.assert_called_once()
