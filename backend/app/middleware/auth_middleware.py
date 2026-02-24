"""
middleware/auth_middleware.py — JWT authentication decorator.

The @require_auth decorator:
  1. Reads the Authorization header (expected: "Bearer <token>")
  2. Decodes and verifies the JWT signature using HS256
  3. Checks token expiry
  4. Attaches user_id (int) to flask.g for the duration of the request
  5. Returns the appropriate 401 error if any step fails

Strict responsibility boundary (ARCHITECTURE.md Section 7, GUIDE Rule 3):
  - This middleware extracts the JWT and attaches user_id to flask.g ONLY.
  - It does NOT perform business authorization (group membership, ownership).
    That belongs in the service layer. Middleware = authentication (401).
    Service = authorization (403).
  - Services receive user_id as a plain integer argument, with no knowledge
    of JWT or HTTP headers.

Error codes:
  TOKEN_MISSING  (401) — no Authorization header
  TOKEN_INVALID  (401) — malformed header, invalid signature, or bad payload
  TOKEN_EXPIRED  (401) — valid token but exp claim is in the past
  → 403 FORBIDDEN is never raised here; it is raised by service functions.
"""

from __future__ import annotations

import functools
from typing import Callable

import jwt
from flask import current_app, g, request

from backend.app.errors import AppError, ErrorCode


def require_auth(f: Callable) -> Callable:
    """
    Route decorator that enforces JWT authentication.

    Attaches the authenticated user's ID to flask.g.user_id.
    Raises AppError for all auth failures — the global error handler converts
    these to the correct JSON response. Routes never catch AppError.

    Usage:
        @app.route("/api/v1/groups")
        @require_auth
        def list_groups():
            user_id = g.user_id  # always an int when this runs
            ...
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        _authenticate_request()
        return f(*args, **kwargs)

    return decorated


def _authenticate_request() -> None:
    """
    Performs the full JWT authentication sequence and sets flask.g.user_id.

    Separated from the decorator wrapper for testability — can be called
    directly in tests without wrapping a real view function.

    Raises AppError on any authentication failure (never returns a response
    directly — error propagates to the global Flask error handler).
    """
    auth_header = request.headers.get("Authorization", "")

    # ── Step 1: Require Authorization header ──────────────────────────────
    if not auth_header:
        raise AppError(
            ErrorCode.TOKEN_MISSING,
            "Authentication required. Provide a Bearer token in the Authorization header.",
            401,
        )

    # ── Step 2: Parse "Bearer <token>" format ─────────────────────────────
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AppError(
            ErrorCode.TOKEN_INVALID,
            "Authorization header must be in the format: Bearer <token>.",
            401,
        )

    raw_token = parts[1]

    # ── Step 3: Decode and verify the JWT ─────────────────────────────────
    try:
        payload = jwt.decode(
            raw_token,
            current_app.config["JWT_SECRET_KEY"],
            algorithms=[current_app.config.get("JWT_ALGORITHM", "HS256")],
        )
    except jwt.ExpiredSignatureError:
        # Token was valid but the exp claim has passed.
        # Client should use POST /auth/refresh.
        raise AppError(
            ErrorCode.TOKEN_EXPIRED,
            "The access token has expired. Use POST /auth/refresh to obtain a new one.",
            401,
        )
    except jwt.InvalidTokenError:
        # Covers: bad signature, malformed token, invalid claims, etc.
        raise AppError(
            ErrorCode.TOKEN_INVALID,
            "The access token is invalid or has been tampered with.",
            401,
        )

    # ── Step 4: Extract and validate the sub (user_id) claim ──────────────
    sub = payload.get("sub")
    if sub is None:
        raise AppError(
            ErrorCode.TOKEN_INVALID,
            "The access token is missing the required 'sub' claim.",
            401,
        )

    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise AppError(
            ErrorCode.TOKEN_INVALID,
            "The 'sub' claim in the access token is not a valid user ID.",
            401,
        )

    # ── Step 5: Attach user_id to flask.g ─────────────────────────────────
    # Services read g.user_id via the route which passes it as a plain int.
    # Services never import flask.g directly — they receive user_id as an arg.
    g.user_id = user_id
