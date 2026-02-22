"""
models/group.py — Group table definition.

Columns and constraints mirror the DB schema in the product spec (Section 6).
No business logic. No imports from services or routes.

FK policy: owner_user_id ON DELETE RESTRICT — a user who owns a group
cannot be deleted until group ownership is transferred or the group is removed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class Group(db.Model):
    # 'groups' is a reserved word in some SQL dialects but is valid in
    # PostgreSQL as a quoted identifier; SQLAlchemy handles quoting.
    __tablename__ = "groups"

    __table_args__ = (
        # Spec: CHECK(LENGTH(TRIM(name)) > 0) — also enforced by marshmallow schema.
        # Both layers are intentional (defence-in-depth); the schema is the primary gate.
        CheckConstraint(
            "LENGTH(TRIM(name)) > 0",
            name="ck_groups_name_nonempty",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Spec: VARCHAR(100) NOT NULL CHECK(LENGTH(TRIM(name)) > 0)
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # ON DELETE RESTRICT — cannot delete a user who owns a group.
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ──────────────────────────────────────────────────────

    owner: Mapped["User"] = relationship(  # noqa: F821
        "User",
        foreign_keys=[owner_user_id],
    )

    memberships: Mapped[list["Membership"]] = relationship(  # noqa: F821
        "Membership",
        back_populates="group",
    )

    expenses: Mapped[list["Expense"]] = relationship(  # noqa: F821
        "Expense",
        back_populates="group",
    )

    settlements: Mapped[list["Settlement"]] = relationship(  # noqa: F821
        "Settlement",
        back_populates="group",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Group id={self.id} name={self.name!r}>"