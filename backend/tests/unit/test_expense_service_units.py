"""
Unit tests for expense_service helper and service paths.

These tests focus on previously uncovered branches in expense_service while
staying DB-free via mocked session/query behavior.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.app.errors import AppError, ErrorCode
from backend.app.models.expense import Category, SplitMode
from backend.app.services import expense_service


def _mock_scalars_all(session: MagicMock, rows: list) -> None:
    session.execute.return_value.scalars.return_value.all.return_value = rows


def test_get_group_or_404_returns_group_when_present():
    session = MagicMock()
    group = SimpleNamespace(id=1, owner_user_id=1)
    session.get.return_value = group

    result = expense_service._get_group_or_404(group_id=1, session=session)

    assert result is group


def test_get_group_or_404_raises_when_missing():
    session = MagicMock()
    session.get.return_value = None

    with pytest.raises(AppError) as exc_info:
        expense_service._get_group_or_404(group_id=404, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.GROUP_NOT_FOUND
    assert err.http_status == 404


def test_get_expense_or_404_returns_expense_when_present():
    session = MagicMock()
    expense = SimpleNamespace(id=10, group_id=1)
    session.get.return_value = expense

    result = expense_service._get_expense_or_404(expense_id=10, session=session)

    assert result is expense


def test_get_expense_or_404_raises_when_missing():
    session = MagicMock()
    session.get.return_value = None

    with pytest.raises(AppError) as exc_info:
        expense_service._get_expense_or_404(expense_id=404, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.EXPENSE_NOT_FOUND
    assert err.http_status == 404


def test_require_member_passes_when_membership_exists():
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = object()

    expense_service._require_member(group_id=1, user_id=1, session=session)

    session.execute.assert_called_once()


def test_require_member_raises_forbidden_when_missing():
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    with pytest.raises(AppError) as exc_info:
        expense_service._require_member(group_id=1, user_id=999, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.FORBIDDEN
    assert err.http_status == 403


def test_get_member_ids_reads_scalars():
    session = MagicMock()
    member_ids = [1, 2, 3]
    _mock_scalars_all(session, member_ids)

    result = expense_service._get_member_ids(group_id=7, session=session)

    assert result == member_ids
    session.execute.assert_called_once()


def test_validate_payer_is_member_raises_for_non_member():
    with pytest.raises(AppError) as exc_info:
        expense_service._validate_payer_is_member(
            paid_by_user_id=5,
            group_id=1,
            member_ids=[1, 2, 3],
        )

    err = exc_info.value
    assert err.code == ErrorCode.PAYER_NOT_MEMBER
    assert err.http_status == 422
    assert err.field == "paid_by_user_id"


def test_validate_split_users_are_members_raises_on_first_invalid_user():
    splits = [
        {"user_id": 1, "amount": Decimal("5.00")},
        {"user_id": 9, "amount": Decimal("5.00")},
    ]

    with pytest.raises(AppError) as exc_info:
        expense_service._validate_split_users_are_members(
            splits=splits,
            group_id=1,
            member_ids=[1, 2, 3],
        )

    err = exc_info.value
    assert err.code == ErrorCode.SPLIT_USER_NOT_MEMBER
    assert err.http_status == 422
    assert err.field == "splits"


def test_compute_equal_splits_internal_error_branch(monkeypatch):
    # Inject a broken module-level sum() to force the defensive INTERNAL_ERROR branch.
    monkeypatch.setattr(
        expense_service,
        "sum",
        lambda *args, **kwargs: Decimal("999.99"),
        raising=False,
    )

    with pytest.raises(AppError) as exc_info:
        expense_service._compute_equal_splits(
            amount=Decimal("10.00"),
            participant_ids=[1, 2, 3],
            payer_id=1,
        )

    err = exc_info.value
    assert err.code == ErrorCode.INTERNAL_ERROR
    assert err.http_status == 500


def test_delete_splits_deletes_all_rows_and_flushes():
    session = MagicMock()
    expense = SimpleNamespace(splits=[SimpleNamespace(id=1), SimpleNamespace(id=2)])

    expense_service._delete_splits(expense=expense, session=session)

    assert session.delete.call_count == 2
    session.flush.assert_called_once()


@patch("backend.app.services.expense_service.Split")
def test_create_split_rows_adds_split_models_and_flushes(mock_split_cls):
    session = MagicMock()
    expense = SimpleNamespace(id=88)
    splits = [
        {"user_id": 1, "amount": Decimal("4.00")},
        {"user_id": 2, "amount": Decimal("6.00")},
    ]

    expense_service._create_split_rows(expense=expense, splits_data=splits, session=session)

    assert session.add.call_count == 2
    session.flush.assert_called_once()


@patch("backend.app.services.expense_service._create_split_rows")
@patch("backend.app.services.expense_service.Expense")
@patch("backend.app.services.expense_service._get_member_ids", return_value=[1, 2])
@patch("backend.app.services.expense_service._validate_payer_is_member")
@patch("backend.app.services.expense_service._require_member")
@patch("backend.app.services.expense_service._get_group_or_404")
def test_create_expense_equal_mode_success(
    mock_get_group,
    mock_require_member,
    mock_validate_payer,
    mock_get_member_ids,
    mock_expense_cls,
    mock_create_split_rows,
):
    session = MagicMock()
    mock_get_group.return_value = SimpleNamespace(id=1, owner_user_id=1)
    mock_expense_cls.side_effect = lambda **kwargs: SimpleNamespace(
        id=101,
        splits=[],
        **kwargs,
    )

    data = {
        "paid_by_user_id": 1,
        "amount": Decimal("10.00"),
        "description": "Lunch",
        "split_mode": SplitMode.EQUAL,
        "category": Category.FOOD,
    }

    expense = expense_service.create_expense(
        group_id=1,
        caller_id=1,
        data=data,
        session=session,
    )

    assert expense.group_id == 1
    assert expense.paid_by_user_id == 1
    assert expense.amount == Decimal("10.00")
    assert expense.split_mode == SplitMode.EQUAL
    assert expense.category == Category.FOOD
    session.add.assert_called()
    session.flush.assert_called()
    session.refresh.assert_called_once_with(expense)
    mock_create_split_rows.assert_called_once()
    mock_require_member.assert_called_once()
    mock_validate_payer.assert_called_once()
    mock_get_member_ids.assert_called_once()


@patch("backend.app.services.expense_service._create_split_rows")
@patch("backend.app.services.expense_service.Expense")
@patch("backend.app.services.expense_service._validate_split_sum")
@patch("backend.app.services.expense_service._validate_split_users_are_members")
@patch("backend.app.services.expense_service._get_member_ids", return_value=[1, 2])
@patch("backend.app.services.expense_service._validate_payer_is_member")
@patch("backend.app.services.expense_service._require_member")
@patch("backend.app.services.expense_service._get_group_or_404")
def test_create_expense_custom_mode_success(
    mock_get_group,
    mock_require_member,
    mock_validate_payer,
    mock_get_member_ids,
    mock_validate_split_users,
    mock_validate_split_sum,
    mock_expense_cls,
    mock_create_split_rows,
):
    session = MagicMock()
    mock_get_group.return_value = SimpleNamespace(id=1, owner_user_id=1)
    mock_expense_cls.side_effect = lambda **kwargs: SimpleNamespace(
        id=102,
        splits=[],
        **kwargs,
    )

    custom_splits = [
        {"user_id": 1, "amount": Decimal("6.00")},
        {"user_id": 2, "amount": Decimal("4.00")},
    ]
    data = {
        "paid_by_user_id": 1,
        "amount": Decimal("10.00"),
        "description": "Taxi",
        "split_mode": SplitMode.CUSTOM,
        "splits": custom_splits,
    }

    expense = expense_service.create_expense(
        group_id=1,
        caller_id=1,
        data=data,
        session=session,
    )

    assert expense.amount == Decimal("10.00")
    assert expense.split_mode == SplitMode.CUSTOM
    assert expense.category == Category.OTHER  # default when missing in payload
    mock_create_split_rows.assert_called_once()
    mock_validate_split_users.assert_called_once_with(custom_splits, 1, [1, 2])
    mock_validate_split_sum.assert_called_once_with(custom_splits, Decimal("10.00"), 1)


@patch("backend.app.services.expense_service._require_member")
@patch("backend.app.services.expense_service._get_group_or_404")
def test_list_expenses_returns_scalars(mock_get_group, mock_require_member):
    session = MagicMock()
    mock_get_group.return_value = SimpleNamespace(id=1)
    rows = [SimpleNamespace(id=11), SimpleNamespace(id=12)]
    _mock_scalars_all(session, rows)

    result = expense_service.list_expenses(group_id=1, caller_id=1, session=session)

    assert result == rows
    mock_get_group.assert_called_once()
    mock_require_member.assert_called_once()
    session.execute.assert_called_once()


@patch("backend.app.services.expense_service._require_member")
@patch("backend.app.services.expense_service._get_expense_or_404")
def test_get_expense_requires_membership_and_returns_row(mock_get_expense_or_404, mock_require_member):
    session = MagicMock()
    expense = SimpleNamespace(id=22, group_id=3)
    mock_get_expense_or_404.return_value = expense

    result = expense_service.get_expense(expense_id=22, caller_id=1, session=session)

    assert result is expense
    mock_get_expense_or_404.assert_called_once_with(22, session)
    mock_require_member.assert_called_once_with(3, 1, session)


@patch("backend.app.services.expense_service._require_member")
@patch("backend.app.services.expense_service._get_expense_or_404")
def test_edit_expense_rejects_deleted(mock_get_expense_or_404, mock_require_member):
    session = MagicMock()
    mock_get_expense_or_404.return_value = SimpleNamespace(
        id=1,
        group_id=1,
        is_deleted=True,
        paid_by_user_id=1,
        split_mode=SplitMode.CUSTOM,
        amount=Decimal("10.00"),
        splits=[],
    )

    with pytest.raises(AppError) as exc_info:
        expense_service.edit_expense(expense_id=1, caller_id=1, data={}, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.EXPENSE_DELETED
    assert err.http_status == 422


@patch("backend.app.services.expense_service._get_group_or_404")
@patch("backend.app.services.expense_service._require_member")
@patch("backend.app.services.expense_service._get_expense_or_404")
def test_edit_expense_forbidden_for_non_payer_non_owner(
    mock_get_expense_or_404,
    mock_require_member,
    mock_get_group,
):
    session = MagicMock()
    mock_get_expense_or_404.return_value = SimpleNamespace(
        id=1,
        group_id=1,
        is_deleted=False,
        paid_by_user_id=100,
        split_mode=SplitMode.CUSTOM,
        amount=Decimal("10.00"),
        splits=[],
    )
    mock_get_group.return_value = SimpleNamespace(id=1, owner_user_id=200)

    with pytest.raises(AppError) as exc_info:
        expense_service.edit_expense(expense_id=1, caller_id=300, data={}, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.FORBIDDEN
    assert err.http_status == 403


@patch("backend.app.services.expense_service._create_split_rows")
@patch("backend.app.services.expense_service._delete_splits")
@patch("backend.app.services.expense_service._compute_equal_splits")
@patch("backend.app.services.expense_service._get_member_ids", return_value=[1, 2])
@patch("backend.app.services.expense_service._validate_payer_is_member")
@patch("backend.app.services.expense_service._get_group_or_404")
@patch("backend.app.services.expense_service._require_member")
@patch("backend.app.services.expense_service._get_expense_or_404")
def test_edit_expense_equal_mode_recomputes_and_updates_fields(
    mock_get_expense_or_404,
    mock_require_member,
    mock_get_group_or_404,
    mock_validate_payer,
    mock_get_member_ids,
    mock_compute_equal_splits,
    mock_delete_splits,
    mock_create_split_rows,
):
    session = MagicMock()
    expense = SimpleNamespace(
        id=1,
        group_id=1,
        is_deleted=False,
        paid_by_user_id=1,
        split_mode=SplitMode.CUSTOM,
        amount=Decimal("10.00"),
        description="Old",
        category=Category.OTHER,
        splits=[SimpleNamespace(id=1)],
        updated_at=None,
    )
    mock_get_expense_or_404.return_value = expense
    mock_get_group_or_404.return_value = SimpleNamespace(id=1, owner_user_id=1)
    mock_compute_equal_splits.return_value = [
        {"user_id": 1, "amount": Decimal("6.00")},
        {"user_id": 2, "amount": Decimal("6.00")},
    ]

    data = {
        "description": "New",
        "category": Category.FOOD,
        "split_mode": SplitMode.EQUAL,
        "amount": Decimal("12.00"),
    }

    result = expense_service.edit_expense(expense_id=1, caller_id=1, data=data, session=session)

    assert result is expense
    assert expense.description == "New"
    assert expense.category == Category.FOOD
    assert expense.split_mode == SplitMode.EQUAL
    assert expense.amount == Decimal("12.00")
    assert expense.updated_at is not None

    mock_validate_payer.assert_not_called()
    mock_get_member_ids.assert_called_once_with(1, session)
    mock_compute_equal_splits.assert_called_once_with(Decimal("12.00"), [1, 2], 1)
    mock_delete_splits.assert_called_once_with(expense, session)
    mock_create_split_rows.assert_called_once()
    session.flush.assert_called_once()
    session.refresh.assert_called_once_with(expense)


@patch("backend.app.services.expense_service._create_split_rows")
@patch("backend.app.services.expense_service._delete_splits")
@patch("backend.app.services.expense_service._validate_split_sum")
@patch("backend.app.services.expense_service._validate_split_users_are_members")
@patch("backend.app.services.expense_service._get_member_ids", return_value=[1, 2])
@patch("backend.app.services.expense_service._validate_payer_is_member")
@patch("backend.app.services.expense_service._get_group_or_404")
@patch("backend.app.services.expense_service._require_member")
@patch("backend.app.services.expense_service._get_expense_or_404")
def test_edit_expense_custom_revalidates_and_rewrites_splits(
    mock_get_expense_or_404,
    mock_require_member,
    mock_get_group_or_404,
    mock_validate_payer,
    mock_get_member_ids,
    mock_validate_split_users,
    mock_validate_split_sum,
    mock_delete_splits,
    mock_create_split_rows,
):
    session = MagicMock()
    expense = SimpleNamespace(
        id=1,
        group_id=1,
        is_deleted=False,
        paid_by_user_id=1,
        split_mode=SplitMode.CUSTOM,
        amount=Decimal("10.00"),
        description="Old",
        category=Category.OTHER,
        splits=[SimpleNamespace(id=1)],
        updated_at=None,
    )
    mock_get_expense_or_404.return_value = expense
    mock_get_group_or_404.return_value = SimpleNamespace(id=1, owner_user_id=99)

    new_splits = [
        {"user_id": 1, "amount": Decimal("7.00")},
        {"user_id": 2, "amount": Decimal("5.00")},
    ]
    data = {
        "paid_by_user_id": 2,
        "amount": Decimal("12.00"),
        "splits": new_splits,
    }

    result = expense_service.edit_expense(expense_id=1, caller_id=1, data=data, session=session)

    assert result is expense
    assert expense.paid_by_user_id == 2
    assert expense.amount == Decimal("12.00")
    assert expense.updated_at is not None

    assert mock_get_member_ids.call_count == 2
    mock_validate_payer.assert_any_call(2, 1, [1, 2])
    mock_validate_payer.assert_any_call(2, 1, [1, 2])
    mock_validate_split_users.assert_called_once_with(new_splits, 1, [1, 2])
    mock_validate_split_sum.assert_called_once_with(new_splits, Decimal("12.00"), 1)
    mock_delete_splits.assert_called_once_with(expense, session)
    mock_create_split_rows.assert_called_once_with(expense, new_splits, session)
    session.flush.assert_called_once()
    session.refresh.assert_called_once_with(expense)


@patch("backend.app.services.expense_service._get_group_or_404")
@patch("backend.app.services.expense_service._require_member")
@patch("backend.app.services.expense_service._get_expense_or_404")
def test_delete_expense_sets_deleted_at_for_authorized_user(
    mock_get_expense_or_404,
    mock_require_member,
    mock_get_group_or_404,
):
    session = MagicMock()
    expense = SimpleNamespace(
        id=1,
        group_id=1,
        paid_by_user_id=1,
        is_deleted=False,
        deleted_at=None,
    )
    mock_get_expense_or_404.return_value = expense
    mock_get_group_or_404.return_value = SimpleNamespace(id=1, owner_user_id=99)

    expense_service.delete_expense(expense_id=1, caller_id=1, session=session)

    assert expense.deleted_at is not None
    session.flush.assert_called_once()


@patch("backend.app.services.expense_service._get_group_or_404")
@patch("backend.app.services.expense_service._require_member")
@patch("backend.app.services.expense_service._get_expense_or_404")
def test_delete_expense_idempotent_when_already_deleted(
    mock_get_expense_or_404,
    mock_require_member,
    mock_get_group_or_404,
):
    session = MagicMock()
    expense = SimpleNamespace(
        id=1,
        group_id=1,
        paid_by_user_id=1,
        is_deleted=True,
        deleted_at="already-set",
    )
    mock_get_expense_or_404.return_value = expense
    mock_get_group_or_404.return_value = SimpleNamespace(id=1, owner_user_id=99)

    expense_service.delete_expense(expense_id=1, caller_id=1, session=session)

    session.flush.assert_not_called()


@patch("backend.app.services.expense_service._get_group_or_404")
@patch("backend.app.services.expense_service._require_member")
@patch("backend.app.services.expense_service._get_expense_or_404")
def test_delete_expense_forbidden_for_non_owner_non_payer(
    mock_get_expense_or_404,
    mock_require_member,
    mock_get_group_or_404,
):
    session = MagicMock()
    expense = SimpleNamespace(
        id=1,
        group_id=1,
        paid_by_user_id=100,
        is_deleted=False,
        deleted_at=None,
    )
    mock_get_expense_or_404.return_value = expense
    mock_get_group_or_404.return_value = SimpleNamespace(id=1, owner_user_id=200)

    with pytest.raises(AppError) as exc_info:
        expense_service.delete_expense(expense_id=1, caller_id=300, session=session)

    err = exc_info.value
    assert err.code == ErrorCode.FORBIDDEN
    assert err.http_status == 403
