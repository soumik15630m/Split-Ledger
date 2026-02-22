"""
schemas/expense_schema.py — Marshmallow schemas for expense endpoints.

Validation responsibility (per GUIDE Rule 4 and spec Section 11):
  - This file:
      - Field types, lengths, enum values, decimal precision (INV-7)
      - SPLITS_SENT_FOR_EQUAL_MODE (400) — request shape rule
      - DUPLICATE_SPLIT_USER       (400) — request shape rule
      - Splits required when split_mode='custom' (CREATE and PATCH)
      - PATCH co-presence rule: amount and splits must both be present
        (or both absent) when split_mode is not changing to 'equal'
      - Non-empty-after-trim enforcement for description
  - services/expense_service.py:
      - INV-1  (SPLIT_SUM_MISMATCH, 422) — requires Decimal arithmetic
      - INV-5  (PAYER_NOT_MEMBER, 422)   — requires DB membership lookup
      - INV-6  (SPLIT_USER_NOT_MEMBER, 422) — requires DB membership lookup
      - INV-8  (EXPENSE_DELETED, 422)    — requires DB record lookup
      - Edit permission (FORBIDDEN, 403) — requires DB record lookup

IMPORTANT: Inherits from marshmallow.Schema directly — never ma.Schema.
           See extensions.py for the full explanation.
"""

from __future__ import annotations

from decimal import Decimal

from marshmallow import (
    Schema,
    ValidationError,
    fields,
    validate,
    validates,
    validates_schema,
)

from app.errors import ErrorCode
from app.models.expense import Category, SplitMode


# ── Shared monetary amount validator ──────────────────────────────────────
#
# Used by SplitInputSchema, CreateExpenseSchema, and PatchExpenseSchema.
# Enforces INV-7 (spec Section 4): max 2 decimal places, strictly positive.
# Input with more than 2 decimal places is REJECTED with INVALID_AMOUNT_PRECISION
# — never rounded or truncated. This is the spec's explicit requirement.
#
# ARCHITECTURE.md Section 4 notes: "INV-7 — marshmallow schema is the
# enforcement point for precision."
# ──────────────────────────────────────────────────────────────────────────

def _validate_monetary_amount(value: Decimal) -> None:
    """
    Validates a monetary Decimal value per INV-7 rules:
      - Must be strictly greater than zero.
      - Must have at most 2 decimal places.

    The route error handler detects INVALID_AMOUNT_PRECISION by matching the
    raised ValidationError message to the known ErrorCode constant.
    """
    if value <= Decimal("0"):
        raise ValidationError("Amount must be greater than zero.")

    # Decimal.as_tuple().exponent gives the scale (number of decimal places
    # as a negative integer). For example:
    #   Decimal("10.123").as_tuple().exponent == -3  → 3 dp → REJECT
    #   Decimal("10.12").as_tuple().exponent  == -2  → 2 dp → accept
    #   Decimal("10").as_tuple().exponent     ==  0  → 0 dp → accept
    if value.as_tuple().exponent < -2:
        raise ValidationError(ErrorCode.INVALID_AMOUNT_PRECISION)


# ── Shared non-empty string validator ─────────────────────────────────────
#
# Spec Section 8.3: description — "Non-empty after trim, max 255 chars."
# validate.Length(min=1) alone allows whitespace-only strings like "   "
# because len("   ") == 3 > 0. This validator strips first then checks.
# ──────────────────────────────────────────────────────────────────────────

def _validate_non_empty_after_trim(value: str) -> None:
    """
    Raises ValidationError if the string is blank or contains only whitespace.
    Mirrors the DB CHECK(LENGTH(TRIM(...)) > 0) constraint at the API layer.
    GUIDE Rule 4: the schema is the primary gate; the DB constraint is the last resort.
    """
    if not value.strip():
        raise ValidationError("This field must not be blank or contain only whitespace.")


# ── Sub-schema: one entry in the `splits` array ───────────────────────────

class SplitInputSchema(Schema):
    """
    Schema for a single split object within the `splits` array of a
    CreateExpenseSchema or PatchExpenseSchema payload.

    Cross-entity rule (INV-6: user_id must be a group member) is checked
    in expense_service.py, not here.
    """

    user_id = fields.Int(
        required=True,
        strict=True,   # reject floats like 1.0
        validate=validate.Range(min=1, error="user_id must be a positive integer."),
    )

    # INV-7: Decimal, strictly positive, max 2 dp.
    amount = fields.Decimal(
        required=True,
        validate=_validate_monetary_amount,
    )


# ── Create expense ─────────────────────────────────────────────────────────

class CreateExpenseSchema(Schema):
    """
    POST /groups/:id/expenses  (spec Section 8.3)

    Split mode behaviour:
      - split_mode='equal'  → client must NOT send splits array.
                              Server computes equal splits (expense_service.py).
                              Returns SPLITS_SENT_FOR_EQUAL_MODE (400) if present.
      - split_mode='custom' → client MUST send splits array (required).
                              INV-1 sum check is in expense_service.py.

    Checks in this schema:
      - SPLITS_SENT_FOR_EQUAL_MODE: splits array present with split_mode='equal'
      - splits required when split_mode='custom' (spec Section 8.3)
      - DUPLICATE_SPLIT_USER: same user_id appears twice in splits array
      - description non-empty after trim

    Checks NOT in this schema (belong in service):
      - INV-1: sum(splits.amount) == amount          → expense_service.py
      - INV-5: paid_by_user_id is a group member     → expense_service.py
      - INV-6: every split.user_id is a group member → expense_service.py
    """

    # Spec: integer, required, must be a group member (INV-5 — checked in service).
    paid_by_user_id = fields.Int(
        required=True,
        strict=True,
        validate=validate.Range(min=1, error="paid_by_user_id must be a positive integer."),
    )

    # Spec: non-empty after trim, max 255 chars.
    description = fields.Str(
        required=True,
        validate=[
            validate.Length(
                min=1,
                max=255,
                error="Description must be between 1 and 255 characters.",
            ),
            _validate_non_empty_after_trim,
        ],
    )

    # INV-7: Decimal, strictly positive, max 2 dp.
    amount = fields.Decimal(
        required=True,
        validate=_validate_monetary_amount,
    )

    # Spec: default 'custom'. Validated against the SplitMode enum.
    # INVALID_SPLIT_MODE (400) returned if value is not in the enum.
    split_mode = fields.Enum(
        SplitMode,
        load_default=SplitMode.CUSTOM,
        by_value=True,
        error_messages={"unknown": ErrorCode.INVALID_SPLIT_MODE},
    )

    # Spec: default 'other'. Validated against the Category enum.
    # INVALID_CATEGORY (400) returned if value is not in the enum.
    category = fields.Enum(
        Category,
        load_default=Category.OTHER,
        by_value=True,
        error_messages={"unknown": ErrorCode.INVALID_CATEGORY},
    )

    # Required when split_mode='custom'; must be absent when split_mode='equal'.
    # Each entry is validated by SplitInputSchema.
    splits = fields.List(
        fields.Nested(SplitInputSchema),
        load_default=None,
    )

    @validates_schema
    def validate_splits_coherence(self, data: dict, **kwargs) -> None:
        """
        Schema-level cross-field checks for the splits array.

        1. SPLITS_SENT_FOR_EQUAL_MODE (400):
           Client sent a splits array when split_mode='equal'.
           Spec Section 8.3: "Client must NOT send a splits array in equal mode."

        2. splits required when split_mode='custom' (spec Section 8.3):
           Client must send a splits array when split_mode='custom'.

        3. DUPLICATE_SPLIT_USER (400):
           Same user_id appears more than once in the splits array.

        Note: INV-1 (sum check) and membership checks (INV-5, INV-6) are
        intentionally NOT checked here — they require Decimal arithmetic and
        DB lookups respectively. Both belong in expense_service.py.
        """
        split_mode = data.get("split_mode", SplitMode.CUSTOM)
        splits = data.get("splits")

        if split_mode == SplitMode.EQUAL:
            # Spec: client must NOT send splits in equal mode.
            if splits is not None:
                raise ValidationError(
                    {
                        "splits": [ErrorCode.SPLITS_SENT_FOR_EQUAL_MODE],
                    }
                )
        else:
            # Custom mode: splits array is required.
            if splits is None:
                raise ValidationError(
                    {
                        "splits": [
                            "splits is required when split_mode is 'custom'."
                        ],
                    }
                )

            # Custom mode: check for duplicate user_ids within the splits array.
            user_ids = [s["user_id"] for s in splits]
            if len(user_ids) != len(set(user_ids)):
                raise ValidationError(
                    {
                        "splits": [ErrorCode.DUPLICATE_SPLIT_USER],
                    }
                )


# ── Patch expense ──────────────────────────────────────────────────────────

class PatchExpenseSchema(Schema):
    """
    PATCH /expenses/:id  (spec Section 8.3, Section 7.2)

    All fields are optional. Only provided fields are updated.

    Partial update rules (spec Section 7.2):
      1. If amount OR splits are provided, BOTH must be present.
         (Server re-validates INV-1 atomically before any DB write.)
      2. If split_mode changes to 'equal':
           - Client must NOT send splits (server recomputes from scratch).
           - amount alone is accepted in this case.
      3. If split_mode changes to 'custom':
           - Client must send the new splits array.
           - amount must also be present (INV-1 re-validation).
      4. Cannot edit a deleted expense → EXPENSE_DELETED (422) — service check.
      5. Only original payer or group owner may edit → FORBIDDEN (403) — service.

    Schema checks here (rules 1–3 above are request-shape rules → 400):
      - SPLITS_SENT_FOR_EQUAL_MODE
      - splits required when split_mode changes to 'custom'
      - DUPLICATE_SPLIT_USER
      - Amount + splits co-presence when split_mode is not changing to 'equal'
      - description non-empty after trim

    Service checks (rules 4–5 require DB):
      - EXPENSE_DELETED  → expense_service.py
      - FORBIDDEN        → expense_service.py
      - INV-1            → expense_service.py
      - INV-5, INV-6     → expense_service.py
    """

    # All fields are optional (PATCH = partial update).
    paid_by_user_id = fields.Int(
        required=False,
        strict=True,
        validate=validate.Range(min=1, error="paid_by_user_id must be a positive integer."),
    )

    description = fields.Str(
        required=False,
        validate=[
            validate.Length(
                min=1,
                max=255,
                error="Description must be between 1 and 255 characters.",
            ),
            _validate_non_empty_after_trim,
        ],
    )

    # INV-7 still applies to PATCH amounts.
    amount = fields.Decimal(
        required=False,
        validate=_validate_monetary_amount,
    )

    split_mode = fields.Enum(
        SplitMode,
        required=False,
        by_value=True,
        error_messages={"unknown": ErrorCode.INVALID_SPLIT_MODE},
    )

    category = fields.Enum(
        Category,
        required=False,
        by_value=True,
        error_messages={"unknown": ErrorCode.INVALID_CATEGORY},
    )

    splits = fields.List(
        fields.Nested(SplitInputSchema),
        required=False,
    )

    @validates_schema
    def validate_patch_coherence(self, data: dict, **kwargs) -> None:
        """
        Enforces PATCH-specific request shape rules.

        These are all 400-level checks because they depend only on the shape
        of the request, not on DB state.

        Rule A — SPLITS_SENT_FOR_EQUAL_MODE:
            If split_mode is being changed to 'equal', splits must be absent.

        Rule B — splits required for 'custom':
            If split_mode is being changed to 'custom', splits must be present.
            Spec Section 7.2: "If split_mode changes to 'custom': client must
            send the new splits array."

        Rule C — DUPLICATE_SPLIT_USER:
            If a splits array is present, no user_id may appear twice.

        Rule D — Amount/splits co-presence:
            If split_mode is NOT being changed to 'equal', then amount and
            splits must be provided together or not at all.
            Rationale: the service re-validates INV-1 when either is touched;
            providing only one makes re-validation impossible.

        Exception for Rule D:
            When split_mode is changing TO 'equal', the client sends amount
            alone (no splits) — the server recomputes splits from scratch.
            This is spec-defined behaviour, not an exception to co-presence.
        """
        split_mode = data.get("split_mode")     # None if not provided in PATCH
        amount     = data.get("amount")          # None if not provided
        splits     = data.get("splits")          # None if not provided

        # ── Rule A: equal mode forbids a client-supplied splits array ──────
        if split_mode == SplitMode.EQUAL:
            if splits is not None:
                raise ValidationError(
                    {
                        "splits": [ErrorCode.SPLITS_SENT_FOR_EQUAL_MODE],
                    }
                )
            # amount alone is valid when switching to equal — fall through.
            return

        # ── Rule B: custom mode requires splits array ──────────────────────
        # Spec Section 7.2: "If split_mode changes to 'custom': client must
        # send the new splits array."
        if split_mode == SplitMode.CUSTOM and splits is None:
            raise ValidationError(
                {
                    "splits": [
                        "splits must be provided when split_mode is 'custom'."
                    ],
                }
            )

        # ── Rule C: no duplicate user_ids in the splits array ─────────────
        if splits is not None:
            user_ids = [s["user_id"] for s in splits]
            if len(user_ids) != len(set(user_ids)):
                raise ValidationError(
                    {
                        "splits": [ErrorCode.DUPLICATE_SPLIT_USER],
                    }
                )

        # ── Rule D: amount and splits must be provided together ────────────
        # Exception: if split_mode is changing to 'equal', amount alone is OK
        # (handled by the early return above). We only apply co-presence when
        # split_mode is either absent (no change) or explicitly set to 'custom'.
        amount_provided = amount is not None
        splits_provided = splits is not None

        if amount_provided and not splits_provided:
            raise ValidationError(
                {
                    "splits": [
                        "splits must be provided when amount is being updated."
                    ],
                }
            )

        if splits_provided and not amount_provided:
            raise ValidationError(
                {
                    "amount": [
                        "amount must be provided when splits are being updated."
                    ],
                }
            )
