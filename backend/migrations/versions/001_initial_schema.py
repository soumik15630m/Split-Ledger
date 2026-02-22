"""Initial schema — all tables, enums, constraints, and indexes.

Revision: 001_initial_schema
Created:  2026-02-21

This migration creates the complete SplitLedger v1 database schema as
defined in the product specification (Section 6).

GUIDE Rule 7 — Append-only:
  This file must NEVER be edited after it has been applied to any database.
  If a schema change is required, create a NEW migration file.
  Editing an applied migration creates a mismatch between what actually ran
  and what the file says.

Creation order:
  1. PostgreSQL enum types (must exist before tables that reference them)
  2. Tables in FK dependency order (users → groups → memberships → expenses
     → splits → settlements, refresh_tokens)
  3. Indexes (including the partial index idx_expenses_active)

ON DELETE policies (spec Section 6):
  refresh_tokens.user_id    → CASCADE   (token owned by user)
  memberships.*             → RESTRICT  (cannot delete user/group with members)
  expenses.*                → RESTRICT  (cannot delete group/user with expenses)
  splits.expense_id         → CASCADE   (splits owned by expense)
  splits.user_id            → RESTRICT  (cannot delete user with splits)
  settlements.*             → RESTRICT  (cannot delete group/user with settlements)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ── Alembic revision identifiers ──────────────────────────────────────────
revision: str = "001_initial_schema"
down_revision: str | None = None      # first migration — no parent
branch_labels: tuple | None = None
depends_on: tuple | None = None


def upgrade() -> None:
    """
    Apply the full initial schema.

    Enum types are created via op.execute() rather than SQLAlchemy's
    Enum(create_type=True) because:
      (a) Alembic autogenerate does not reliably detect type creation/deletion
          for PostgreSQL custom types.
      (b) Using op.execute() makes the exact SQL explicit and reviewable.
      (c) Models use Enum(..., create_type=False) — the type is expected to
          already exist in the DB before the ORM maps to it.
    """

    # ── Step 1: PostgreSQL enum types ─────────────────────────────────────
    # Must be created before the expenses table which references them.

    op.execute("""
        CREATE TYPE split_mode_enum AS ENUM ('equal', 'custom')
    """)

    op.execute("""
        CREATE TYPE category_enum AS ENUM (
            'food',
            'transport',
            'accommodation',
            'entertainment',
            'utilities',
            'other'
        )
    """)

    # ── Step 2: users ──────────────────────────────────────────────────────
    # Spec: username VARCHAR(50) NOT NULL UNIQUE CHECK(LENGTH(TRIM(username))>0)
    # Spec: email    VARCHAR(255) NOT NULL UNIQUE CHECK(email LIKE '%@%')

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "LENGTH(TRIM(username)) > 0",
            name="ck_users_username_nonempty",
        ),
        sa.CheckConstraint(
            "email LIKE '%@%'",
            name="ck_users_email_format",
        ),
    )

    # ── Step 3: refresh_tokens ─────────────────────────────────────────────
    # FK: user_id ON DELETE CASCADE — token is destroyed when user is deleted.

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_refresh_tokens_user"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_hash"),
    )

    # ── Step 4: groups ─────────────────────────────────────────────────────
    # FK: owner_user_id ON DELETE RESTRICT

    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_groups_owner"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_groups"),
        sa.CheckConstraint(
            "LENGTH(TRIM(name)) > 0",
            name="ck_groups_name_nonempty",
        ),
    )

    # ── Step 5: memberships ────────────────────────────────────────────────
    # Both FKs ON DELETE RESTRICT. UNIQUE(user_id, group_id).

    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_memberships_user"),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("groups.id", ondelete="RESTRICT", name="fk_memberships_group"),
            nullable=False,
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.UniqueConstraint("user_id", "group_id", name="uq_memberships_user_group"),
    )

    # ── Step 6: expenses ───────────────────────────────────────────────────
    # Uses split_mode_enum and category_enum (created in Step 1).
    # deleted_at IS NULL = active; non-null = soft-deleted (INV-8).
    # Both FKs ON DELETE RESTRICT.

    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("groups.id", ondelete="RESTRICT", name="fk_expenses_group"),
            nullable=False,
        ),
        sa.Column(
            "paid_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_expenses_payer"),
            nullable=False,
        ),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "split_mode",
            postgresql.ENUM("equal", "custom", name="split_mode_enum", create_type=False),
            nullable=False,
            server_default="custom",
        ),
        sa.Column(
            "category",
            postgresql.ENUM(
                "food", "transport", "accommodation",
                "entertainment", "utilities", "other",
                name="category_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="other",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_expenses"),
        sa.CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        sa.CheckConstraint(
            "LENGTH(TRIM(description)) > 0",
            name="ck_expenses_description_nonempty",
        ),
    )

    # ── Step 7: splits ─────────────────────────────────────────────────────
    # expense_id ON DELETE CASCADE — splits owned by their expense.
    # user_id ON DELETE RESTRICT.
    # UNIQUE(expense_id, user_id).

    op.create_table(
        "splits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "expense_id",
            sa.Integer(),
            sa.ForeignKey("expenses.id", ondelete="CASCADE", name="fk_splits_expense"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_splits_user"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_splits"),
        sa.UniqueConstraint("expense_id", "user_id", name="uq_splits_expense_user"),
        sa.CheckConstraint("amount > 0", name="ck_splits_amount_positive"),
    )

    # ── Step 8: settlements ────────────────────────────────────────────────
    # All three FKs ON DELETE RESTRICT.
    # CHECK(paid_by_user_id <> paid_to_user_id) — INV-4 at DB level.

    op.create_table(
        "settlements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("groups.id", ondelete="RESTRICT", name="fk_settlements_group"),
            nullable=False,
        ),
        sa.Column(
            "paid_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_settlements_payer"),
            nullable=False,
        ),
        sa.Column(
            "paid_to_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT", name="fk_settlements_recipient"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_settlements"),
        sa.CheckConstraint("amount > 0", name="ck_settlements_amount_positive"),
        # INV-4: self-settlement is forbidden at the DB level (also enforced in service).
        sa.CheckConstraint(
            "paid_by_user_id <> paid_to_user_id",
            name="ck_settlements_no_self_settlement",
        ),
    )

    # ── Step 9: Indexes ────────────────────────────────────────────────────
    # All indexes from spec Section 6. Names match the spec exactly.

    # refresh_tokens: fast lookup by user for cascade/revocation queries.
    op.create_index(
        "idx_refresh_tokens_user",
        "refresh_tokens",
        ["user_id"],
    )

    # memberships: fast lookup by group (list members) and by user (list groups).
    op.create_index(
        "idx_memberships_group",
        "memberships",
        ["group_id"],
    )
    op.create_index(
        "idx_memberships_user",
        "memberships",
        ["user_id"],
    )

    # expenses: general group scan + active-only partial index.
    op.create_index(
        "idx_expenses_group",
        "expenses",
        ["group_id"],
    )
    # Partial index: only indexes active (non-deleted) expense rows.
    # The balance service always queries WHERE deleted_at IS NULL — this index
    # makes those queries efficient without including deleted rows.
    op.create_index(
        "idx_expenses_active",
        "expenses",
        ["group_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # splits: fast lookup by expense (cascade checks, balance queries).
    op.create_index(
        "idx_splits_expense",
        "splits",
        ["expense_id"],
    )

    # settlements: fast lookup by group (balance computation, list).
    op.create_index(
        "idx_settlements_group",
        "settlements",
        ["group_id"],
    )


def downgrade() -> None:
    """
    Drop all objects created in upgrade(), in reverse dependency order.

    This is provided for completeness and local development reset.
    In production, downgrade() should never be run — GUIDE Rule 7 states
    that migrations are append-only and corrective migrations are preferred
    over rollbacks.
    """

    # Drop indexes first (no dependency order needed for indexes).
    op.drop_index("idx_settlements_group",   table_name="settlements")
    op.drop_index("idx_splits_expense",      table_name="splits")
    op.drop_index("idx_expenses_active",     table_name="expenses")
    op.drop_index("idx_expenses_group",      table_name="expenses")
    op.drop_index("idx_memberships_user",    table_name="memberships")
    op.drop_index("idx_memberships_group",   table_name="memberships")
    op.drop_index("idx_refresh_tokens_user", table_name="refresh_tokens")

    # Drop tables in reverse FK dependency order.
    op.drop_table("settlements")
    op.drop_table("splits")
    op.drop_table("expenses")
    op.drop_table("memberships")
    op.drop_table("groups")
    op.drop_table("refresh_tokens")
    op.drop_table("users")

    # Drop enum types last (tables that reference them must be gone first).
    op.execute("DROP TYPE IF EXISTS category_enum")
    op.execute("DROP TYPE IF EXISTS split_mode_enum")
