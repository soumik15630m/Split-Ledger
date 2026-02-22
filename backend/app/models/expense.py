"""
models/expense.py — Expense table definition.

Columns and constraints mirror the DB schema in the product spec (Section 6).
No business logic. No imports from services or routes.

Key design points:
  - `deleted_at` is NULL for active expenses, non-null for soft-deleted ones (INV-8).
  - `amount` uses Numeric(12, 2) — never Float.
  - Both FK columns are ON DELETE RESTRICT.
  - A partial index on (group_id) WHERE deleted_at IS NULL is defined here;
    it is also created via Alembic migration (models are the canonical definition).
  - SplitMode and Category are Python enums so they can be imported and used
    throughout the service layer without repeating string literals.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


# ── Enum Definitions ───────────────────────────────────────────────────────
# Defined here so they can be imported by schemas and services without
# pulling in the full model. Do not duplicate these as plain string constants
# anywhere else in the codebase.

class SplitMode(str, enum.Enum):
    """Spec: split_mode_enum AS ENUM ('equal', 'custom')"""
    EQUAL  = "equal"
    CUSTOM = "custom"


class Category(str, enum.Enum):
    """Spec: category_enum AS ENUM (...)"""
    FOOD            = "food"
    TRANSPORT       = "transport"
    ACCOMMODATION   = "accommodation"
    ENTERTAINMENT   = "entertainment"
    UTILITIES       = "utilities"
    OTHER           = "other"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Ensure SQLAlchemy stores enum values (e.g., 'custom'), not names ('CUSTOM')."""
    return [member.value for member in enum_cls]


# ── Model ──────────────────────────────────────────────────────────────────

class Expense(db.Model):
    __tablename__ = "expenses"

    __table_args__ = (
        # Spec: CHECK(amount > 0) — also enforced by marshmallow schema.
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),

        # Spec: CHECK(LENGTH(TRIM(description)) > 0) — also enforced by marshmallow schema.
        # Both layers are intentional (defence-in-depth); the schema is the primary gate.
        CheckConstraint(
            "LENGTH(TRIM(description)) > 0",
            name="ck_expenses_description_nonempty",
        ),

        # Spec: partial index for active-only expense queries (idx_expenses_active).
        # The balance service always queries through get_active_expenses(), which
        # filters deleted_at IS NULL; this index makes those queries efficient.
        Index(
            "idx_expenses_active",
            "group_id",
            postgresql_where="deleted_at IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # ON DELETE RESTRICT — cannot delete a group that has expenses.
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,   # idx_expenses_group (spec Section 6)
    )

    # ON DELETE RESTRICT — cannot delete a user who has paid expenses.
    paid_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Spec: VARCHAR(255) NOT NULL CHECK(LENGTH(TRIM(description)) > 0)
    description: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # INV-7: NUMERIC(12, 2). Never Float. Input with >2 decimal places is
    # rejected by the schema (INVALID_AMOUNT_PRECISION), not rounded.
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    # Spec: split_mode_enum NOT NULL DEFAULT 'custom'
    split_mode: Mapped[SplitMode] = mapped_column(
        Enum(
            SplitMode,
            name="split_mode_enum",
            create_type=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=SplitMode.CUSTOM,
        server_default=SplitMode.CUSTOM.value,
    )

    # Spec: category_enum NOT NULL DEFAULT 'other'
    category: Mapped[Category] = mapped_column(
        Enum(
            Category,
            name="category_enum",
            create_type=False,
            values_callable=_enum_values,
        ),
        nullable=False,
        default=Category.OTHER,
        server_default=Category.OTHER.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Spec: updated_at TIMESTAMPTZ — nullable; set on every successful PATCH.
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Spec: deleted_at TIMESTAMPTZ — NULL = active; NOT NULL = soft-deleted (INV-8).
    # Never hard-delete expense rows via the API.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Relationships ──────────────────────────────────────────────────────

    group: Mapped["Group"] = relationship(  # noqa: F821
        "Group",
        back_populates="expenses",
    )

    payer: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="expenses_paid",
        foreign_keys=[paid_by_user_id],
    )

    # ON DELETE CASCADE — splits are owned by their expense.
    splits: Mapped[list["Split"]] = relationship(  # noqa: F821
        "Split",
        back_populates="expense",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # ── Convenience property ───────────────────────────────────────────────
    # Read-only; does NOT contain logic — just inspects a column value.
    @property
    def is_deleted(self) -> bool:
        """True if this expense has been soft-deleted."""
        return self.deleted_at is not None

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Expense id={self.id} "
            f"group_id={self.group_id} "
            f"amount={self.amount} "
            f"deleted={self.is_deleted}>"
        )
