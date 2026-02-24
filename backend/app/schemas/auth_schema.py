"""
schemas/auth_schema.py — Marshmallow schemas for authentication endpoints.

Validation responsibility (per GUIDE Rule 4 and spec Section 11):
  - This file: field types, lengths, formats, regex patterns.
  - services/auth_service.py: DUPLICATE_EMAIL / DUPLICATE_USERNAME checks
    (cross-entity: require a DB lookup — not a schema concern).

IMPORTANT: All schemas inherit from marshmallow.Schema directly.
           Do NOT use ma.Schema — it requires an active Flask app context
           and breaks unit tests. See extensions.py for the full explanation.
"""

from __future__ import annotations

import re

from marshmallow import Schema, ValidationError, fields, validates, validate

from backend.app.errors import ErrorCode


class RegisterSchema(Schema):
    """
    POST /auth/register

    Field rules (spec Section 8.1):
      username : 3–50 chars, alphanumeric + underscore only
      email    : valid email format (RFC-compatible local check)
      password : min 8 chars, at least one letter and one digit

    Cross-entity rules (uniqueness checks) are enforced in auth_service.py,
    not here, because they require a DB query.
    """

    # Spec: VARCHAR(50) NOT NULL UNIQUE, alphanumeric + underscore, 3–50 chars.
    username = fields.Str(
        required=True,
        validate=[
            validate.Length(
                min=3,
                max=50,
                error="Username must be between 3 and 50 characters.",
            ),
            validate.Regexp(
                r"^[a-zA-Z0-9_]+$",
                error="Username may only contain letters, numbers, and underscores.",
            ),
        ],
    )

    # Spec: VARCHAR(255) NOT NULL UNIQUE, valid email format.
    # marshmallow's Email field applies RFC-5322-compatible validation.
    email = fields.Email(
        required=True,
        validate=validate.Length(max=255),
    )

    # Spec: min 8 chars, at least one letter and one digit.
    # Validated in @validates below to produce a clear message per missing rule.
    password = fields.Str(required=True, load_only=True)

    @validates("password")
    def validate_password_strength(self, value: str) -> None:
        """
        Spec Section 8.1: password — Required, min 8 chars,
        at least one letter and one digit.
        """
        if len(value) < 8:
            raise ValidationError("Password must be at least 8 characters long.")
        if not any(c.isalpha() for c in value):
            raise ValidationError("Password must contain at least one letter.")
        if not any(c.isdigit() for c in value):
            raise ValidationError("Password must contain at least one digit.")


class LoginSchema(Schema):
    """
    POST /auth/login

    Accepts username (not email) + password. Credential correctness
    is checked in auth_service.py (INVALID_CREDENTIALS, 401).
    """

    username = fields.Str(required=True)
    password = fields.Str(required=True, load_only=True)


class RefreshTokenSchema(Schema):
    """
    POST /auth/refresh

    Expects the raw refresh token string in the request body.
    Token validity (revoked, expired, not found) is checked in
    auth_service.py (REFRESH_TOKEN_INVALID, 401).
    """

    refresh_token = fields.Str(required=True)