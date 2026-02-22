"""
models/settlement.py — Settlement table definition.

Columns and constraints mirror the DB schema in the product spec (Section 6).
No business logic. No imports from services or routes.

Key design points:
  - `amount` uses Numeric(12, 2) — never Float.
  - INV-4: CHECK(paid_by_user_id <> paid_to_user_id) is enforced at the DB
    level here AND in settlement_service.py (SELF_SETTLEMENT, 422).
    The DB constraint is the last line of defense.
  - All three FK columns (group_id, paid_by_user_id, paid_to_user_id) are
    ON DELETE RESTRICT — cannot delete a group or user that has settlements.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class Settlement(db.Model):
    __tablename__ = "settlements"

    __table_args__ = (
        # Spec: CHECK(amount > 0)
        CheckConstraint("amount > 0", name="ck_settlements_amount_positive"),

        # INV-4: paid_by_user_id must not equal paid_to_user_id.
        # This is also enforced in settlement_service.py with SELF_SETTLEMENT (422)
        # before the write reaches the DB. The DB constraint is the final guard.
        CheckConstraint(
            "paid_by_user_id <> paid_to_user_id",
            name="ck_settlements_no_self_settlement",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # ON DELETE RESTRICT — cannot delete a group that has settlements.
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,   # idx_settlements_group (spec Section 6)
    )

    # ON DELETE RESTRICT — cannot delete a user who has made settlements.
    paid_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # ON DELETE RESTRICT — cannot delete a user who has received settlements.
    paid_to_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # INV-7: NUMERIC(12, 2). Never Float.
    # INV-3: amount > 0 (CHECK above). Overpayment is valid — it warns but
    # does not block. The schema rejects amounts <= 0 before this is reached.
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ──────────────────────────────────────────────────────

    group: Mapped["Group"] = relationship(  # noqa: F821
        "Group",
        back_populates="settlements",
    )

    payer: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="settlements_made",
        foreign_keys=[paid_by_user_id],
    )

    recipient: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="settlements_received",
        foreign_keys=[paid_to_user_id],
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Settlement id={self.id} "
            f"group_id={self.group_id} "
            f"from={self.paid_by_user_id} "
            f"to={self.paid_to_user_id} "
            f"amount={self.amount}>"
        )