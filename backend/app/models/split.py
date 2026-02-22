"""
models/split.py — Split table definition.

Columns and constraints mirror the DB schema in the product spec (Section 6).
No business logic. No imports from services or routes.

Key design points:
  - `amount` uses Numeric(12, 2) — never Float.
  - expense_id is ON DELETE CASCADE — splits are owned by their expense.
    If an expense row is hard-deleted (only possible via direct DB access;
    the API soft-deletes only), splits are removed automatically.
  - user_id is ON DELETE RESTRICT — cannot delete a user who has splits.
  - UNIQUE(expense_id, user_id) prevents the same user appearing twice in
    one expense's splits (also enforced as DUPLICATE_SPLIT_USER at schema layer).

INV-1 (sum(splits.amount) == expense.amount) is enforced in expense_service.py,
not here. The DB constraint would require a deferred trigger; the service check
is simpler and catches the error before the write.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class Split(db.Model):
    __tablename__ = "splits"

    __table_args__ = (
        # Spec: UNIQUE(expense_id, user_id) — a user can only appear once per expense.
        UniqueConstraint("expense_id", "user_id", name="uq_splits_expense_user"),

        # Spec: CHECK(amount > 0) — each split must be a positive amount.
        CheckConstraint("amount > 0", name="ck_splits_amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # ON DELETE CASCADE — splits are destroyed when their expense is destroyed.
    # (The API never hard-deletes expenses, but direct DB cleanup would cascade.)
    expense_id: Mapped[int] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,   # idx_splits_expense (spec Section 6)
    )

    # ON DELETE RESTRICT — cannot delete a user who has split assignments.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # INV-7: NUMERIC(12, 2). Never Float.
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────

    expense: Mapped["Expense"] = relationship(  # noqa: F821
        "Expense",
        back_populates="splits",
    )

    user: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="splits",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Split id={self.id} "
            f"expense_id={self.expense_id} "
            f"user_id={self.user_id} "
            f"amount={self.amount}>"
        )