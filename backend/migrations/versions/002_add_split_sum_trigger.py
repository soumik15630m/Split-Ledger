"""Add split sum integrity trigger (INV-1 DB enforcement layer).

Revision: 002_add_split_sum_trigger
Created:  2026-02-21

ARCHITECTURE.md Section 4 — INV-1 Enforcement:
  The invariants table specifies "Service layer + DB trigger" for INV-1.
  This migration creates the DB trigger that is the fourth and final
  enforcement layer for sum(splits.amount) == expense.amount.

Why a trigger and not a CHECK constraint:
  Standard PostgreSQL CHECK constraints are evaluated per-row in isolation.
  They cannot reference data in other tables (e.g. summing sibling rows
  against a parent column). A AFTER row-level trigger on the splits table
  can perform this cross-table aggregate check correctly.

Trigger design:
  Function : fn_check_split_sum()
    - Determines the affected expense_id from NEW (INSERT/UPDATE) or
      OLD (DELETE).
    - Queries SUM(amount) FROM splits WHERE expense_id = <affected>.
    - Queries amount FROM expenses WHERE id = <affected>.
    - Raises EXCEPTION (SQLSTATE '23514' — check_violation) if they differ.

  Trigger  : trg_splits_sum_check
    - AFTER INSERT OR UPDATE OR DELETE ON splits
    - FOR EACH ROW
    - EXECUTES fn_check_split_sum()

  The trigger fires AFTER the DML so that the aggregate reflects the
  new state of the table. This allows a batch of split inserts within
  a single transaction (as expense_service.py does) as long as the
  final state satisfies INV-1 by commit time.

  IMPORTANT — deferred execution:
    The trigger is created as INITIALLY DEFERRED so that it fires at
    COMMIT rather than after each individual row operation. This is
    necessary because expense_service.py:
      1. Writes the expense row (flush)
      2. Writes each split row one at a time (flush)
    After step 1 and before the last split is written, the intermediate
    sum will not equal the expense amount. Without DEFERRABLE, the trigger
    would fire and raise an exception prematurely.

GUIDE Rule 7 — Append-only:
  This file must NEVER be edited after it has been applied to any database.
  If a change is needed, create a new corrective migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ── Alembic revision identifiers ──────────────────────────────────────────
revision: str = "002_add_split_sum_trigger"
down_revision: str | None = "001_initial_schema"
branch_labels: tuple | None = None
depends_on: tuple | None = None


# ── SQL definitions ────────────────────────────────────────────────────────
#
# Defined as module-level constants so upgrade() and downgrade() reference
# the same names, and so the SQL is easy to review in isolation.

_CREATE_FUNCTION = """
                   CREATE OR REPLACE FUNCTION fn_check_split_sum()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
                   v_expense_id  INTEGER;
    v_split_sum   NUMERIC(12, 2);
    v_expense_amt NUMERIC(12, 2);
                   BEGIN
    -- Determine which expense is affected by this DML operation.
    -- DELETE provides OLD; INSERT and UPDATE provide NEW.
    IF TG_OP = 'DELETE' THEN
        v_expense_id := OLD.expense_id;
                   ELSE
        v_expense_id := NEW.expense_id;
                   END IF;

    -- Aggregate the current split total for the affected expense.
    -- COALESCE handles the edge case where all splits were just deleted
    -- (sum would be NULL); in that case we compare 0 against the amount.
                   SELECT COALESCE(SUM(amount), 0)
                   INTO v_split_sum
                   FROM splits
                   WHERE expense_id = v_expense_id;

                   -- Read the expected total from the parent expense row.
                   SELECT amount
                   INTO v_expense_amt
                   FROM expenses
                   WHERE id = v_expense_id;

                   -- INV-1: the sums must be exactly equal.
                   -- NUMERIC(12,2) equality is exact — no floating-point tolerance needed.
                   IF v_split_sum <> v_expense_amt THEN
        RAISE EXCEPTION
            'INV-1 violated: split sum (%) does not equal expense amount (%) for expense id=%',
            v_split_sum, v_expense_amt, v_expense_id
            USING ERRCODE = '23514';  -- check_violation
                   END IF;

    -- Triggers must return a row value for row-level triggers.
    -- For AFTER triggers the return value is ignored by PostgreSQL,
    -- but RETURN NEW / RETURN OLD is required by the language spec.
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
                   ELSE
        RETURN NEW;
                   END IF;
                   END;
$$; \
                   """

_CREATE_TRIGGER = """
CREATE CONSTRAINT TRIGGER trg_splits_sum_check
    AFTER INSERT OR UPDATE OR DELETE
    ON splits
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION fn_check_split_sum();
"""

_DROP_TRIGGER = "DROP TRIGGER IF EXISTS trg_splits_sum_check ON splits;"
_DROP_FUNCTION = "DROP FUNCTION IF EXISTS fn_check_split_sum();"


def upgrade() -> None:
    """
    Creates the split-sum integrity trigger and its backing function.

    Execution order:
      1. Create fn_check_split_sum() — must exist before the trigger references it.
      2. Create trg_splits_sum_check — CONSTRAINT TRIGGER, DEFERRABLE INITIALLY DEFERRED.

    After this migration is applied, any transaction that leaves a splits table
    in a state where sum(splits.amount) != expenses.amount will fail at commit
    with SQLSTATE 23514 (check_violation), even if the write bypassed the
    service layer entirely.
    """
    op.execute(_CREATE_FUNCTION)
    op.execute(_CREATE_TRIGGER)


def downgrade() -> None:
    """
    Removes the trigger and its backing function.

    Drop order is the reverse of creation: trigger first (it references the
    function), then the function.

    After downgrade, INV-1 is enforced only by the service layer and unit tests.
    Re-run upgrade() (or apply a new migration) to restore DB-level enforcement.

    GUIDE Rule 7: in production, prefer a corrective migration over downgrade.
    """
    op.execute(_DROP_TRIGGER)
    op.execute(_DROP_FUNCTION)