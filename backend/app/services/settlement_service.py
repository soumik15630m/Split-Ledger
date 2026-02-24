"""
services/settlement_service.py — Settlement business logic.

Invariants enforced here (ARCHITECTURE.md Section 4):
  INV-3  OVERPAYMENT warning  — overpayment is valid; returns warning but records
  INV-4  SELF_SETTLEMENT (422)— paid_by_user_id must not equal paid_to_user_id
  INV-5  PAYER_NOT_MEMBER (422) — paid_by must be a group member
         RECIPIENT_NOT_MEMBER (422) — paid_to must be a group member
  INV-9  FORBIDDEN (403)     — caller must be a group member

Notes on INV-3 (overpayment):
  If the settlement amount exceeds the current debt between the two parties,
  the request is still recorded (pre-payment is valid business logic) but a
  warning is returned in the response alongside the 201. The warning uses
  WarningCode.OVERPAYMENT. The route wraps this in the standard warning
  envelope: {"data": {...}, "warnings": [{"code": "OVERPAYMENT", ...}]}.

Notes on INV-4 (self-settlement):
  The schema cannot check this because paid_by_user_id comes from flask.g
  (auth context), not the request body. The service receives both user IDs
  as plain integers and performs the check here. The DB also has a CHECK
  constraint as the final defence layer.

Layer rules (GUIDE Rule 3):
  - No Flask imports. Pure Python with a SQLAlchemy session parameter.
  - Commits are the route's responsibility — only flush here.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.errors import AppError, ErrorCode, WarningCode
from backend.app.models.expense import Expense
from backend.app.models.membership import Membership
from backend.app.models.settlement import Settlement
from backend.app.models.split import Split


# ── Private helpers ────────────────────────────────────────────────────────

def _require_member(group_id: int, user_id: int, session: Session) -> None:
    """
    Raises FORBIDDEN (403) if user_id is not a member of group_id. INV-9.
    Uses second-person phrasing consistent with all other _require_member
    helpers in the codebase (group_service.py, balance_service.py).
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


def _compute_bilateral_debt(
        group_id: int,
        debtor_id: int,
        creditor_id: int,
        session: Session,
) -> Decimal:
    """
    Computes bilateral outstanding debt from debtor_id -> creditor_id.

    This is intentionally pair-specific (between exactly two users), which is
    what the OVERPAYMENT warning contract refers to.

    Formula:
      debt = amounts the debtor owes the creditor from active expenses
           - amounts the creditor owes the debtor from active expenses
           - settlements already paid debtor->creditor
           + settlements already paid creditor->debtor

    Returns:
      Positive Decimal debt amount if debtor owes creditor, else Decimal("0.00").
    """
    # Expense-side obligations (active expenses only — INV-8).
    debtor_owes_creditor_from_expenses = session.execute(
        select(func.coalesce(func.sum(Split.amount), 0))
        .select_from(Split)
        .join(Expense, Split.expense_id == Expense.id)
        .where(
            Expense.group_id == group_id,
            Expense.deleted_at.is_(None),
            Split.user_id == debtor_id,
            Expense.paid_by_user_id == creditor_id,
        )
    ).scalar_one()

    creditor_owes_debtor_from_expenses = session.execute(
        select(func.coalesce(func.sum(Split.amount), 0))
        .select_from(Split)
        .join(Expense, Split.expense_id == Expense.id)
        .where(
            Expense.group_id == group_id,
            Expense.deleted_at.is_(None),
            Split.user_id == creditor_id,
            Expense.paid_by_user_id == debtor_id,
        )
    ).scalar_one()

    # Settlement-side offsets between these two users.
    debtor_paid_creditor = session.execute(
        select(func.coalesce(func.sum(Settlement.amount), 0))
        .where(
            Settlement.group_id == group_id,
            Settlement.paid_by_user_id == debtor_id,
            Settlement.paid_to_user_id == creditor_id,
        )
    ).scalar_one()

    creditor_paid_debtor = session.execute(
        select(func.coalesce(func.sum(Settlement.amount), 0))
        .where(
            Settlement.group_id == group_id,
            Settlement.paid_by_user_id == creditor_id,
            Settlement.paid_to_user_id == debtor_id,
        )
    ).scalar_one()

    net_debt = (
        debtor_owes_creditor_from_expenses
        - creditor_owes_debtor_from_expenses
        - debtor_paid_creditor
        + creditor_paid_debtor
    )

    if net_debt <= Decimal("0.00"):
        return Decimal("0.00")

    return net_debt


# ── Public service functions ───────────────────────────────────────────────

def create_settlement(
        group_id: int,
        paid_by_id: int,
        data: dict,
        session: Session,
) -> tuple[Settlement, list[dict]]:
    """
    Records a settlement payment from paid_by_id to paid_to_user_id.

    Args:
        group_id:   The group this settlement belongs to.
        paid_by_id: The authenticated user making the payment (from flask.g).
        data:       Validated dict from CreateSettlementSchema.
                    Keys: paid_to_user_id (int), amount (Decimal).

    Enforces:
      INV-9: paid_by_id must be a group member (FORBIDDEN, 403)
      INV-4: paid_by_id != paid_to_user_id (SELF_SETTLEMENT, 422)
      INV-5: paid_by_id membership already checked by INV-9 guard above
             paid_to must also be a group member (RECIPIENT_NOT_MEMBER, 422)
      INV-3: overpayment is allowed — returns warning, does not block (201)

    Returns:
        (Settlement, warnings) where warnings is a list of warning dicts.
        An empty warnings list means no warnings.
        Example warning: {"code": "OVERPAYMENT", "message": "..."}
    """
    from backend.app.models.group import Group  # local import to avoid circular dep

    group = session.get(Group, group_id)
    if group is None:
        raise AppError(
            ErrorCode.GROUP_NOT_FOUND,
            f"Group {group_id} does not exist.",
            404,
        )

    # INV-9: the caller (paid_by_id) must be a group member.
    _require_member(group_id, paid_by_id, session)

    paid_to_user_id: int = data["paid_to_user_id"]
    amount: Decimal = data["amount"]

    # INV-4: self-settlement is forbidden.
    # This check MUST live in the service because paid_by_id comes from
    # flask.g (auth context) and is unavailable to the schema layer.
    if paid_by_id == paid_to_user_id:
        raise AppError(
            ErrorCode.SELF_SETTLEMENT,
            "A settlement cannot be made to yourself.",
            422,
            field="paid_to_user_id",
        )

    # Recipient must also be a group member.
    recipient_membership = session.execute(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == paid_to_user_id,
            )
    ).scalar_one_or_none()

    if recipient_membership is None:
        raise AppError(
            ErrorCode.RECIPIENT_NOT_MEMBER,
            f"User {paid_to_user_id} is not a member of group {group_id}.",
            422,
            field="paid_to_user_id",
        )

    # INV-3: check for overpayment and build warning if applicable.
    # The settlement is still recorded — pre-payment is valid business logic.
    warnings: list[dict] = []
    current_debt = _compute_bilateral_debt(group_id, paid_by_id, paid_to_user_id, session)

    if amount > current_debt:
        warnings.append({
            "code": WarningCode.OVERPAYMENT,
            "message": (
                f"Settlement of {amount} exceeds current outstanding debt of "
                f"{current_debt} from user {paid_by_id} to user {paid_to_user_id}. "
                f"Recording anyway — pre-payment is valid."
            ),
        })

    settlement = Settlement(
        group_id=group_id,
        paid_by_user_id=paid_by_id,
        paid_to_user_id=paid_to_user_id,
        amount=amount,
    )
    session.add(settlement)
    session.flush()

    return settlement, warnings


def list_settlements(
        group_id: int,
        caller_id: int,
        session: Session,
) -> list[Settlement]:
    """
    Returns all settlements for a group, ordered by creation date (newest first).

    INV-9: caller must be a group member (FORBIDDEN, 403).
    """
    from backend.app.models.group import Group  # local import to avoid circular dep

    group = session.get(Group, group_id)
    if group is None:
        raise AppError(
            ErrorCode.GROUP_NOT_FOUND,
            f"Group {group_id} does not exist.",
            404,
        )

    _require_member(group_id, caller_id, session)

    stmt = (
        select(Settlement)
        .where(Settlement.group_id == group_id)
        .order_by(Settlement.created_at.desc())
    )
    return list(session.execute(stmt).scalars().all())
