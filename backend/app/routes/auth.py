"""
routes/auth.py — Authentication route handlers.

Layer rules (GUIDE Rule 3 + ARCHITECTURE.md Section 2):
  - Parse request body
  - Validate with the appropriate schema (raises ValidationError on bad input)
  - Call exactly ONE service function
  - Commit the DB session
  - Return the standard response envelope: {"data": {...}, "warnings": []}

No business logic here. No DB queries. No bare SQL.
AppError propagates to the global error handler in app/__init__.py — routes
never catch it.

Endpoints (spec Section 8.1, base url_prefix=/api/v1/auth):
  POST   /auth/register  → 201
  POST   /auth/login     → 200
  POST   /auth/refresh   → 200
  POST   /auth/logout    → 200
  GET    /auth/me        → 200
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from backend.app.extensions import db
from backend.app.middleware.auth_middleware import require_auth
from backend.app.schemas.auth_schema import LoginSchema, RefreshTokenSchema, RegisterSchema
from backend.app.services import auth_service

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["POST"])
def register():
    """POST /auth/register — Create account; return tokens. (No auth required.)"""
    data = RegisterSchema().load(request.get_json(force=True) or {})
    result = auth_service.register_user(
        username=data["username"],
        email=data["email"],
        password=data["password"],
        session=db.session,
    )
    db.session.commit()
    return jsonify({"data": result, "warnings": []}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    """POST /auth/login — Authenticate; return tokens. (No auth required.)"""
    data = LoginSchema().load(request.get_json(force=True) or {})
    result = auth_service.login_user(
        username=data["username"],
        password=data["password"],
        session=db.session,
    )
    db.session.commit()
    return jsonify({"data": result, "warnings": []}), 200


@auth_bp.route("/refresh", methods=["POST"])
def refresh():
    """POST /auth/refresh — Exchange refresh token for new access token."""
    data = RefreshTokenSchema().load(request.get_json(force=True) or {})
    result = auth_service.refresh_access_token(
        raw_refresh_token=data["refresh_token"],
        session=db.session,
    )
    db.session.commit()
    return jsonify({"data": result, "warnings": []}), 200


@auth_bp.route("/logout", methods=["POST"])
@require_auth
def logout():
    """POST /auth/logout — Revoke refresh token. (Auth required.)"""
    data = RefreshTokenSchema().load(request.get_json(force=True) or {})
    auth_service.logout_user(
        raw_refresh_token=data["refresh_token"],
        session=db.session,
    )
    db.session.commit()
    return jsonify({"data": {"message": "Logged out successfully."}, "warnings": []}), 200


@auth_bp.route("/me", methods=["GET"])
@require_auth
def me():
    """GET /auth/me — Return current user profile. (Auth required.)"""
    result = auth_service.get_current_user(
        user_id=g.user_id,
        session=db.session,
    )
    return jsonify({"data": result, "warnings": []}), 200