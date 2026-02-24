"""
services/balance_service.py — Balance computation and debt simplification.

This file is the SINGLE SOURCE OF TRUTH for how balances are computed.
The canonical formula must not be reimplemented elsewhere in the codebase.
Any change to how balances work must be made here; all other behaviour
follows from it. (ARCHITECTURE.md Section 6)

Layer rules (GUIDE Rule 3):
  - No Flask imports. No current_app, request, g, or HTTP knowledge.
  - Receives group_id (int) and session (SQLAlchemy Session) as arguments.
  - Returns plain Python dicts and lists.
  - Fully unit-testable without a Flask app or HTTP context.

INV-8 enforcement:
  - get_active_expenses() ALWAYS filters WHERE deleted_at IS NULL.
  - All functions that read expense amounts use get_active_expenses().
  - Direct queries on the Expense model without this filter are FORBIDDEN
    in any balance-related context. (GUIDE Rule 8)

INV-2 guarantee:
  - compute_balances() is mathematically guaranteed to produce sum == 0
    when INV-1 holds for all active expenses. The route asserts this
    before responding; a non-zero sum surfaces as a 500.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import AppError, ErrorCode
from backend.app.models.expense import Category, Expense
from backend.app.models.membership import Membership
from backend.app.models.settlement import Settlement
from backend.app.models.split import Split
from backend.app.models.user import User


# ── Data access helpers ────────────────────────────────────────────────────
# These are the ONLY sanctioned ways to query expense/split data for
# balance purposes. They exist to enforce INV-8 at the query level.

def get_active_expenses(
        group_id: int,
        session: Session,
        category: Category | None = None,
) -> list[Expense]:
    """
    Returns expenses for a group WHERE deleted_at IS NULL (INV-8).

    Args:
        category: Optional filter. When provided, only expenses of that
                  category are included. This is used for the informational
                  category-scoped balance view (spec Section 8.4).
                  IMPORTANT: category filtering is informational only —
                  balance_sum will NOT be zero for a filtered result because
                  settlements are not category-scoped.
    """
    stmt = (
        select(Expense)
        .where(
            Expense.group_id == group_id,
            Expense.deleted_at.is_(None),  # INV-8: exclude soft-deleted
        )
    )
    if category is not None:
        stmt = stmt.where(Expense.category == category)

    return list(session.execute(stmt).scalars().all())


def get_splits_for_active_expenses(
        group_id: int,
        session: Session,
        category: Category | None = None,
) -> list[Split]:
    """
    Returns splits belonging to active (non-deleted) expenses in a group.

    Joins Split → Expense to enforce the INV-8 filter. Does not query
    Expense directly without the deleted_at filter.
    """
    stmt = (
        select(Split)
        .join(Expense, Split.expense_id == Expense.id)
        .where(
            Expense.group_id == group_id,
            Expense.deleted_at.is_(None),  # INV-8
        )
    )
    if category is not None:
        stmt = stmt.where(Expense.category == category)

    return list(session.execute(stmt).scalars().all())


def get_settlements(group_id: int, session: Session) -> list[Settlement]:
    """Returns all settlements for a group. Settlements have no soft-delete."""
    stmt = select(Settlement).where(Settlement.group_id == group_id)
    return list(session.execute(stmt).scalars().all())


def get_member_ids(group_id: int, session: Session) -> list[int]:
    """Returns the user_ids of all current members of a group."""
    stmt = select(Membership.user_id).where(Membership.group_id == group_id)
    return list(session.execute(stmt).scalars().all())


def get_members(group_id: int, session: Session) -> list[User]:
    """Returns full User objects for all current group members."""
    stmt = (
        select(User)
        .join(Membership, User.id == Membership.user_id)
        .where(Membership.group_id == group_id)
    )
    return list(session.execute(stmt).scalars().all())


# ── Core algorithms ────────────────────────────────────────────────────────

def compute_balances(
        group_id: int,
        session: Session,
        category: Category | None = None,
) -> dict[int, Decimal]:
    """
    Canonical balance computation for a group. (ARCHITECTURE.md Section 6)

    Returns {user_id: net_balance} for every current member.

    Algorithm:
      1. Credit each payer for the full expense amount they fronted.
      2. Debit each participant for their split amount.
      3. Net all settlements (payer gains credit, recipient loses credit).
      4. Ensure every member appears even if their balance is exactly zero.

    INV-8: Only active (deleted_at IS NULL) expenses are included.
           This is enforced through get_active_expenses() and
           get_splits_for_active_expenses() — never bypass these helpers.

    INV-2: sum(return_value.values()) == Decimal("0.00") for a full
           (non-category-filtered) computation. This is a mathematical
           consequence of INV-1 and is asserted by the caller (the route
           or the test) before using the result.

    Category filter note:
      When category is provided, settlements are NOT filtered — they are
      cross-category. As a result, sum(balances) will NOT be zero for
      a category-filtered result. The caller must NOT assert INV-2 on
      category-filtered results.
    """
    balances: dict[int, Decimal] = defaultdict(Decimal)

    # Step 1: Credit payer for the full expense amount they fronted.
    for expense in get_active_expenses(group_id, session, category):
        balances[expense.paid_by_user_id] += expense.amount

    # Step 2: Debit each participant for their split portion.
    for split in get_splits_for_active_expenses(group_id, session, category):
        balances[split.user_id] -= split.amount

    # Step 3: Net settlements. Only included when no category filter is active,
    # because settlements are cross-category and would distort the filtered view.
    if category is None:
        for settlement in get_settlements(group_id, session):
            balances[settlement.paid_by_user_id] += settlement.amount
            balances[settlement.paid_to_user_id] -= settlement.amount

    # Step 4: Ensure every member appears, even if their net balance is zero.
    for member_id in get_member_ids(group_id, session):
        balances.setdefault(member_id, Decimal("0.00"))

    return dict(balances)


def simplify_debts(balances: dict[int, Decimal]) -> list[dict]:
    """
    Greedy minimum cash flow debt simplification.
    (ARCHITECTURE.md Section 6 — AI-generated, test-verified)

    Repeatedly matches the largest debtor with the largest creditor until
    all balances reach zero. For N members, produces at most N-1 transactions.

    Args:
        balances: {user_id: net_balance} from compute_balances().
                  MUST satisfy sum(balances.values()) == 0 (INV-2).
                  Passing a category-filtered result violates this contract.

    Returns:
        List of {"from_user_id": int, "to_user_id": int, "amount": Decimal}
        An empty list means all balances are already zero.
    """
    # Build mutable sorted lists: largest creditor first, largest debtor first.
    creditors = sorted(
        [(uid, amt) for uid, amt in balances.items() if amt > 0],
        key=lambda x: x[1],
        reverse=True,
    )
    debtors = sorted(
        [(uid, -amt) for uid, amt in balances.items() if amt < 0],
        key=lambda x: x[1],
        reverse=True,
    )

    transactions: list[dict] = []
    i = j = 0

    while i < len(creditors) and j < len(debtors):
        cid, credit = creditors[i]
        did, debt = debtors[j]

        transfer = min(credit, debt)
        transactions.append({
            "from_user_id": did,
            "to_user_id": cid,
            "amount": transfer,
        })

        creditors[i] = (cid, credit - transfer)
        debtors[j] = (did, debt - transfer)

        if creditors[i][1] == Decimal("0"):
            i += 1
        if debtors[j][1] == Decimal("0"):
            j += 1

    return transactions


def get_balance_response(
        group_id: int,
        caller_id: int,
        session: Session,
        category: Category | None = None,
) -> dict:
    """
    Builds the full balance response payload for GET /groups/:id/balances.

    Enforces INV-9 (caller must be a group member), computes balances,
    enriches with member names, computes simplified debts, and asserts
    INV-2 (balance_sum == 0) for non-filtered responses.

    Raises:
        AppError(GROUP_NOT_FOUND, 404)  -- group does not exist.
        AppError(FORBIDDEN, 403)        -- caller not a group member (INV-9).
        AppError(INTERNAL_ERROR, 500)   -- INV-2 violated on unfiltered computation.
    """
    # Verify group exists.
    from backend.app.models.group import Group  # local import to avoid circular dep
    group = session.get(Group, group_id)
    if group is None:
        raise AppError(
            ErrorCode.GROUP_NOT_FOUND,
            f"Group {group_id} does not exist.",
            404,
        )

    # INV-9: caller must be a member of the group.
    caller_is_member = caller_id in get_member_ids(group_id, session)
    if not caller_is_member:
        raise AppError(
            ErrorCode.FORBIDDEN,
            f"You are not a member of group {group_id}.",
            403,
        )

    balances = compute_balances(group_id, session, category)
    members = get_members(group_id, session)
    member_map = {m.id: m.username for m in members}

    balance_list = [
        {
            "user_id": uid,
            "name": member_map.get(uid, f"user_{uid}"),
            "balance": str(bal),
        }
        for uid, bal in balances.items()
    ]

    # INV-2 assertion: sum of all balances MUST be zero for the full computation.
    # Category-filtered results are explicitly excluded from this check because
    # they intentionally omit cross-category settlements.
    if category is None:
        balance_sum = sum(balances.values(), Decimal("0.00"))
        if balance_sum != Decimal("0.00"):
            # This is a 500 — it means source data is corrupt.
            # The error handler will log the full context.
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"Balance integrity check failed: sum was {balance_sum} (expected 0.00). "
                f"Group {group_id} has inconsistent financial data.",
                500,
            )

        simplified = simplify_debts(balances)
        simplified_debts = [
            {
                "from_user_id": t["from_user_id"],
                "from_name": member_map.get(t["from_user_id"], f"user_{t['from_user_id']}"),
                "to_user_id": t["to_user_id"],
                "to_name": member_map.get(t["to_user_id"], f"user_{t['to_user_id']}"),
                "amount": str(t["amount"]),
            }
            for t in simplified
        ]
    else:
        # For category-filtered view, simplified debts are not meaningful.
        simplified_debts = []

    final_sum = sum(balances.values(), Decimal("0.00"))

    return {
        "group_id": group_id,
        "balances": balance_list,
        "simplified_debts": simplified_debts,
        "balance_sum": str(final_sum),
    }