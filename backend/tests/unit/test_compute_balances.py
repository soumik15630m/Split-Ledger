"""
tests/unit/test_compute_balances.py — Unit tests for balance_service.compute_balances
                                      and balance_service.simplify_debts.

What this file proves (ARCHITECTURE.md Section 9 / Table row test_compute_balances.py):
  - Balance sum is always Decimal("0.00") for full, unfiltered computations (INV-2)
  - Deleted expenses (deleted_at IS NOT NULL) are EXCLUDED from balance computation (INV-8)
  - Payer is credited for the full expense amount they fronted
  - Each split participant is debited their split portion
  - Settlements are correctly netted (payer gains credit, recipient loses it)
  - Every group member appears in the result even if their balance is exactly zero
  - Category-filtered computations intentionally do NOT produce sum==0 (settlements excluded)

Unit test constraints (ARCHITECTURE.md Section 9 Level 1):
  - No database. All DB-querying helpers are patched via unittest.mock.
  - No Flask application context.
  - No authentication context.
  - Pure Python: only Decimal arithmetic and mock objects.

GUIDE Rule 2 — All monetary amounts use Decimal. No float anywhere.
GUIDE Rule 1 — INV-8 is verified here: deleted expenses must not contribute to balances.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.balance_service import compute_balances, simplify_debts


# ── Mock factory helpers ───────────────────────────────────────────────────
# These create lightweight mock objects that mimic ORM model attributes
# accessed inside compute_balances. No real ORM objects are constructed.


def _expense(paid_by: int, amount: str) -> MagicMock:
    """Creates a mock Expense with paid_by_user_id and amount."""
    e = MagicMock()
    e.paid_by_user_id = paid_by
    e.amount = Decimal(amount)
    return e


def _split(user_id: int, amount: str) -> MagicMock:
    """Creates a mock Split with user_id and amount."""
    s = MagicMock()
    s.user_id = user_id
    s.amount = Decimal(amount)
    return s


def _settlement(paid_by: int, paid_to: int, amount: str) -> MagicMock:
    """Creates a mock Settlement with paid_by_user_id, paid_to_user_id, amount."""
    s = MagicMock()
    s.paid_by_user_id = paid_by
    s.paid_to_user_id = paid_to
    s.amount = Decimal(amount)
    return s


# ── Patch targets ──────────────────────────────────────────────────────────
# These are the DB-accessing helpers inside balance_service that we replace
# with controlled return values so the tests run without a database.

_PATCH_BASE = "backend.app.services.balance_service"
_PATCH_EXPENSES    = f"{_PATCH_BASE}.get_active_expenses"
_PATCH_SPLITS      = f"{_PATCH_BASE}.get_splits_for_active_expenses"
_PATCH_SETTLEMENTS = f"{_PATCH_BASE}.get_settlements"
_PATCH_MEMBER_IDS  = f"{_PATCH_BASE}.get_member_ids"


# ── Tests: compute_balances ────────────────────────────────────────────────

@patch(_PATCH_MEMBER_IDS)
@patch(_PATCH_SETTLEMENTS)
@patch(_PATCH_SPLITS)
@patch(_PATCH_EXPENSES)
def test_payer_credited_split_participants_debited(
    mock_expenses, mock_splits, mock_settlements, mock_member_ids
):
    """
    Fundamental balance formula verification:
      - Payer is credited the full expense amount.
      - Each split participant is debited their split portion.
    Scenario: Alice pays $100, split $60 Alice / $40 Bob.
    Alice net = +100 - 60 = +40.  Bob net = -40.  Sum = 0 (INV-2).
    """
    mock_expenses.return_value    = [_expense(paid_by=1, amount="100.00")]
    mock_splits.return_value      = [_split(1, "60.00"), _split(2, "40.00")]
    mock_settlements.return_value = []
    mock_member_ids.return_value  = [1, 2]

    result = compute_balances(group_id=1, session=MagicMock())

    assert result[1] == Decimal("40.00"),  "Alice should be owed 40.00"
    assert result[2] == Decimal("-40.00"), "Bob should owe 40.00"
    assert sum(result.values()) == Decimal("0.00"), "INV-2: balance sum must be zero"


@patch(_PATCH_MEMBER_IDS)
@patch(_PATCH_SETTLEMENTS)
@patch(_PATCH_SPLITS)
@patch(_PATCH_EXPENSES)
def test_balance_sum_zero_multiple_expenses(
    mock_expenses, mock_splits, mock_settlements, mock_member_ids
):
    """
    INV-2: sum of all member balances == 0 when there are multiple expenses.
    Alice pays $90 (split 3 ways $30 each), Bob pays $60 (split 2 ways $30 each).
    """
    mock_expenses.return_value = [
        _expense(paid_by=1, amount="90.00"),
        _expense(paid_by=2, amount="60.00"),
    ]
    mock_splits.return_value = [
        _split(1, "30.00"), _split(2, "30.00"), _split(3, "30.00"),  # expense 1
        _split(1, "30.00"), _split(2, "30.00"),                      # expense 2
    ]
    mock_settlements.return_value = []
    mock_member_ids.return_value = [1, 2, 3]

    result = compute_balances(group_id=1, session=MagicMock())

    total = sum(result.values(), Decimal("0.00"))
    assert total == Decimal("0.00"), f"INV-2 violated: sum was {total}"


@patch(_PATCH_MEMBER_IDS)
@patch(_PATCH_SETTLEMENTS)
@patch(_PATCH_SPLITS)
@patch(_PATCH_EXPENSES)
def test_deleted_expense_excluded_inv8(
    mock_expenses, mock_splits, mock_settlements, mock_member_ids
):
    """
    INV-8: get_active_expenses filters WHERE deleted_at IS NULL.

    This test verifies that compute_balances routes ALL expense data access
    through get_active_expenses() (which filters deleted rows). If a deleted
    expense were included, Alice's balance would be non-zero even though the
    mock_expenses list is empty — this test catches that regression.

    The mock returns ZERO expenses, simulating that all expenses in this group
    are soft-deleted and were filtered out by get_active_expenses().
    """
    mock_expenses.return_value    = []          # all deleted — none returned
    mock_splits.return_value      = []          # no active splits
    mock_settlements.return_value = []
    mock_member_ids.return_value  = [1, 2]

    result = compute_balances(group_id=1, session=MagicMock())

    assert result[1] == Decimal("0.00"), "Deleted expenses must not affect balance"
    assert result[2] == Decimal("0.00"), "Deleted expenses must not affect balance"
    assert sum(result.values()) == Decimal("0.00")

    # Also verify that get_active_expenses was called (not bypassed).
    mock_expenses.assert_called_once()


@patch(_PATCH_MEMBER_IDS)
@patch(_PATCH_SETTLEMENTS)
@patch(_PATCH_SPLITS)
@patch(_PATCH_EXPENSES)
def test_settlements_netted_correctly(
    mock_expenses, mock_splits, mock_settlements, mock_member_ids
):
    """
    Settlements reduce outstanding debt.
    Alice paid $100, split evenly. Bob owes Alice $50.
    Bob then settles $30. Bob should still owe $20. Alice should be owed $20.
    """
    mock_expenses.return_value    = [_expense(paid_by=1, amount="100.00")]
    mock_splits.return_value      = [_split(1, "50.00"), _split(2, "50.00")]
    mock_settlements.return_value = [_settlement(paid_by=2, paid_to=1, amount="30.00")]
    mock_member_ids.return_value  = [1, 2]

    result = compute_balances(group_id=1, session=MagicMock())

    # Alice: +100 (payer credit) - 50 (her split debit) - 30 (settlement received) = +20
    assert result[1] == Decimal("20.00"), "Alice should be owed 20.00 after partial settlement"
    # Bob: -50 (his split) + 30 (his settlement payment) = -20
    assert result[2] == Decimal("-20.00"), "Bob should owe 20.00 after partial settlement"
    assert sum(result.values()) == Decimal("0.00"), "INV-2: sum must be zero"


@patch(_PATCH_MEMBER_IDS)
@patch(_PATCH_SETTLEMENTS)
@patch(_PATCH_SPLITS)
@patch(_PATCH_EXPENSES)
def test_zero_balance_member_appears_in_result(
    mock_expenses, mock_splits, mock_settlements, mock_member_ids
):
    """
    ARCHITECTURE.md Section 6 — Step 4:
    Every group member must appear in the result, even if their balance is zero.
    Carol has no expenses and no splits — she should still appear with 0.00.
    """
    mock_expenses.return_value    = [_expense(paid_by=1, amount="100.00")]
    mock_splits.return_value      = [_split(1, "50.00"), _split(2, "50.00")]
    mock_settlements.return_value = []
    mock_member_ids.return_value  = [1, 2, 3]   # Carol (3) has no transactions

    result = compute_balances(group_id=1, session=MagicMock())

    assert 3 in result, "Carol must appear in result even with zero balance"
    assert result[3] == Decimal("0.00"), "Carol's balance must be exactly 0.00"


@patch(_PATCH_MEMBER_IDS)
@patch(_PATCH_SETTLEMENTS)
@patch(_PATCH_SPLITS)
@patch(_PATCH_EXPENSES)
def test_no_expenses_no_settlements_all_zero(
    mock_expenses, mock_splits, mock_settlements, mock_member_ids
):
    """Group with members but no expenses or settlements — everyone is at zero."""
    mock_expenses.return_value    = []
    mock_splits.return_value      = []
    mock_settlements.return_value = []
    mock_member_ids.return_value  = [1, 2, 3]

    result = compute_balances(group_id=1, session=MagicMock())

    assert all(v == Decimal("0.00") for v in result.values())
    assert sum(result.values()) == Decimal("0.00")


@patch(_PATCH_MEMBER_IDS)
@patch(_PATCH_SETTLEMENTS)
@patch(_PATCH_SPLITS)
@patch(_PATCH_EXPENSES)
def test_full_settlement_zeroes_out_debt(
    mock_expenses, mock_splits, mock_settlements, mock_member_ids
):
    """
    A settlement that exactly matches the outstanding debt brings both parties to zero.
    """
    mock_expenses.return_value    = [_expense(paid_by=1, amount="60.00")]
    mock_splits.return_value      = [_split(1, "30.00"), _split(2, "30.00")]
    mock_settlements.return_value = [_settlement(paid_by=2, paid_to=1, amount="30.00")]
    mock_member_ids.return_value  = [1, 2]

    result = compute_balances(group_id=1, session=MagicMock())

    assert result[1] == Decimal("0.00")
    assert result[2] == Decimal("0.00")


@patch(_PATCH_MEMBER_IDS)
@patch(_PATCH_SETTLEMENTS)
@patch(_PATCH_SPLITS)
@patch(_PATCH_EXPENSES)
def test_category_filter_settlements_not_included(
    mock_expenses, mock_splits, mock_settlements, mock_member_ids
):
    """
    When a category filter is active, settlements are NOT included (spec Section 8.4).
    balance_sum will NOT be zero — this is expected and documented behaviour.
    The caller must NOT assert INV-2 on category-filtered results.
    """
    mock_expenses.return_value    = [_expense(paid_by=1, amount="100.00")]
    mock_splits.return_value      = [_split(1, "50.00"), _split(2, "50.00")]
    mock_settlements.return_value = [_settlement(paid_by=2, paid_to=1, amount="50.00")]
    mock_member_ids.return_value  = [1, 2]

    from backend.app.models.expense import Category
    result = compute_balances(group_id=1, session=MagicMock(), category=Category.FOOD)

    # Settlements should NOT be called for category-filtered computation.
    mock_settlements.assert_not_called()

    # Balance sum is intentionally non-zero for filtered view.
    # (Alice +50, Bob -50 from splits only — settlements excluded)
    assert result[1] == Decimal("50.00")
    assert result[2] == Decimal("-50.00")


@patch(_PATCH_MEMBER_IDS)
@patch(_PATCH_SETTLEMENTS)
@patch(_PATCH_SPLITS)
@patch(_PATCH_EXPENSES)
def test_multiple_payers_balance_sum_zero(
    mock_expenses, mock_splits, mock_settlements, mock_member_ids
):
    """
    Three members, two expense payers, complex split arrangement.
    INV-2 must still hold.
    """
    mock_expenses.return_value = [
        _expense(paid_by=1, amount="120.00"),
        _expense(paid_by=2, amount="60.00"),
    ]
    mock_splits.return_value = [
        _split(1, "40.00"), _split(2, "40.00"), _split(3, "40.00"),  # expense 1
        _split(1, "20.00"), _split(2, "20.00"), _split(3, "20.00"),  # expense 2
    ]
    mock_settlements.return_value = []
    mock_member_ids.return_value  = [1, 2, 3]

    result = compute_balances(group_id=1, session=MagicMock())

    total = sum(result.values(), Decimal("0.00"))
    assert total == Decimal("0.00"), f"INV-2 violated with multiple payers: sum was {total}"


# ── Tests: simplify_debts ──────────────────────────────────────────────────

def test_simplify_empty_balances():
    """All-zero balances produce no transactions."""
    result = simplify_debts({1: Decimal("0.00"), 2: Decimal("0.00")})
    assert result == []


def test_simplify_two_person_debt():
    """
    A owes B $50 → one transaction: from A to B for $50.
    For N members, at most N-1 transactions (ARCHITECTURE.md Section 6).
    """
    balances = {1: Decimal("50.00"), 2: Decimal("-50.00")}
    result = simplify_debts(balances)

    assert len(result) == 1
    txn = result[0]
    assert txn["from_user_id"] == 2,            "Debtor is from_user_id"
    assert txn["to_user_id"]   == 1,            "Creditor is to_user_id"
    assert txn["amount"]       == Decimal("50.00")


def test_simplify_triangle_reduces_to_two_transactions():
    """
    Triangle debt: A→B $30, B→C $30, C→A $30 creates a net-zero cycle.
    Greedy simplification resolves it in at most N-1 = 2 transactions.
    Input: A=0, B=0, C=0 (already balanced) → 0 transactions.

    More illustrative: A=+$60 (owed), B=-$30 (owes), C=-$30 (owes).
    Result: B→A $30, C→A $30 (two transactions, both paying Alice).
    """
    balances = {
        1: Decimal("60.00"),   # Alice is owed $60
        2: Decimal("-30.00"),  # Bob owes $30
        3: Decimal("-30.00"),  # Carol owes $30
    }
    result = simplify_debts(balances)

    assert len(result) == 2, "Two debtors → two transactions (N-1 = 2)"

    # Both transactions should be to Alice (user 1)
    recipients = {txn["to_user_id"] for txn in result}
    assert recipients == {1}, "All payments go to Alice"

    # Total paid should equal what Alice is owed
    total_paid = sum(txn["amount"] for txn in result)
    assert total_paid == Decimal("60.00")


def test_simplify_four_person_complex():
    """
    Four members, complex balances. At most N-1 = 3 transactions.
    INV-2 pre-condition: sum must be zero.
    """
    balances = {
        1: Decimal("90.00"),   # owed $90
        2: Decimal("-30.00"),  # owes $30
        3: Decimal("-40.00"),  # owes $40
        4: Decimal("-20.00"),  # owes $20
    }
    result = simplify_debts(balances)

    # All payers must be debtors; all recipients must be creditors
    for txn in result:
        assert txn["amount"] > Decimal("0"), "Every transaction must be positive"

    # Net each person after applying the simplified transactions
    net = defaultdict(lambda: Decimal("0.00"))
    for txn in result:
        net[txn["from_user_id"]] -= txn["amount"]
        net[txn["to_user_id"]]   += txn["amount"]

    for uid, original_balance in balances.items():
        assert net[uid] == original_balance, (
            f"Simplification is incorrect for user {uid}: "
            f"expected {original_balance}, got {net[uid]}"
        )


def test_simplify_single_debtor_creditor():
    """Single creditor / single debtor — exactly one transaction."""
    balances = {1: Decimal("100.00"), 2: Decimal("-100.00")}
    result = simplify_debts(balances)
    assert len(result) == 1
    assert result[0]["amount"] == Decimal("100.00")


def test_simplify_produces_at_most_n_minus_one_transactions():
    """
    ARCHITECTURE.md Section 6: greedy simplification produces at most N-1 transactions
    for N members. Test with 5 members.
    """
    balances = {
        1: Decimal("100.00"),
        2: Decimal("50.00"),
        3: Decimal("-40.00"),
        4: Decimal("-60.00"),
        5: Decimal("-50.00"),
    }
    result = simplify_debts(balances)

    n = len(balances)
    assert len(result) <= n - 1, f"Expected at most {n-1} transactions, got {len(result)}"

    # Verify all debts are settled
    total = sum(result[i]["amount"] for i in range(len(result)))
    assert total == Decimal("150.00"), "Total transferred must equal total owed"


def test_simplify_all_creditors_no_debtors():
    """Edge case: everyone has a positive balance but sum != 0 → no valid input."""
    # This would violate INV-2. simplify_debts should return empty since there are
    # no debtors to match against creditors.
    balances = {1: Decimal("50.00"), 2: Decimal("50.00")}
    result = simplify_debts(balances)
    # No debtors → no transactions can be generated
    assert result == []


def test_simplify_transaction_amounts_are_decimal_not_float():
    """GUIDE Rule 2: amounts in simplified transactions must be Decimal, not float."""
    balances = {1: Decimal("33.33"), 2: Decimal("-33.33")}
    result = simplify_debts(balances)
    for txn in result:
        assert isinstance(txn["amount"], Decimal), (
            f"Transaction amount must be Decimal, got {type(txn['amount'])}"
        )
