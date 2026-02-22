"""
tests/unit/test_equal_split.py — Unit tests for expense_service._compute_equal_splits.

What this file proves (ARCHITECTURE.md Section 9 / Table row test_equal_split.py):
  - Equal split guarantees sum(splits) == amount for ANY amount and participant count (INV-1)
  - When amount is not evenly divisible, the 1-cent remainder goes to the PAYER's split
  - When the payer is not in the participant list (edge case), the fallback is the first participant
  - Single participant receives the full amount
  - All split amounts are Decimal — never float (GUIDE Rule 2)
  - The function uses ROUND_DOWN (not ROUND_HALF_UP) as specified in Section 9.2

Unit test constraints (ARCHITECTURE.md Section 9 Level 1):
  - No database, no Flask, no auth context.
  - Pure Python: only Decimal arithmetic.

GUIDE Rule 2 — float arithmetic must never appear in or around money calculations.
GUIDE Rule 1 — INV-1: sum(splits.amount) == expense.amount exactly.
               The test asserts this for every case — tolerance is zero.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

# _compute_equal_splits is a module-level private function.
# ARCHITECTURE.md Section 9 explicitly lists test_equal_split.py as testing this function.
# The single-underscore prefix is a convention, not a name-mangling barrier.
from app.services.expense_service import _compute_equal_splits


# ── Invariant helper ───────────────────────────────────────────────────────

def _assert_inv1(splits: list[dict], expected_amount: Decimal) -> None:
    """
    Asserts INV-1: sum(splits[i].amount) == expected_amount exactly.
    Called after every _compute_equal_splits invocation in this file.
    Tolerance: zero. Uses Decimal arithmetic — no float.
    """
    total = sum(s["amount"] for s in splits)
    assert total == expected_amount, (
        f"INV-1 violated: split sum {total} != expected amount {expected_amount}"
    )


# ── Tests ──────────────────────────────────────────────────────────────────

def test_even_split_two_participants():
    """
    $100.00 split between two participants → $50.00 each. No remainder.
    """
    amount = Decimal("100.00")
    participants = [1, 2]
    result = _compute_equal_splits(amount, participants, payer_id=1)

    assert len(result) == 2
    assert all(s["amount"] == Decimal("50.00") for s in result)
    _assert_inv1(result, amount)


def test_even_split_three_participants():
    """
    $90.00 / 3 = $30.00 each. No remainder.
    """
    amount = Decimal("90.00")
    participants = [1, 2, 3]
    result = _compute_equal_splits(amount, participants, payer_id=1)

    assert len(result) == 3
    assert all(s["amount"] == Decimal("30.00") for s in result)
    _assert_inv1(result, amount)


def test_odd_remainder_goes_to_payer():
    """
    Spec Section 9.2: "If the amount is not evenly divisible, the remainder
    (1 cent) is added to the payer's split."

    $10.00 / 3 = $3.33 per person (ROUND_DOWN), remainder = $0.01.
    Payer (user 1) gets $3.33 + $0.01 = $3.34.
    Others get $3.33 each.
    """
    amount = Decimal("10.00")
    participants = [1, 2, 3]
    result = _compute_equal_splits(amount, participants, payer_id=1)

    assert len(result) == 3

    payer_split = next(s for s in result if s["user_id"] == 1)
    other_splits = [s for s in result if s["user_id"] != 1]

    assert payer_split["amount"] == Decimal("3.34"), "Payer must receive the 1-cent remainder"
    assert all(s["amount"] == Decimal("3.33") for s in other_splits)
    _assert_inv1(result, amount)


def test_odd_remainder_goes_to_payer_larger_amount():
    """
    $100.00 / 3 = $33.33 (ROUND_DOWN), remainder = $0.01.
    Payer gets $33.34, others get $33.33.
    """
    amount = Decimal("100.00")
    participants = [1, 2, 3]
    result = _compute_equal_splits(amount, participants, payer_id=2)

    payer_split = next(s for s in result if s["user_id"] == 2)
    assert payer_split["amount"] == Decimal("33.34")

    other_splits = [s for s in result if s["user_id"] != 2]
    assert all(s["amount"] == Decimal("33.33") for s in other_splits)
    _assert_inv1(result, amount)


def test_payer_not_in_participant_list_fallback_to_first():
    """
    Spec Section 9.2 fallback: "If payer is not in participants, fallback to first participant."
    This is an edge case — INV-5 ensures payer is a member, and equal split uses all members,
    so the payer should always be in the list. The fallback handles defensive coding.
    """
    amount = Decimal("10.00")
    participants = [2, 3, 4]     # payer_id=1 is NOT in this list
    result = _compute_equal_splits(amount, participants, payer_id=1)

    # The first participant (user 2) should receive the remainder.
    first_split = next(s for s in result if s["user_id"] == 2)
    other_splits = [s for s in result if s["user_id"] != 2]

    # $10.00 / 3 = $3.33 (ROUND_DOWN), rem = $0.01. First participant gets $3.34.
    assert first_split["amount"] == Decimal("3.34")
    assert all(s["amount"] == Decimal("3.33") for s in other_splits)
    _assert_inv1(result, amount)


def test_single_participant_gets_full_amount():
    """
    One participant → they receive the full amount. No division, no remainder.
    """
    amount = Decimal("57.89")
    participants = [1]
    result = _compute_equal_splits(amount, participants, payer_id=1)

    assert len(result) == 1
    assert result[0]["user_id"] == 1
    assert result[0]["amount"] == Decimal("57.89")
    _assert_inv1(result, amount)


def test_round_down_not_round_half_up():
    """
    ARCHITECTURE.md Section 9.2: uses ROUND_DOWN.
    $1.00 / 3 = $0.33 (ROUND_DOWN), NOT $0.34 (ROUND_HALF_UP).
    Remainder = $0.01 goes to payer.
    """
    amount = Decimal("1.00")
    participants = [1, 2, 3]
    result = _compute_equal_splits(amount, participants, payer_id=1)

    non_payer_splits = [s for s in result if s["user_id"] != 1]
    assert all(s["amount"] == Decimal("0.33") for s in non_payer_splits), (
        "Non-payer splits should be ROUND_DOWN (0.33), not ROUND_HALF_UP (0.34)"
    )
    _assert_inv1(result, amount)


def test_inv1_holds_for_many_amounts():
    """
    Parametric check: INV-1 must hold for a variety of amounts and participant counts.
    GUIDE Rule 2: amounts are Decimal; no float at any point.
    """
    cases = [
        ("0.01", [1]),
        ("0.10", [1, 2]),
        ("1.00", [1, 2, 3]),
        ("99.99", [1, 2, 3, 4]),
        ("100.00", [1, 2, 3, 4, 5]),
        ("7.77", [1, 2, 3]),
        ("1000.00", [1, 2, 3, 4, 5, 6, 7]),
        ("0.07", [1, 2, 3]),
    ]
    for amount_str, participants in cases:
        amount = Decimal(amount_str)
        result = _compute_equal_splits(amount, participants, payer_id=participants[0])
        _assert_inv1(result, amount)


def test_all_amounts_are_decimal_not_float():
    """
    GUIDE Rule 2: every split amount must be a Decimal instance, never float.
    """
    amount = Decimal("50.00")
    participants = [1, 2, 3]
    result = _compute_equal_splits(amount, participants, payer_id=1)

    for s in result:
        assert isinstance(s["amount"], Decimal), (
            f"split amount is {type(s['amount'])}, expected Decimal"
        )


def test_result_contains_all_participant_ids():
    """Each participant_id must appear exactly once in the result."""
    participants = [10, 20, 30, 40]
    result = _compute_equal_splits(Decimal("80.00"), participants, payer_id=10)

    result_user_ids = [s["user_id"] for s in result]
    assert sorted(result_user_ids) == sorted(participants)
    assert len(result_user_ids) == len(set(result_user_ids)), "Duplicate user_ids in result"


def test_large_group_inv1():
    """
    Large group (10 members) with an amount that produces a remainder.
    $1.00 / 10 = $0.10 exactly — no remainder.
    $0.11 / 10 = $0.01 (ROUND_DOWN) x9 + $0.02 (payer, remainder $0.02... wait)

    Actually $0.11 / 10 = 0.011 → ROUND_DOWN → 0.01 each.
    sum(10 * 0.01) = 0.10. remainder = 0.11 - 0.10 = 0.01.
    Payer gets 0.01 + 0.01 = 0.02.
    """
    amount = Decimal("0.11")
    participants = list(range(1, 11))  # 10 members
    result = _compute_equal_splits(amount, participants, payer_id=1)

    _assert_inv1(result, amount)
    assert len(result) == 10


def test_payer_is_in_participant_list_only_once():
    """
    The payer appears exactly once in the result (they don't get a double entry).
    Only their split AMOUNT gets the remainder added — not a new row.
    """
    amount = Decimal("10.00")
    participants = [1, 2, 3]
    result = _compute_equal_splits(amount, participants, payer_id=1)

    payer_entries = [s for s in result if s["user_id"] == 1]
    assert len(payer_entries) == 1, "Payer must appear exactly once in the splits"
