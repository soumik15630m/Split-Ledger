"""
tests/unit/test_debt_simplification.py — Unit tests for balance_service.simplify_debts.

What this file proves (ARCHITECTURE.md Section 9 / Table row test_debt_simplification.py):
  - Two-person debt → single transaction
  - Triangle: 3 members with circular debt reduces to at most N-1 = 2 transactions
  - All-zero balances → empty transaction list
  - Large group (4+ members) → at most N-1 transactions
  - All transactions are directionally correct (debtor → creditor)
  - Simplification is economically correct: applying the transactions produces the same
    net positions as the original balances
  - Transaction amounts are Decimal, not float (GUIDE Rule 2)

Unit test constraints (ARCHITECTURE.md Section 9 Level 1):
  - No database, no Flask, no auth context.
  - simplify_debts takes a plain dict[int, Decimal] — no mocking required.

Pre-condition for simplify_debts: sum(balances.values()) == 0 (INV-2).
  Passing a category-filtered result violates this contract. This file only
  passes correctly-summed input per the function's contract.

ARCHITECTURE.md Section 9.3 note: "AI-generated — MUST be verified by tests."
This test suite is the verification referenced in that note.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import pytest

from backend.app.services.balance_service import simplify_debts


# ── Helpers ────────────────────────────────────────────────────────────────

def _verify_correctness(
    original_balances: dict[int, Decimal],
    transactions: list[dict],
) -> None:
    """
    Applies the simplified transactions to a copy of the balances and asserts
    that the resulting net positions match the original input.

    This is the economic correctness check: simplify_debts must not invent
    money, lose money, or misroute payments.
    """
    net = defaultdict(lambda: Decimal("0.00"))
    for txn in transactions:
        net[txn["from_user_id"]] -= txn["amount"]
        net[txn["to_user_id"]]   += txn["amount"]

    for uid, expected_balance in original_balances.items():
        actual = net[uid]
        assert actual == expected_balance, (
            f"Simplification incorrect for user {uid}: "
            f"expected net change {expected_balance}, got {actual}"
        )


def _sum_balances(balances: dict[int, Decimal]) -> Decimal:
    """Utility to verify INV-2 pre-condition before calling simplify_debts."""
    return sum(balances.values(), Decimal("0.00"))


# ── Tests ──────────────────────────────────────────────────────────────────

def test_all_zero_returns_empty_list():
    """
    All balances are zero → no transactions needed.
    """
    balances = {1: Decimal("0.00"), 2: Decimal("0.00"), 3: Decimal("0.00")}
    result = simplify_debts(balances)
    assert result == []


def test_empty_dict_returns_empty_list():
    """Edge case: no members."""
    result = simplify_debts({})
    assert result == []


def test_two_person_debt_one_transaction():
    """
    Alice is owed $50 (balance +50), Bob owes $50 (balance -50).
    Result: exactly one transaction, Bob → Alice, $50.
    """
    balances = {1: Decimal("50.00"), 2: Decimal("-50.00")}
    assert _sum_balances(balances) == Decimal("0.00"), "INV-2 pre-condition must hold"

    result = simplify_debts(balances)

    assert len(result) == 1
    txn = result[0]
    assert txn["from_user_id"] == 2, "Bob (debtor) should pay"
    assert txn["to_user_id"]   == 1, "Alice (creditor) should receive"
    assert txn["amount"]       == Decimal("50.00")


def test_three_person_one_creditor_two_debtors():
    """
    Alice +$100, Bob -$40, Carol -$60.
    Two transactions: Bob → Alice $40, Carol → Alice $60.
    At most N-1 = 2 transactions.
    """
    balances = {
        1: Decimal("100.00"),
        2: Decimal("-40.00"),
        3: Decimal("-60.00"),
    }
    assert _sum_balances(balances) == Decimal("0.00")

    result = simplify_debts(balances)

    assert len(result) <= 2, f"Expected at most 2 transactions, got {len(result)}"
    _verify_correctness(balances, result)

    # All payments should go to Alice
    for txn in result:
        assert txn["to_user_id"] == 1


def test_triangle_reduces_to_at_most_n_minus_one():
    """
    Triangle: A+$60 (owed), B-$30, C-$30.
    N=3, so at most N-1=2 transactions.
    """
    balances = {
        1: Decimal("60.00"),
        2: Decimal("-30.00"),
        3: Decimal("-30.00"),
    }
    assert _sum_balances(balances) == Decimal("0.00")

    result = simplify_debts(balances)

    assert len(result) <= 2
    _verify_correctness(balances, result)


def test_two_creditors_two_debtors():
    """
    Alice +$80, Dave +$20, Bob -$50, Carol -$50.
    N=4, at most N-1=3 transactions.
    Economic correctness verified by _verify_correctness.
    """
    balances = {
        1: Decimal("80.00"),   # Alice owed
        2: Decimal("-50.00"),  # Bob owes
        3: Decimal("-50.00"),  # Carol owes
        4: Decimal("20.00"),   # Dave owed
    }
    assert _sum_balances(balances) == Decimal("0.00")

    result = simplify_debts(balances)

    assert len(result) <= 3
    _verify_correctness(balances, result)


def test_five_member_group_at_most_n_minus_1():
    """
    Five members. At most N-1=4 transactions (ARCHITECTURE.md Section 6).
    """
    balances = {
        1: Decimal("100.00"),
        2: Decimal("50.00"),
        3: Decimal("-40.00"),
        4: Decimal("-60.00"),
        5: Decimal("-50.00"),
    }
    assert _sum_balances(balances) == Decimal("0.00")

    result = simplify_debts(balances)

    assert len(result) <= 4
    _verify_correctness(balances, result)


def test_single_cent_debt():
    """Minimum meaningful amount: $0.01."""
    balances = {1: Decimal("0.01"), 2: Decimal("-0.01")}
    assert _sum_balances(balances) == Decimal("0.00")

    result = simplify_debts(balances)

    assert len(result) == 1
    assert result[0]["amount"] == Decimal("0.01")


def test_large_amounts():
    """Large monetary values work correctly."""
    balances = {
        1: Decimal("999999.99"),
        2: Decimal("-999999.99"),
    }
    assert _sum_balances(balances) == Decimal("0.00")

    result = simplify_debts(balances)

    assert result[0]["amount"] == Decimal("999999.99")


def test_all_positive_no_debtors():
    """
    If everyone has a positive balance (violates INV-2, but tests defensive behaviour).
    simplify_debts finds no debtors → returns empty list (no crashes).
    """
    balances = {1: Decimal("50.00"), 2: Decimal("50.00")}
    # sum != 0 — caller should never pass this, but the function must not crash
    result = simplify_debts(balances)
    assert result == []


def test_all_negative_no_creditors():
    """
    If everyone has a negative balance (violates INV-2, but tests defensive behaviour).
    simplify_debts finds no creditors → returns empty list (no crashes).
    """
    balances = {1: Decimal("-50.00"), 2: Decimal("-50.00")}
    result = simplify_debts(balances)
    assert result == []


def test_transaction_amounts_are_decimal_not_float():
    """
    GUIDE Rule 2: every transaction amount must be Decimal, never float.
    """
    balances = {1: Decimal("33.33"), 2: Decimal("-33.33")}
    result = simplify_debts(balances)

    for txn in result:
        assert isinstance(txn["amount"], Decimal), (
            f"Transaction amount is {type(txn['amount'])}, expected Decimal — "
            "GUIDE Rule 2 violated"
        )


def test_transaction_amounts_are_positive():
    """Every generated transaction must have a strictly positive amount."""
    balances = {
        1: Decimal("100.00"),
        2: Decimal("-60.00"),
        3: Decimal("-40.00"),
    }
    result = simplify_debts(balances)

    for txn in result:
        assert txn["amount"] > Decimal("0.00"), "All transaction amounts must be > 0"


def test_no_self_transactions_generated():
    """
    simplify_debts must never generate a transaction where from_user_id == to_user_id.
    That would be an invalid self-settlement (INV-4 equivalent in the simplification domain).
    """
    balances = {
        1: Decimal("50.00"),
        2: Decimal("-30.00"),
        3: Decimal("-20.00"),
    }
    result = simplify_debts(balances)

    for txn in result:
        assert txn["from_user_id"] != txn["to_user_id"], (
            "simplify_debts must not generate self-transactions"
        )


def test_partial_settlement_scenario():
    """
    After a partial settlement, remaining debt is simplifiable.
    Alice +$20, Bob -$20 (after Bob already paid $30 of $50).
    """
    balances = {1: Decimal("20.00"), 2: Decimal("-20.00")}
    assert _sum_balances(balances) == Decimal("0.00")

    result = simplify_debts(balances)

    assert len(result) == 1
    assert result[0]["amount"] == Decimal("20.00")
    _verify_correctness(balances, result)


def test_result_structure_has_required_keys():
    """
    Each transaction dict must contain exactly the keys the route expects:
    from_user_id, to_user_id, amount.
    """
    balances = {1: Decimal("40.00"), 2: Decimal("-40.00")}
    result = simplify_debts(balances)

    for txn in result:
        assert "from_user_id" in txn
        assert "to_user_id"   in txn
        assert "amount"       in txn
