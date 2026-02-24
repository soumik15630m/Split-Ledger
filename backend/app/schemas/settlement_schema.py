"""
schemas/settlement_schema.py — Marshmallow schema for settlement endpoints.

Validation responsibility (per GUIDE Rule 4 and spec Section 11):
  - This file: field types, decimal precision (INV-7), positive amount.
  - services/settlement_service.py:
      - INV-4  (SELF_SETTLEMENT, 422)       — paid_by == paid_to check,
                                               requires the caller's user_id
                                               from flask.g (HTTP context);
                                               service receives it as argument.
      - INV-3  (OVERPAYMENT warning, 201)   — requires current balance lookup.
      - INV-5  (PAYER_NOT_MEMBER, 422)      — requires DB membership lookup.
      - RECIPIENT_NOT_MEMBER (422)          — requires DB membership lookup.
      - GROUP_NOT_FOUND (404)               — requires DB lookup.
      - USER_NOT_FOUND  (404)               — requires DB lookup.

IMPORTANT: Inherits from marshmallow.Schema directly — never ma.Schema.
           See extensions.py for the full explanation.
"""

from __future__ import annotations

from decimal import Decimal

from marshmallow import Schema, ValidationError, fields, validate

from backend.app.errors import ErrorCode


# ── Shared monetary amount validator ──────────────────────────────────────
#
# Identical logic to the validator in expense_schema.py. Defined here
# rather than imported from expense_schema to keep each schema file
# self-contained (importing from a sibling schema creates coupling and
# makes unit testing harder to isolate).
# ──────────────────────────────────────────────────────────────────────────

def _validate_monetary_amount(value: Decimal) -> None:
    """
    Validates a monetary Decimal value per INV-7 (spec Section 4):
      - Must be strictly greater than zero.
      - Must have at most 2 decimal places.

    Input with more than 2 decimal places is REJECTED (INVALID_AMOUNT_PRECISION)
    — never rounded. This matches the spec's explicit rule and the DB column
    type NUMERIC(12, 2).
    """
    if value <= Decimal("0"):
        raise ValidationError("Amount must be greater than zero.")

    # Decimal.as_tuple().exponent gives the scale as a negative integer.
    # e.g. Decimal("10.123").as_tuple().exponent == -3 → 3 dp → REJECT
    # e.g. Decimal("10.12").as_tuple().exponent  == -2 → 2 dp → accept
    if value.as_tuple().exponent < -2:
        raise ValidationError(ErrorCode.INVALID_AMOUNT_PRECISION)


# ── Schema ─────────────────────────────────────────────────────────────────

class CreateSettlementSchema(Schema):
    """
    POST /groups/:id/settlements  (spec Section 8.5)

    Records a direct debt payment from the authenticated user (paid_by,
    taken from flask.g.user_id in the route — not from the request body)
    to another group member.

    Field rules:
      paid_to_user_id : required, positive integer
                        Whether this user exists and is a member of the group
                        is checked in settlement_service.py (not here).
      amount          : required, positive Decimal, max 2 decimal places (INV-7)
                        Overpayment (INV-3) is allowed — service issues a warning
                        but does NOT block the request.

    Note on self-settlement (INV-4):
      The paid_by_user_id comes from flask.g (auth context), which is not
      available in schemas. Therefore the INV-4 check (paid_by != paid_to)
      is performed in settlement_service.py, which receives both user IDs
      as plain integer arguments. See GUIDE Rule 3 — schemas have no knowledge
      of Flask, g, or HTTP context.
    """

    # Must be a positive integer. Existence and membership are DB concerns.
    paid_to_user_id = fields.Int(
        required=True,
        strict=True,   # reject floats like 1.0 — integers only
        validate=validate.Range(
            min=1,
            error="paid_to_user_id must be a positive integer.",
        ),
    )

    # INV-7: Decimal, strictly positive, max 2 dp.
    # INV-3: Overpayment is valid — not checked here.
    amount = fields.Decimal(
        required=True,
        validate=_validate_monetary_amount,
    )