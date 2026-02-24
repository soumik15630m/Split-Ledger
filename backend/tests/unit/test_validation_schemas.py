"""
tests/unit/test_validation_schemas.py — Unit tests for all marshmallow schemas.

What this file proves (ARCHITECTURE.md Section 9 / Table row test_validation_schemas.py):
  - Every schema accepts valid input without raising
  - Every schema rejects invalid input with the correct ValidationError
  - Field-level rules (type, length, enum, decimal precision) are enforced by schemas
  - Cross-entity rules (membership, INV-1) are NOT tested here — they belong in services
  - All error codes raised match the registered constants in errors.py (GUIDE Rule 5)

Unit test constraints (ARCHITECTURE.md Section 9 Level 1):
  - No database. Schemas must not call the DB (GUIDE Rule 4 — validation in schemas only).
  - No Flask application context.
    Schemas inherit from marshmallow.Schema directly (not ma.Schema) — this is precisely
    why they can be instantiated without an app context (extensions.py note).
  - No auth context.

GUIDE Rule 4 — Field rules live in schemas. Cross-entity rules live in services.
GUIDE Rule 2 — Monetary amounts: Decimal. The schemas use fields.Decimal() which
               returns Decimal objects — this is verified in the amount tests.
GUIDE Rule 5 — Error codes used in schema ValidationErrors must match errors.py constants.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from marshmallow import ValidationError

# Schemas under test
from backend.app.schemas.auth_schema import LoginSchema, RefreshTokenSchema, RegisterSchema
from backend.app.schemas.expense_schema import (
    CreateExpenseSchema,
    PatchExpenseSchema,
    SplitInputSchema,
)
from backend.app.schemas.group_schema import AddMemberSchema, CreateGroupSchema
from backend.app.schemas.settlement_schema import CreateSettlementSchema

# Error codes — used to assert exact code strings
from backend.app.errors import ErrorCode


# ═══════════════════════════════════════════════════════════════════════════
# RegisterSchema
# ═══════════════════════════════════════════════════════════════════════════

class TestRegisterSchema:

    def _load(self, data: dict):
        return RegisterSchema().load(data)

    def test_valid_payload(self):
        result = self._load({
            "username": "alice_99",
            "email": "alice@example.com",
            "password": "Secure1!",
        })
        assert result["username"] == "alice_99"
        assert result["email"]    == "alice@example.com"

    def test_username_too_short_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"username": "ab", "email": "a@b.com", "password": "Secure1!"})
        assert "username" in exc.value.messages

    def test_username_too_long_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"username": "a" * 51, "email": "a@b.com", "password": "Secure1!"})
        assert "username" in exc.value.messages

    def test_username_invalid_chars_raises(self):
        """Spec: alphanumeric + underscore only."""
        with pytest.raises(ValidationError) as exc:
            self._load({"username": "alice!", "email": "a@b.com", "password": "Secure1!"})
        assert "username" in exc.value.messages

    def test_username_spaces_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"username": "alice smith", "email": "a@b.com", "password": "Secure1!"})
        assert "username" in exc.value.messages

    def test_username_exactly_3_chars_passes(self):
        """Boundary: min 3 chars."""
        result = self._load({"username": "abc", "email": "a@b.com", "password": "Secure1!"})
        assert result["username"] == "abc"

    def test_username_exactly_50_chars_passes(self):
        """Boundary: max 50 chars."""
        name = "a" * 50
        result = self._load({"username": name, "email": "a@b.com", "password": "Secure1!"})
        assert result["username"] == name

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"username": "alice", "email": "notanemail", "password": "Secure1!"})
        assert "email" in exc.value.messages

    def test_password_too_short_raises(self):
        """Spec: min 8 chars."""
        with pytest.raises(ValidationError) as exc:
            self._load({"username": "alice", "email": "a@b.com", "password": "Ab1!"})
        assert "password" in exc.value.messages

    def test_password_no_letter_raises(self):
        """Spec: at least one letter."""
        with pytest.raises(ValidationError) as exc:
            self._load({"username": "alice", "email": "a@b.com", "password": "12345678"})
        assert "password" in exc.value.messages

    def test_password_no_digit_raises(self):
        """Spec: at least one digit."""
        with pytest.raises(ValidationError) as exc:
            self._load({"username": "alice", "email": "a@b.com", "password": "password"})
        assert "password" in exc.value.messages

    def test_password_exactly_8_chars_passes(self):
        """Boundary: min 8 chars, 1 letter + 1 digit."""
        result = self._load({"username": "alice", "email": "a@b.com", "password": "Passw0rd"})
        assert "password" in result

    def test_missing_username_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"email": "a@b.com", "password": "Secure1!"})
        assert "username" in exc.value.messages

    def test_missing_email_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"username": "alice", "password": "Secure1!"})
        assert "email" in exc.value.messages

    def test_missing_password_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"username": "alice", "email": "a@b.com"})
        assert "password" in exc.value.messages


# ═══════════════════════════════════════════════════════════════════════════
# LoginSchema
# ═══════════════════════════════════════════════════════════════════════════

class TestLoginSchema:

    def _load(self, data: dict):
        return LoginSchema().load(data)

    def test_valid_payload(self):
        result = self._load({"username": "alice", "password": "any_password"})
        assert result["username"] == "alice"

    def test_missing_username_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"password": "pass"})
        assert "username" in exc.value.messages

    def test_missing_password_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"username": "alice"})
        assert "password" in exc.value.messages

    def test_empty_payload_raises(self):
        with pytest.raises(ValidationError):
            self._load({})


# ═══════════════════════════════════════════════════════════════════════════
# RefreshTokenSchema
# ═══════════════════════════════════════════════════════════════════════════

class TestRefreshTokenSchema:

    def _load(self, data: dict):
        return RefreshTokenSchema().load(data)

    def test_valid_payload(self):
        result = self._load({"refresh_token": "abc123tokenstring"})
        assert result["refresh_token"] == "abc123tokenstring"

    def test_missing_refresh_token_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({})
        assert "refresh_token" in exc.value.messages


# ═══════════════════════════════════════════════════════════════════════════
# CreateGroupSchema
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateGroupSchema:

    def _load(self, data: dict):
        return CreateGroupSchema().load(data)

    def test_valid_name(self):
        result = self._load({"name": "Weekend Trip"})
        assert result["name"] == "Weekend Trip"

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({})
        assert "name" in exc.value.messages

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"name": ""})
        assert "name" in exc.value.messages

    def test_whitespace_only_raises(self):
        """Mirrors DB CHECK(LENGTH(TRIM(name)) > 0). Schema is the primary gate."""
        with pytest.raises(ValidationError) as exc:
            self._load({"name": "   "})
        assert "name" in exc.value.messages

    def test_name_exactly_100_chars_passes(self):
        """Boundary: max 100 chars."""
        result = self._load({"name": "a" * 100})
        assert len(result["name"]) == 100

    def test_name_101_chars_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"name": "a" * 101})
        assert "name" in exc.value.messages


# ═══════════════════════════════════════════════════════════════════════════
# AddMemberSchema
# ═══════════════════════════════════════════════════════════════════════════

class TestAddMemberSchema:

    def _load(self, data: dict):
        return AddMemberSchema().load(data)

    def test_valid_user_id(self):
        result = self._load({"user_id": 42})
        assert result["user_id"] == 42

    def test_missing_user_id_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({})
        assert "user_id" in exc.value.messages

    def test_zero_user_id_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"user_id": 0})
        assert "user_id" in exc.value.messages

    def test_negative_user_id_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"user_id": -1})
        assert "user_id" in exc.value.messages

    def test_float_user_id_raises(self):
        """strict=True rejects 1.0 even though it equals int 1."""
        with pytest.raises(ValidationError) as exc:
            self._load({"user_id": 1.0})
        assert "user_id" in exc.value.messages

    def test_string_user_id_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"user_id": "abc"})
        assert "user_id" in exc.value.messages


# ═══════════════════════════════════════════════════════════════════════════
# SplitInputSchema
# ═══════════════════════════════════════════════════════════════════════════

class TestSplitInputSchema:

    def _load(self, data: dict):
        return SplitInputSchema().load(data)

    def test_valid_split(self):
        result = self._load({"user_id": 1, "amount": "50.00"})
        assert result["user_id"] == 1
        assert result["amount"]  == Decimal("50.00")

    def test_amount_is_decimal_type(self):
        """GUIDE Rule 2: schema must return Decimal, not float."""
        result = self._load({"user_id": 1, "amount": "33.33"})
        assert isinstance(result["amount"], Decimal)

    def test_zero_amount_raises(self):
        """INV-7: amount must be > 0."""
        with pytest.raises(ValidationError) as exc:
            self._load({"user_id": 1, "amount": "0.00"})
        assert "amount" in exc.value.messages

    def test_negative_amount_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"user_id": 1, "amount": "-10.00"})
        assert "amount" in exc.value.messages

    def test_too_many_decimal_places_raises(self):
        """INV-7: max 2 decimal places. 3 dp is REJECTED, not rounded."""
        with pytest.raises(ValidationError) as exc:
            self._load({"user_id": 1, "amount": "10.123"})
        # The message should be the INVALID_AMOUNT_PRECISION error code
        errors = exc.value.messages.get("amount", [])
        assert ErrorCode.INVALID_AMOUNT_PRECISION in errors

    def test_missing_user_id_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"amount": "10.00"})
        assert "user_id" in exc.value.messages

    def test_missing_amount_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"user_id": 1})
        assert "amount" in exc.value.messages


# ═══════════════════════════════════════════════════════════════════════════
# CreateExpenseSchema
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateExpenseSchema:

    def _load(self, data: dict):
        return CreateExpenseSchema().load(data)

    # ── Happy path ─────────────────────────────────────────────────────────

    def test_valid_custom_mode(self):
        result = self._load({
            "paid_by_user_id": 1,
            "description": "Dinner",
            "amount": "100.00",
            "split_mode": "custom",
            "splits": [
                {"user_id": 1, "amount": "60.00"},
                {"user_id": 2, "amount": "40.00"},
            ],
        })
        assert result["amount"] == Decimal("100.00")
        assert result["split_mode"].value == "custom"

    def test_valid_equal_mode_no_splits(self):
        """Equal mode: splits must be absent. Schema allows it."""
        result = self._load({
            "paid_by_user_id": 1,
            "description": "Groceries",
            "amount": "60.00",
            "split_mode": "equal",
        })
        assert result["split_mode"].value == "equal"
        assert result.get("splits") is None

    def test_default_split_mode_is_custom(self):
        """Spec: split_mode defaults to 'custom'."""
        result = self._load({
            "paid_by_user_id": 1,
            "description": "Test",
            "amount": "10.00",
            "splits": [{"user_id": 1, "amount": "10.00"}],
        })
        assert result["split_mode"].value == "custom"

    def test_default_category_is_other(self):
        """Spec: category defaults to 'other'."""
        result = self._load({
            "paid_by_user_id": 1,
            "description": "Test",
            "amount": "10.00",
            "split_mode": "equal",
        })
        assert result["category"].value == "other"

    def test_all_valid_categories_pass(self):
        """All six enum values must be accepted."""
        for cat in ("food", "transport", "accommodation", "entertainment", "utilities", "other"):
            result = self._load({
                "paid_by_user_id": 1,
                "description": "Test",
                "amount": "10.00",
                "split_mode": "equal",
                "category": cat,
            })
            assert result["category"].value == cat

    # ── Failure paths ──────────────────────────────────────────────────────

    def test_splits_with_equal_mode_raises(self):
        """SPLITS_SENT_FOR_EQUAL_MODE (400): client sent splits in equal mode."""
        with pytest.raises(ValidationError) as exc:
            self._load({
                "paid_by_user_id": 1,
                "description": "Test",
                "amount": "100.00",
                "split_mode": "equal",
                "splits": [{"user_id": 1, "amount": "100.00"}],
            })
        # Should appear in _schema or splits field
        messages = exc.value.messages
        splits_errors = messages.get("splits", [])
        assert ErrorCode.SPLITS_SENT_FOR_EQUAL_MODE in splits_errors

    def test_missing_splits_in_custom_mode_raises(self):
        """Custom mode requires splits array."""
        with pytest.raises(ValidationError) as exc:
            self._load({
                "paid_by_user_id": 1,
                "description": "Test",
                "amount": "100.00",
                "split_mode": "custom",
            })
        assert "splits" in exc.value.messages

    def test_duplicate_split_user_raises(self):
        """DUPLICATE_SPLIT_USER (400): same user_id appears twice."""
        with pytest.raises(ValidationError) as exc:
            self._load({
                "paid_by_user_id": 1,
                "description": "Test",
                "amount": "100.00",
                "split_mode": "custom",
                "splits": [
                    {"user_id": 1, "amount": "50.00"},
                    {"user_id": 1, "amount": "50.00"},  # duplicate
                ],
            })
        errors = exc.value.messages.get("splits", [])
        assert ErrorCode.DUPLICATE_SPLIT_USER in errors

    def test_invalid_split_mode_raises(self):
        """INVALID_SPLIT_MODE (400): value not in ('equal', 'custom')."""
        with pytest.raises(ValidationError) as exc:
            self._load({
                "paid_by_user_id": 1,
                "description": "Test",
                "amount": "100.00",
                "split_mode": "percentage",
            })
        assert "split_mode" in exc.value.messages

    def test_invalid_category_raises(self):
        """INVALID_CATEGORY (400): value not in the allowed enum."""
        with pytest.raises(ValidationError) as exc:
            self._load({
                "paid_by_user_id": 1,
                "description": "Test",
                "amount": "100.00",
                "split_mode": "equal",
                "category": "luxury",
            })
        assert "category" in exc.value.messages

    def test_amount_three_decimal_places_raises(self):
        """INV-7: more than 2 decimal places → INVALID_AMOUNT_PRECISION (400)."""
        with pytest.raises(ValidationError) as exc:
            self._load({
                "paid_by_user_id": 1,
                "description": "Test",
                "amount": "10.001",
                "split_mode": "equal",
            })
        assert "amount" in exc.value.messages

    def test_amount_zero_raises(self):
        """INV-7: amount must be > 0."""
        with pytest.raises(ValidationError) as exc:
            self._load({
                "paid_by_user_id": 1,
                "description": "Test",
                "amount": "0.00",
                "split_mode": "equal",
            })
        assert "amount" in exc.value.messages

    def test_description_whitespace_only_raises(self):
        """Spec: non-empty after trim."""
        with pytest.raises(ValidationError) as exc:
            self._load({
                "paid_by_user_id": 1,
                "description": "    ",
                "amount": "10.00",
                "split_mode": "equal",
            })
        assert "description" in exc.value.messages

    def test_description_too_long_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({
                "paid_by_user_id": 1,
                "description": "x" * 256,
                "amount": "10.00",
                "split_mode": "equal",
            })
        assert "description" in exc.value.messages

    def test_missing_required_fields_raise(self):
        with pytest.raises(ValidationError):
            self._load({})

    def test_amount_returned_as_decimal(self):
        """GUIDE Rule 2: loaded amount must be Decimal, not float or string."""
        result = self._load({
            "paid_by_user_id": 1,
            "description": "Test",
            "amount": "55.50",
            "split_mode": "equal",
        })
        assert isinstance(result["amount"], Decimal)


# ═══════════════════════════════════════════════════════════════════════════
# PatchExpenseSchema
# ═══════════════════════════════════════════════════════════════════════════

class TestPatchExpenseSchema:

    def _load(self, data: dict):
        return PatchExpenseSchema().load(data)

    # ── Rule A: equal mode forbids splits ──────────────────────────────────

    def test_rule_a_equal_mode_with_splits_raises(self):
        """SPLITS_SENT_FOR_EQUAL_MODE: split_mode=equal + splits array → 400."""
        with pytest.raises(ValidationError) as exc:
            self._load({
                "split_mode": "equal",
                "splits": [{"user_id": 1, "amount": "50.00"}],
            })
        errors = exc.value.messages.get("splits", [])
        assert ErrorCode.SPLITS_SENT_FOR_EQUAL_MODE in errors

    def test_rule_a_equal_mode_with_amount_only_passes(self):
        """split_mode=equal + amount only is valid (server recomputes splits)."""
        result = self._load({"split_mode": "equal", "amount": "100.00"})
        assert result["split_mode"].value == "equal"

    # ── Rule B: custom mode requires splits ───────────────────────────────

    def test_rule_b_custom_mode_without_splits_raises(self):
        """split_mode=custom without splits → 400."""
        with pytest.raises(ValidationError) as exc:
            self._load({"split_mode": "custom"})
        assert "splits" in exc.value.messages

    def test_rule_b_custom_mode_with_splits_passes(self):
        """split_mode=custom with splits array is valid."""
        result = self._load({
            "split_mode": "custom",
            "amount": "100.00",
            "splits": [
                {"user_id": 1, "amount": "50.00"},
                {"user_id": 2, "amount": "50.00"},
            ],
        })
        assert result["split_mode"].value == "custom"

    # ── Rule C: duplicate split users ─────────────────────────────────────

    def test_rule_c_duplicate_split_user_raises(self):
        """DUPLICATE_SPLIT_USER: same user_id in splits twice."""
        with pytest.raises(ValidationError) as exc:
            self._load({
                "amount": "100.00",
                "splits": [
                    {"user_id": 1, "amount": "50.00"},
                    {"user_id": 1, "amount": "50.00"},
                ],
            })
        errors = exc.value.messages.get("splits", [])
        assert ErrorCode.DUPLICATE_SPLIT_USER in errors

    # ── Rule D: amount and splits co-presence ─────────────────────────────

    def test_rule_d_amount_without_splits_raises(self):
        """Amount provided, splits absent → 400 (co-presence violation)."""
        with pytest.raises(ValidationError) as exc:
            self._load({"amount": "100.00"})
        assert "splits" in exc.value.messages

    def test_rule_d_splits_without_amount_raises(self):
        """Splits provided, amount absent → 400 (co-presence violation)."""
        with pytest.raises(ValidationError) as exc:
            self._load({
                "splits": [{"user_id": 1, "amount": "50.00"}]
            })
        assert "amount" in exc.value.messages

    def test_description_only_patch_passes(self):
        """Updating only description is valid — no amount/splits re-validation needed."""
        result = self._load({"description": "Updated description"})
        assert result["description"] == "Updated description"

    def test_category_only_patch_passes(self):
        """Category-only update is valid."""
        result = self._load({"category": "food"})
        assert result["category"].value == "food"

    def test_empty_patch_passes(self):
        """Empty PATCH body is technically valid at schema level (service may no-op)."""
        result = self._load({})
        assert result == {}

    def test_amount_returned_as_decimal_in_patch(self):
        """GUIDE Rule 2: PATCH amounts must be Decimal."""
        result = self._load({
            "amount": "75.25",
            "splits": [
                {"user_id": 1, "amount": "50.00"},
                {"user_id": 2, "amount": "25.25"},
            ],
        })
        assert isinstance(result["amount"], Decimal)


# ═══════════════════════════════════════════════════════════════════════════
# CreateSettlementSchema
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateSettlementSchema:

    def _load(self, data: dict):
        return CreateSettlementSchema().load(data)

    def test_valid_payload(self):
        result = self._load({"paid_to_user_id": 2, "amount": "50.00"})
        assert result["paid_to_user_id"] == 2
        assert result["amount"]          == Decimal("50.00")

    def test_amount_is_decimal(self):
        """GUIDE Rule 2: settlement amount must be Decimal."""
        result = self._load({"paid_to_user_id": 2, "amount": "10.00"})
        assert isinstance(result["amount"], Decimal)

    def test_zero_amount_raises(self):
        """INV-7: amount must be > 0."""
        with pytest.raises(ValidationError) as exc:
            self._load({"paid_to_user_id": 2, "amount": "0.00"})
        assert "amount" in exc.value.messages

    def test_negative_amount_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"paid_to_user_id": 2, "amount": "-5.00"})
        assert "amount" in exc.value.messages

    def test_too_many_decimal_places_raises(self):
        """INV-7: max 2 decimal places."""
        with pytest.raises(ValidationError) as exc:
            self._load({"paid_to_user_id": 2, "amount": "10.001"})
        errors = exc.value.messages.get("amount", [])
        assert ErrorCode.INVALID_AMOUNT_PRECISION in errors

    def test_zero_paid_to_user_id_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"paid_to_user_id": 0, "amount": "10.00"})
        assert "paid_to_user_id" in exc.value.messages

    def test_negative_paid_to_user_id_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"paid_to_user_id": -1, "amount": "10.00"})
        assert "paid_to_user_id" in exc.value.messages

    def test_float_paid_to_user_id_raises(self):
        """strict=True: reject floats like 1.0."""
        with pytest.raises(ValidationError) as exc:
            self._load({"paid_to_user_id": 2.0, "amount": "10.00"})
        assert "paid_to_user_id" in exc.value.messages

    def test_missing_paid_to_user_id_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"amount": "10.00"})
        assert "paid_to_user_id" in exc.value.messages

    def test_missing_amount_raises(self):
        with pytest.raises(ValidationError) as exc:
            self._load({"paid_to_user_id": 2})
        assert "amount" in exc.value.messages

    def test_self_settlement_not_blocked_by_schema(self):
        """
        INV-4 (SELF_SETTLEMENT) is NOT enforced here — schema has no knowledge of
        the caller's user_id (which comes from flask.g). The service enforces it.
        GUIDE Rule 4: cross-entity checks belong in services, not schemas.
        A payload with paid_to_user_id == 1 must pass schema validation.
        """
        # paid_to_user_id=1, and if caller were user 1, that's a self-settlement —
        # but the schema cannot know the caller's id.
        result = self._load({"paid_to_user_id": 1, "amount": "20.00"})
        assert result["paid_to_user_id"] == 1  # schema passes, service will reject
