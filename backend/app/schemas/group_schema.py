"""
schemas/group_schema.py — Marshmallow schemas for group and membership endpoints.

Validation responsibility (per GUIDE Rule 4 and spec Section 11):
  - This file: field types, string lengths, non-empty checks (including trim).
  - services/group_service.py:
      - INV-9 (caller must be a member to read/write group data)
      - USER_NOT_FOUND (user_id existence check requires DB lookup)
      - ALREADY_MEMBER  (membership existence check requires DB lookup)
      - GROUP_NOT_FOUND (requires DB lookup)

IMPORTANT: Inherits from marshmallow.Schema directly — never ma.Schema.
           See extensions.py for the full explanation.
"""

from __future__ import annotations

from marshmallow import Schema, ValidationError, fields, validate, validates


# ── Shared non-empty string validator ─────────────────────────────────────
#
# Spec Section 8.2: group name — "Non-empty after trim, max 100 chars."
# validate.Length(min=1) alone allows whitespace-only strings like "   "
# because len("   ") == 3 > 0. This validator strips first then checks,
# mirroring the DB CHECK(LENGTH(TRIM(name)) > 0) at the API layer.
# GUIDE Rule 4: the schema is the primary gate; the DB constraint is the last resort.
# ──────────────────────────────────────────────────────────────────────────

def _validate_non_empty_after_trim(value: str) -> None:
    """
    Raises ValidationError if the string is blank or contains only whitespace.
    Mirrors the DB CHECK(LENGTH(TRIM(...)) > 0) constraint at the API layer.
    """
    if not value.strip():
        raise ValidationError("This field must not be blank or contain only whitespace.")


class CreateGroupSchema(Schema):
    """
    POST /groups

    Spec Section 8.2: name — non-empty after trim, max 100 chars.

    The DB schema has CHECK(LENGTH(TRIM(name)) > 0). This schema enforces
    the same rule at the API layer so bad input is rejected before the service
    is called. Both layers are intentional (defence-in-depth), but the schema
    is the primary gate — the DB constraint is the last resort.
    """

    # Spec: VARCHAR(100) NOT NULL CHECK(LENGTH(TRIM(name)) > 0)
    name = fields.Str(
        required=True,
        validate=[
            validate.Length(
                min=1,
                max=100,
                error="Group name must be between 1 and 100 characters.",
            ),
            _validate_non_empty_after_trim,
        ],
    )


class AddMemberSchema(Schema):
    """
    POST /groups/:id/members

    Spec Section 8.2: add user to group (owner only).
    Only the user_id field is accepted; the service enforces ownership
    (INV-9) and existence checks.
    """

    # Must be a positive integer. Whether the user exists is a DB concern
    # (USER_NOT_FOUND, 404) — checked in group_service.py.
    user_id = fields.Int(
        required=True,
        strict=True,  # reject floats like 1.0 — integers only
        validate=validate.Range(
            min=1,
            error="user_id must be a positive integer.",
        ),
    )