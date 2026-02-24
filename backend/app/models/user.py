"""
models/user.py — User table definition.

Columns and constraints mirror the DB schema in the product spec (Section 6).
No business logic. No imports from services or routes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.extensions import db


class User(db.Model):
    __tablename__ = "users"

    __table_args__ = (
        # Spec: CHECK(LENGTH(TRIM(username)) > 0) — also enforced by marshmallow schema.
        CheckConstraint(
            "LENGTH(TRIM(username)) > 0",
            name="ck_users_username_nonempty",
        ),
        # Spec: CHECK(email LIKE '%@%') — also enforced by marshmallow Email field.
        CheckConstraint(
            "email LIKE '%@%'",
            name="ck_users_email_format",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Spec: VARCHAR(50) NOT NULL UNIQUE CHECK(LENGTH(TRIM(username)) > 0)
    # The CHECK is enforced at the DB level via __table_args__ above;
    # marshmallow schema enforces the same rule at the API layer.
    username: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
    )

    # Spec: VARCHAR(255) NOT NULL UNIQUE CHECK(email LIKE '%@%')
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ──────────────────────────────────────────────────────
    # Read-only navigation — no logic here.

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(  # noqa: F821
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    memberships: Mapped[list["Membership"]] = relationship(  # noqa: F821
        "Membership",
        back_populates="user",
    )

    # Expenses this user paid for (paid_by_user_id FK)
    expenses_paid: Mapped[list["Expense"]] = relationship(  # noqa: F821
        "Expense",
        back_populates="payer",
        foreign_keys="[Expense.paid_by_user_id]",
    )

    # Splits assigned to this user
    splits: Mapped[list["Split"]] = relationship(  # noqa: F821
        "Split",
        back_populates="user",
    )

    # Settlements where this user is the payer
    settlements_made: Mapped[list["Settlement"]] = relationship(  # noqa: F821
        "Settlement",
        back_populates="payer",
        foreign_keys="[Settlement.paid_by_user_id]",
    )

    # Settlements where this user is the recipient
    settlements_received: Mapped[list["Settlement"]] = relationship(  # noqa: F821
        "Settlement",
        back_populates="recipient",
        foreign_keys="[Settlement.paid_to_user_id]",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} username={self.username!r}>"