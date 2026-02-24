"""
tests/unit/test_split_sum_invariant.py — Unit tests for INV-1 enforcement via
                                          expense_service._validate_split_sum.

What this file proves (ARCHITECTURE.md Section 9 / Table row test_split_sum_invariant.py):
  - INV-1 check raises AppError(SPLIT_SUM_MISMATCH, 422) when sum != amount
  - INV-1 check passes silently when sum == amount exactly
  - The error has the correct code (SPLIT_SUM_MISMATCH), HTTP status (422), and field ("splits")
  - Decimal arithmetic is used — no float rounding errors can cause false positives or negatives
  - The check applies in both CREATE and EDIT paths (same function, tested for both contexts)
  - Tolerance is exactly zero — even a $0.01 discrepancy triggers the error

Unit test constraints (ARCHITECTURE.md Section 9 Level 1):
  - No database, no Flask, no auth context.
  - _validate_split_sum is a pure function: takes list[dict] and Decimal, returns None or raises.

GUIDE Rule 1 — INV-1 is non-negotiable. Code that bypasses it will be rejected.
GUIDE Rule 2 — All amounts are Decimal. Never float.
GUIDE Rule 5 — Error codes (SPLIT_SUM_MISMATCH) are used from errors.py only.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.app.errors import AppError, ErrorCode
from backend.app.services.expense_service import _validate_split_sum


# ── Helper ─────────────────────────────────────────────────────────────────

def _split(user_id: int, amount: str) -> dict:
    """Builds a split dict matching the format _validate_split_sum expects."""
    return {"user_id": user_id, "amount": Decimal(amount)}


# ── Happy path ─────────────────────────────────────────────────────────────

def test_exact_match_passes_silently():
    """
    INV-1 is satisfied: sum(splits) == expense.amount exactly.
    No exception should be raised.
    """
    splits = [_split(1, "50.00"), _split(2, "50.00")]
    # Should not raise
    _validate_split_sum(splits, expected_amount=Decimal("100.00"), group_id=1)


def test_single_split_full_amount_passes():
    """One split covering the full amount satisfies INV-1."""
    splits = [_split(1, "75.50")]
    _validate_split_sum(splits, expected_amount=Decimal("75.50"), group_id=1)


def test_three_way_exact_split_passes():
    """Three splits that sum to exactly $90.00."""
    splits = [_split(1, "30.00"), _split(2, "30.00"), _split(3, "30.00")]
    _validate_split_sum(splits, expected_amount=Decimal("90.00"), group_id=1)


def test_uneven_but_exact_splits_pass():
    """Unequal split amounts that still sum correctly."""
    splits = [_split(1, "60.00"), _split(2, "25.00"), _split(3, "15.00")]
    _validate_split_sum(splits, expected_amount=Decimal("100.00"), group_id=1)


def test_minimum_amount_single_cent_passes():
    """$0.01 split entirely to one participant."""
    splits = [_split(1, "0.01")]
    _validate_split_sum(splits, expected_amount=Decimal("0.01"), group_id=1)


def test_large_amount_passes():
    """$9999.99 split exactly between two people."""
    splits = [_split(1, "4999.99"), _split(2, "5000.00")]
    _validate_split_sum(splits, expected_amount=Decimal("9999.99"), group_id=1)


# ── Failure path ───────────────────────────────────────────────────────────

def test_sum_too_low_raises_split_sum_mismatch():
    """
    INV-1 violated: splits sum to $90, expense is $100.
    Must raise AppError with SPLIT_SUM_MISMATCH and status 422.
    """
    splits = [_split(1, "45.00"), _split(2, "45.00")]  # sum = 90.00

    with pytest.raises(AppError) as exc_info:
        _validate_split_sum(splits, expected_amount=Decimal("100.00"), group_id=1)

    err = exc_info.value
    assert err.code        == ErrorCode.SPLIT_SUM_MISMATCH
    assert err.http_status == 422


def test_sum_too_high_raises_split_sum_mismatch():
    """
    INV-1 violated: splits sum to $110, expense is $100.
    Over-allocation is equally invalid.
    """
    splits = [_split(1, "60.00"), _split(2, "50.00")]  # sum = 110.00

    with pytest.raises(AppError) as exc_info:
        _validate_split_sum(splits, expected_amount=Decimal("100.00"), group_id=1)

    err = exc_info.value
    assert err.code == ErrorCode.SPLIT_SUM_MISMATCH
    assert err.http_status == 422


def test_one_cent_discrepancy_raises():
    """
    INV-1 tolerance is exactly zero. Even a $0.01 discrepancy must be rejected.
    This is the "GUIDE Rule 1 — no rounding tolerance" test.
    """
    splits = [_split(1, "49.99"), _split(2, "50.00")]  # sum = 99.99, not 100.00

    with pytest.raises(AppError) as exc_info:
        _validate_split_sum(splits, expected_amount=Decimal("100.00"), group_id=1)

    assert exc_info.value.code == ErrorCode.SPLIT_SUM_MISMATCH


def test_error_field_is_splits():
    """
    ARCHITECTURE.md Section 8: field context tells the client which field failed.
    For SPLIT_SUM_MISMATCH the field must be "splits".
    """
    splits = [_split(1, "40.00")]  # sum = 40.00, not 100.00

    with pytest.raises(AppError) as exc_info:
        _validate_split_sum(splits, expected_amount=Decimal("100.00"), group_id=1)

    assert exc_info.value.field == "splits"


def test_empty_splits_raises_when_amount_nonzero():
    """
    An empty splits list sums to zero. Any nonzero expense amount triggers INV-1.
    """
    with pytest.raises(AppError) as exc_info:
        _validate_split_sum([], expected_amount=Decimal("50.00"), group_id=1)

    assert exc_info.value.code == ErrorCode.SPLIT_SUM_MISMATCH


def test_decimal_precision_no_float_false_positive():
    """
    GUIDE Rule 2: Decimal arithmetic must not produce false positives.
    float(10.1) + float(20.2) == 30.299999... (would fail incorrectly).
    Decimal("10.10") + Decimal("20.20") == Decimal("30.30") (exact).
    """
    splits = [_split(1, "10.10"), _split(2, "20.20")]
    expected = Decimal("30.30")

    # Must NOT raise — Decimal arithmetic is exact
    _validate_split_sum(splits, expected_amount=expected, group_id=1)


def test_decimal_precision_catches_float_style_error():
    """
    If floats were used: 10.1 + 20.2 = 30.299999... which != 30.30.
    With Decimal this is exact and passes. This test documents the contrast.

    We also test that a genuine Decimal mismatch (30.29 vs 30.30) still raises.
    """
    splits = [_split(1, "10.10"), _split(2, "20.19")]  # sum = 30.29, not 30.30

    with pytest.raises(AppError) as exc_info:
        _validate_split_sum(splits, expected_amount=Decimal("30.30"), group_id=1)

    assert exc_info.value.code == ErrorCode.SPLIT_SUM_MISMATCH


def test_error_message_contains_amounts():
    """
    The error message should be human-readable and include both the actual split
    sum and the expected amount, helping the client diagnose the problem.
    (ARCHITECTURE.md Section 8: messages are human-readable prose.)
    """
    splits = [_split(1, "40.00"), _split(2, "40.00")]  # sum = 80.00

    with pytest.raises(AppError) as exc_info:
        _validate_split_sum(splits, expected_amount=Decimal("100.00"), group_id=1)

    message = exc_info.value.message
    assert "80" in message or "80.00" in message, "Message should contain the actual split sum"
    assert "100" in message or "100.00" in message, "Message should contain the expected amount"


def test_inv1_enforced_for_create_path():
    """
    INV-1 applies on CREATE (spec Section 8.3).
    Simulate what create_expense does: validate before any DB write.
    """
    raw_splits_from_request = [
        {"user_id": 1, "amount": Decimal("30.00")},
        {"user_id": 2, "amount": Decimal("30.00")},
        # Missing $40 to reach $100
    ]

    with pytest.raises(AppError) as exc_info:
        _validate_split_sum(
            raw_splits_from_request,
            expected_amount=Decimal("100.00"),
            group_id=42,
        )

    assert exc_info.value.code == ErrorCode.SPLIT_SUM_MISMATCH
    assert exc_info.value.http_status == 422


def test_inv1_enforced_for_edit_path():
    """
    INV-1 applies on EDIT too (spec Section 7.2: "INV-1 re-validated atomically").
    Patching the amount without updating splits to match is an INV-1 violation.
    """
    # Old expense was $100 split equally. Client sends new amount=$120 but same splits.
    old_splits_not_updated = [
        {"user_id": 1, "amount": Decimal("50.00")},
        {"user_id": 2, "amount": Decimal("50.00")},
    ]

    with pytest.raises(AppError) as exc_info:
        _validate_split_sum(
            old_splits_not_updated,
            expected_amount=Decimal("120.00"),   # new amount — splits don't match
            group_id=7,
        )

    assert exc_info.value.code == ErrorCode.SPLIT_SUM_MISMATCH
    assert exc_info.value.field == "splits"
