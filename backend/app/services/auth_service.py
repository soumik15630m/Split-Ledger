"""
services/auth_service.py — Authentication business logic.

Responsibilities:
  - User registration and credential validation
  - JWT access token creation (HS256)
  - Refresh token lifecycle (creation, validation, revocation)
  - Password hashing (bcrypt) and verification

Layer rules (GUIDE Rule 3):
  - No imports from routes or schemas
  - No use of flask.request, flask.g, or HTTP status codes
  - current_app.config is used ONLY to read JWT_SECRET_KEY and JWT expiry —
    this is the single Flask dependency in this service, justified because:
    (a) auth_service is only integration-tested (never unit-tested without an
        app context), and (b) JWT secrets must not be hardcoded or read from
        env directly in a way that bypasses Flask config validation.

Token design (ARCHITECTURE.md Section 7):
  - Access token: JWT, HS256, 15 min TTL, sub = user_id (str)
  - Refresh token: cryptographically random hex string, stored in DB as
    SHA-256 hash (never the raw value). Revoked on logout.
  - The raw refresh token is returned to the client once and never stored.

Password storage:
  - Hashed with bcrypt (cost factor from config BCRYPT_LOG_ROUNDS, default 12)
  - Raw password is never stored, never logged
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

import bcrypt
import jwt
from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError, ErrorCode
from app.models.refresh_token import RefreshToken
from app.models.user import User


# ── Private helpers ────────────────────────────────────────────────────────

def _hash_token(raw_token: str) -> str:
    """SHA-256 hex digest of a raw token string. Used for refresh token storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _create_access_token(user_id: int) -> str:
    """
    Creates a signed JWT access token.
    Payload: sub (user_id as str), iat, exp, jti.
    Algorithm: HS256. Secret from current_app.config["JWT_SECRET_KEY"].
    TTL from current_app.config["JWT_ACCESS_TOKEN_EXPIRES"] (timedelta).
    """
    now = datetime.now(timezone.utc)
    expiry = now + current_app.config["JWT_ACCESS_TOKEN_EXPIRES"]
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": expiry,
        # Guarantees each issued token is unique even if generated in the same second.
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(
        payload,
        current_app.config["JWT_SECRET_KEY"],
        algorithm=current_app.config.get("JWT_ALGORITHM", "HS256"),
    )


def _create_refresh_token(user_id: int, session: Session) -> str:
    """
    Creates a new refresh token, stores its SHA-256 hash in the DB,
    and returns the raw token to be sent to the client once.

    The raw value is never stored. Only the hash is persisted so that a
    compromised DB does not expose valid refresh tokens.
    """
    raw_token = secrets.token_hex(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + current_app.config["JWT_REFRESH_TOKEN_EXPIRES"]

    refresh_token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(refresh_token)
    # flush so the row exists before we return; commit is the route's job
    session.flush()

    return raw_token


def _build_token_pair(user_id: int, session: Session) -> dict:
    """Returns a dict with both access_token and refresh_token for a user."""
    return {
        "access_token": _create_access_token(user_id),
        "refresh_token": _create_refresh_token(user_id, session),
    }


def _build_user_dict(user: User) -> dict:
    """Serialises a User to a plain dict. No business logic."""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at.isoformat(),
    }


# ── Public service functions ───────────────────────────────────────────────

def register_user(
        username: str,
        email: str,
        password: str,
        session: Session,
) -> dict:
    """
    Creates a new user account and issues an access + refresh token pair.

    Raises:
      AppError(DUPLICATE_EMAIL, 409)    — email already registered
      AppError(DUPLICATE_USERNAME, 409) — username already taken

    Returns: {"user": {...}, "access_token": "...", "refresh_token": "..."}
    """
    # Cross-entity uniqueness checks (cannot be done in schema — require DB).
    existing_email = session.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()
    if existing_email is not None:
        raise AppError(
            ErrorCode.DUPLICATE_EMAIL,
            f"The email address '{email}' is already registered.",
            409,
            field="email",
        )

    existing_username = session.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()
    if existing_username is not None:
        raise AppError(
            ErrorCode.DUPLICATE_USERNAME,
            f"The username '{username}' is already taken.",
            409,
            field="username",
        )

    rounds = current_app.config.get("BCRYPT_LOG_ROUNDS", 12)
    password_hash = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=rounds),
    ).decode("utf-8")

    user = User(
        username=username,
        email=email,
        password_hash=password_hash,
    )
    session.add(user)
    session.flush()  # populate user.id before creating refresh token

    tokens = _build_token_pair(user.id, session)

    return {
        "user": _build_user_dict(user),
        **tokens,
    }


def login_user(
        username: str,
        password: str,
        session: Session,
) -> dict:
    """
    Validates credentials and issues a new access + refresh token pair.

    Raises:
      AppError(INVALID_CREDENTIALS, 401) — username not found or password wrong.
      Uses the same error for both to avoid username enumeration.

    Returns: {"user": {...}, "access_token": "...", "refresh_token": "..."}
    """
    user = session.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()

    # Constant-time password comparison prevents timing-based username enumeration.
    # bcrypt.checkpw handles this internally.
    if user is None or not bcrypt.checkpw(
            password.encode("utf-8"),
            user.password_hash.encode("utf-8"),
    ):
        raise AppError(
            ErrorCode.INVALID_CREDENTIALS,
            "The username or password is incorrect.",
            401,
        )

    tokens = _build_token_pair(user.id, session)

    return {
        "user": _build_user_dict(user),
        **tokens,
    }


def refresh_access_token(
        raw_refresh_token: str,
        session: Session,
) -> dict:
    """
    Validates a refresh token and issues a new access token.

    The refresh token itself is NOT rotated on use — the same refresh token
    remains valid until it expires or is explicitly revoked via logout.
    This is a deliberate simplicity tradeoff for v1 (ARCHITECTURE.md Section 7).

    Raises:
      AppError(REFRESH_TOKEN_INVALID, 401) — not found, revoked, or expired.

    Returns: {"access_token": "..."}
    """
    token_hash = _hash_token(raw_refresh_token)
    now = datetime.now(timezone.utc)

    record = session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    ).scalar_one_or_none()

    if record is None or record.revoked or record.expires_at <= now:
        raise AppError(
            ErrorCode.REFRESH_TOKEN_INVALID,
            "The refresh token is invalid, expired, or has been revoked.",
            401,
        )

    return {
        "access_token": _create_access_token(record.user_id),
    }


def logout_user(
        raw_refresh_token: str,
        session: Session,
) -> None:
    """
    Revokes a refresh token. Future calls to /auth/refresh with this token
    will return 401 REFRESH_TOKEN_INVALID.

    Access tokens are short-lived (15 min) and are not revocable without a
    server-side denylist — this is a documented v1 tradeoff (ARCHITECTURE.md).

    Raises:
      AppError(REFRESH_TOKEN_INVALID, 401) — token not found or already revoked.
    """
    token_hash = _hash_token(raw_refresh_token)

    record = session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    ).scalar_one_or_none()

    if record is None or record.revoked:
        raise AppError(
            ErrorCode.REFRESH_TOKEN_INVALID,
            "The refresh token is invalid or has already been revoked.",
            401,
        )

    record.revoked = True
    session.flush()


def get_current_user(user_id: int, session: Session) -> dict:
    """
    Returns the profile of the currently authenticated user.

    Raises:
      AppError(USER_NOT_FOUND, 404) — user_id from JWT no longer exists in DB.
        This is an edge case (user deleted between token issue and request) but
        must be handled gracefully.
    """
    user = session.get(User, user_id)
    if user is None:
        raise AppError(
            ErrorCode.USER_NOT_FOUND,
            f"User {user_id} not found.",
            404,
        )
    return _build_user_dict(user)
