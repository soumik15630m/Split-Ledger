"""
models/membership.py — Membership junction table definition.

Columns and constraints mirror the DB schema in the product spec (Section 6).
No business logic. No imports from services or routes.

FK policy: user_id and group_id both ON DELETE RESTRICT — neither a user nor
a group can be deleted while active memberships exist.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.extensions import db


class Membership(db.Model):
    __tablename__ = "memberships"

    __table_args__ = (
        # Spec: UNIQUE(user_id, group_id) — a user can only belong to a group once.
        UniqueConstraint("user_id", "group_id", name="uq_memberships_user_group"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # ON DELETE RESTRICT — cannot delete a user who has memberships.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,   # idx_memberships_user (spec Section 6)
    )

    # ON DELETE RESTRICT — cannot delete a group that has members.
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,   # idx_memberships_group (spec Section 6)
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ──────────────────────────────────────────────────────

    user: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="memberships",
    )

    group: Mapped["Group"] = relationship(  # noqa: F821
        "Group",
        back_populates="memberships",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Membership id={self.id} "
            f"user_id={self.user_id} "
            f"group_id={self.group_id}>"
        )