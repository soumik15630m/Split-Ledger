"""
models/refresh_token.py — RefreshToken table definition.

Columns and constraints mirror the DB schema in the product spec (Section 6).
No business logic. No imports from services or routes.

FK policy: user_id ON DELETE CASCADE — token is owned by the user;
both are deleted together. (See spec Section 6 ON DELETE Policy table.)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class RefreshToken(db.Model):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)

    # ON DELETE CASCADE — token is destroyed when its owning user is deleted.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,   # idx_refresh_tokens_user (spec Section 6)
    )

    # Spec: VARCHAR(255) NOT NULL UNIQUE
    # Stores the SHA-256 hex digest of the raw refresh token, never the token itself.
    # auth_service._hash_token() computes hashlib.sha256(raw_token).hexdigest()
    # before any DB read/write. A compromised DB does not expose valid raw tokens.
    # ARCHITECTURE.md Section 7: "stored as a SHA-256 hash in the database, never the raw value."
    token_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Spec: BOOLEAN NOT NULL DEFAULT FALSE
    # Set to TRUE on POST /auth/logout. The access token expires naturally.
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ──────────────────────────────────────────────────────

    user: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="refresh_tokens",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<RefreshToken id={self.id} "
            f"user_id={self.user_id} "
            f"revoked={self.revoked}>"
        )