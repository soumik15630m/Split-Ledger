"""
services/expense_service.py — Expense business logic.

Invariants enforced here (ARCHITECTURE.md Section 4):
  INV-1  SPLIT_SUM_MISMATCH (422)      — sum(splits.amount) == expense.amount exactly
  INV-5  PAYER_NOT_MEMBER (422)        — paid_by_user_id must be a group member
  INV-6  SPLIT_USER_NOT_MEMBER (422)   — every split.user_id must be a group member
  INV-8  EXPENSE_DELETED (422)         — cannot edit a soft-deleted expense
  INV-9  FORBIDDEN (403)               — caller must be a group member

Authorization rules:
  - Create: caller must be a group member (INV-9); paid_by_user_id must be a member (INV-5)
  - List:   caller must be a group member (INV-9)
  - Get:    caller must be a member of the expense's group (INV-9)
  - Edit:   caller must be the original payer OR the group owner (spec Section 7.2)
  - Delete: caller must be the original payer OR the group owner (consistent with edit)

Equal split computation (spec Section 9.2):
  - Server divides amount among ALL current group members using ROUND_DOWN.
  - Remainder (1 cent) is added to the payer's split.
  - This guarantees sum(splits) == amount — maintains INV-1.

Layer rules (GUIDE Rule 3):
  - No Flask imports. No current_app, request, g, or HTTP knowledge.
  - Receives plain ints and dicts; returns ORM objects or raises AppError.
  - Commits are the route's responsibility — only flush here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError, ErrorCode
from app.models.expense import Category, Expense, SplitMode
from app.models.group import Group
from app.models.membership import Membership
from app.models.split import Split
from app.models.user import User


# ── Private helpers ────────────────────────────────────────────────────────

def _get_group_or_404(group_id: int, session: Session) -> Group:
    """Returns the Group or raises GROUP_NOT_FOUND (404)."""
    group = session.get(Group, group_id)
    if group is None:
        raise AppError(
            ErrorCode.GROUP_NOT_FOUND,
            f"Group {group_id} does not exist.",
            404,
        )
    return group


def _get_expense_or_404(expense_id: int, session: Session) -> Expense:
    """Returns the Expense (active or deleted) or raises EXPENSE_NOT_FOUND (404)."""
    expense = session.get(Expense, expense_id)
    if expense is None:
        raise AppError(
            ErrorCode.EXPENSE_NOT_FOUND,
            f"Expense {expense_id} does not exist.",
            404,
        )
    return expense


def _require_member(group_id: int, user_id: int, session: Session) -> None:
    """
    Raises FORBIDDEN (403) if user_id is not a member of group_id.
    INV-9: non-members receive 403, not 404.
    """
    membership = session.execute(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
            )
    ).scalar_one_or_none()

    if membership is None:
        raise AppError(
            ErrorCode.FORBIDDEN,
            f"You are not a member of group {group_id}.",
            403,
        )


def _get_member_ids(group_id: int, session: Session) -> list[int]:
    """Returns the user_ids of all current members of a group."""
    stmt = select(Membership.user_id).where(Membership.group_id == group_id)
    return list(session.execute(stmt).scalars().all())


def _validate_payer_is_member(
        paid_by_user_id: int,
        group_id: int,
        member_ids: list[int],
) -> None:
    """
    Raises PAYER_NOT_MEMBER (422) if paid_by_user_id is not in the group.
    INV-5: enforced here because the schema cannot perform DB lookups.
    """
    if paid_by_user_id not in member_ids:
        raise AppError(
            ErrorCode.PAYER_NOT_MEMBER,
            f"User {paid_by_user_id} is not a member of group {group_id}.",
            422,
            field="paid_by_user_id",
        )


def _validate_split_users_are_members(
        splits: list[dict],
        group_id: int,
        member_ids: list[int],
) -> None:
    """
    Raises SPLIT_USER_NOT_MEMBER (422) for the first split user not in the group.
    INV-6: enforced here because the schema cannot perform DB lookups.
    """
    member_set = set(member_ids)
    for split in splits:
        if split["user_id"] not in member_set:
            raise AppError(
                ErrorCode.SPLIT_USER_NOT_MEMBER,
                f"User {split['user_id']} is not a member of group {group_id}.",
                422,
                field="splits",
            )


def _validate_split_sum(
        splits: list[dict],
        expected_amount: Decimal,
        group_id: int,
) -> None:
    """
    Raises SPLIT_SUM_MISMATCH (422) if sum(splits.amount) != expected_amount.
    INV-1: the authoritative enforcement point (ARCHITECTURE.md Section 4).
    Uses Decimal arithmetic — never float.
    """
    total = sum(s["amount"] for s in splits)
    if total != expected_amount:
        raise AppError(
            ErrorCode.SPLIT_SUM_MISMATCH,
            f"Split amounts ({total}) do not equal expense amount ({expected_amount}).",
            422,
            field="splits",
        )


def _compute_equal_splits(
        amount: Decimal,
        participant_ids: list[int],
        payer_id: int,
) -> list[dict]:
    """
    Canonical equal split computation. (Spec Section 9.2, ARCHITECTURE.md Section 6)

    Divides amount evenly among all participants using ROUND_DOWN.
    The 1-cent remainder is added to the payer's split.
    Guarantees: sum(result amounts) == amount  — maintains INV-1.

    Args:
        amount:          The full expense amount. Must be Decimal.
        participant_ids: All user_ids who share the expense (all current group members).
        payer_id:        The user_id of the person who paid. Receives the remainder.

    Returns:
        List of {"user_id": int, "amount": Decimal} dicts.
    """
    n = len(participant_ids)
    base = (amount / Decimal(n)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    remainder = amount - (base * n)

    splits = [{"user_id": uid, "amount": base} for uid in participant_ids]

    if remainder > Decimal("0"):
        # Add the remainder to the payer's split. If payer is not in the list
        # (edge case — INV-5 ensures payer is a member; participants = all members),
        # fall back to the first participant.
        payer_split = next(
            (s for s in splits if s["user_id"] == payer_id),
            splits[0],
        )
        payer_split["amount"] += remainder

    # Sanity check — this must always hold; a failure here is a programming error.
    computed_sum = sum(s["amount"] for s in splits)
    if computed_sum != amount:
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            f"Equal split computation produced sum {computed_sum} for amount {amount}. "
            f"This is a bug — please report it.",
            500,
        )

    return splits


def _delete_splits(expense: Expense, session: Session) -> None:
    """Removes all existing splits for an expense. Used before re-creating them on PATCH."""
    for split in list(expense.splits):
        session.delete(split)
    session.flush()


def _create_split_rows(
        expense: Expense,
        splits_data: list[dict],
        session: Session,
) -> None:
    """Creates Split rows for an expense from a list of {user_id, amount} dicts."""
    for s in splits_data:
        split = Split(
            expense_id=expense.id,
            user_id=s["user_id"],
            amount=s["amount"],
        )
        session.add(split)
    session.flush()


# ── Public service functions ───────────────────────────────────────────────

def create_expense(
        group_id: int,
        caller_id: int,
        data: dict,
        session: Session,
) -> Expense:
    """
    Records a new expense for a group.

    Args:
        group_id:  The group this expense belongs to.
        caller_id: The authenticated user creating the expense (from flask.g).
        data:      Validated dict from CreateExpenseSchema.

    Enforces:
      INV-9: caller must be a group member (FORBIDDEN, 403)
      INV-5: paid_by_user_id must be a group member (PAYER_NOT_MEMBER, 422)
      INV-6: every split user_id must be a group member (SPLIT_USER_NOT_MEMBER, 422)
      INV-1: sum(splits.amount) == amount (SPLIT_SUM_MISMATCH, 422)

    Equal split mode (spec Section 9.2):
      Server computes splits across ALL current group members.
      Client must NOT send a splits array — the schema enforces this.

    Returns:
        The newly created Expense ORM object (with splits loaded).
    """
    group = _get_group_or_404(group_id, session)

    # INV-9: caller must be a member.
    _require_member(group_id, caller_id, session)

    paid_by_user_id: int = data["paid_by_user_id"]
    amount: Decimal = data["amount"]
    description: str = data["description"]
    split_mode: SplitMode = data.get("split_mode", SplitMode.CUSTOM)
    category: Category = data.get("category", Category.OTHER)

    member_ids = _get_member_ids(group_id, session)

    # INV-5: paid_by_user_id must be a group member.
    _validate_payer_is_member(paid_by_user_id, group_id, member_ids)

    # Compute split data before writing the expense row.
    if split_mode == SplitMode.EQUAL:
        splits_data = _compute_equal_splits(amount, member_ids, paid_by_user_id)
    else:
        # custom mode — splits provided by the client (validated by schema).
        raw_splits = data.get("splits") or []
        # INV-6: every split user must be a member.
        _validate_split_users_are_members(raw_splits, group_id, member_ids)
        # INV-1: sum(splits) must equal amount.
        _validate_split_sum(raw_splits, amount, group_id)
        splits_data = raw_splits

    # Write the expense row.
    expense = Expense(
        group_id=group_id,
        paid_by_user_id=paid_by_user_id,
        description=description,
        amount=amount,
        split_mode=split_mode,
        category=category,
    )
    session.add(expense)
    session.flush()  # populate expense.id before creating splits

    # Write split rows.
    _create_split_rows(expense, splits_data, session)

    # Refresh to load relationship so _serialize_expense() in the route works.
    session.refresh(expense)
    return expense


def list_expenses(
        group_id: int,
        caller_id: int,
        session: Session,
) -> list[Expense]:
    """
    Returns all active (non-deleted) expenses for a group, newest first.

    INV-8: only expenses WHERE deleted_at IS NULL are returned.
    INV-9: caller must be a group member (FORBIDDEN, 403).
    """
    _get_group_or_404(group_id, session)
    _require_member(group_id, caller_id, session)

    stmt = (
        select(Expense)
        .where(
            Expense.group_id == group_id,
            Expense.deleted_at.is_(None),  # INV-8
        )
        .order_by(Expense.created_at.desc())
    )
    return list(session.execute(stmt).scalars().all())


def get_expense(
        expense_id: int,
        caller_id: int,
        session: Session,
) -> Expense:
    """
    Returns a single expense including its splits.

    INV-9: caller must be a member of the expense's group (FORBIDDEN, 403).

    Note: Returns the expense even if soft-deleted. The spec does not restrict
    GET on deleted expenses — the deleted_at field is present in the response
    so the client can display the deletion state.
    """
    expense = _get_expense_or_404(expense_id, session)
    _require_member(expense.group_id, caller_id, session)
    return expense


def edit_expense(
        expense_id: int,
        caller_id: int,
        data: dict,
        session: Session,
) -> Expense:
    """
    Partially updates an expense.

    Spec Section 7.2 rules:
      - Only the original payer or group owner may edit (FORBIDDEN, 403).
      - Cannot edit a soft-deleted expense (EXPENSE_DELETED, 422) — INV-8.
      - If amount OR splits are provided, BOTH must be present and INV-1 is
        re-validated atomically before any DB write. (Schema enforces co-presence.)
      - If split_mode changes to 'equal': server recomputes splits from scratch.
      - If split_mode changes to 'custom': client provides new splits; INV-1 re-validated.
      - updated_at is set to NOW() on every successful PATCH.

    Args:
        expense_id: The expense to edit.
        caller_id:  Authenticated user making the edit (from flask.g).
        data:       Validated partial dict from PatchExpenseSchema.

    Returns:
        The updated Expense ORM object.
    """
    expense = _get_expense_or_404(expense_id, session)

    # INV-9: caller must be a member of the group.
    _require_member(expense.group_id, caller_id, session)

    # INV-8: soft-deleted expenses cannot be edited.
    if expense.is_deleted:
        raise AppError(
            ErrorCode.EXPENSE_DELETED,
            f"Expense {expense_id} has been deleted and cannot be edited.",
            422,
        )

    # Authorization: only the original payer or group owner may edit.
    group = _get_group_or_404(expense.group_id, session)
    is_payer = (caller_id == expense.paid_by_user_id)
    is_owner = (caller_id == group.owner_user_id)

    if not (is_payer or is_owner):
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Only the original payer or group owner may edit this expense.",
            403,
        )

    # ── Apply field updates ────────────────────────────────────────────────

    if "description" in data:
        expense.description = data["description"]

    if "category" in data:
        expense.category = data["category"]

    if "paid_by_user_id" in data:
        member_ids = _get_member_ids(expense.group_id, session)
        _validate_payer_is_member(data["paid_by_user_id"], expense.group_id, member_ids)
        expense.paid_by_user_id = data["paid_by_user_id"]

    # ── Split and amount updates ───────────────────────────────────────────
    # The schema guarantees co-presence rules. Here we apply them.

    new_split_mode = data.get("split_mode")   # None if not in PATCH
    new_amount = data.get("amount")           # None if not in PATCH
    new_splits = data.get("splits")           # None if not in PATCH

    # Resolve the effective split mode for this operation.
    effective_split_mode = new_split_mode if new_split_mode is not None else expense.split_mode

    if new_split_mode is not None:
        expense.split_mode = new_split_mode

    if effective_split_mode == SplitMode.EQUAL and (new_amount is not None or new_split_mode == SplitMode.EQUAL):
        # Recompute equal splits from scratch.
        # Trigger: either amount changed, or split_mode changed to 'equal'.
        # The schema ensures splits is None in this case.
        effective_amount = new_amount if new_amount is not None else expense.amount
        if new_amount is not None:
            expense.amount = new_amount

        member_ids = _get_member_ids(expense.group_id, session)
        splits_data = _compute_equal_splits(effective_amount, member_ids, expense.paid_by_user_id)

        _delete_splits(expense, session)
        _create_split_rows(expense, splits_data, session)

    elif new_amount is not None and new_splits is not None:
        # Custom mode with both amount and splits provided — re-validate INV-1.
        member_ids = _get_member_ids(expense.group_id, session)
        _validate_payer_is_member(expense.paid_by_user_id, expense.group_id, member_ids)
        _validate_split_users_are_members(new_splits, expense.group_id, member_ids)
        _validate_split_sum(new_splits, new_amount, expense.group_id)

        expense.amount = new_amount
        _delete_splits(expense, session)
        _create_split_rows(expense, new_splits, session)

    # Spec Section 7.2: updated_at is set on every successful PATCH.
    expense.updated_at = datetime.now(timezone.utc)
    session.flush()
    session.refresh(expense)
    return expense


def delete_expense(
        expense_id: int,
        caller_id: int,
        session: Session,
) -> None:
    """
    Soft-deletes an expense by setting deleted_at = NOW().

    The row stays in the database. Splits are preserved for audit.
    Balance computation excludes it via INV-8.

    Authorization: only the original payer or group owner may delete.
    INV-9: caller must be a group member (FORBIDDEN, 403).

    Raises:
        AppError(EXPENSE_NOT_FOUND, 404) — expense does not exist.
        AppError(FORBIDDEN, 403)         — caller is not payer or owner.
    """
    expense = _get_expense_or_404(expense_id, session)

    # INV-9: caller must be a member.
    _require_member(expense.group_id, caller_id, session)

    # Authorization: only payer or group owner may delete.
    group = _get_group_or_404(expense.group_id, session)
    is_payer = (caller_id == expense.paid_by_user_id)
    is_owner = (caller_id == group.owner_user_id)

    if not (is_payer or is_owner):
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Only the original payer or group owner may delete this expense.",
            403,
        )

    # Idempotent: if already soft-deleted, do nothing (no error on re-delete).
    if not expense.is_deleted:
        expense.deleted_at = datetime.now(timezone.utc)
        session.flush()