# backend/app/routes/users.py
from flask import Blueprint, jsonify
from sqlalchemy import select
from backend.app.extensions import db
from backend.app.models.user import User
from backend.app.middleware.auth_middleware import require_auth
from backend.app.errors import AppError, ErrorCode

users_bp = Blueprint("users", __name__)

@users_bp.route("/by-username/<string:username>", methods=["GET"])
@require_auth
def get_user_by_username(username: str):
    # Query the user using SQLAlchemy 2.0 syntax
    user = db.session.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()

    if not user:
        raise AppError(
            ErrorCode.USER_NOT_FOUND,
            f"User '{username}' not found.",
            404
        )

    return jsonify({
        "data": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat()
        },
        "warnings": []
    }), 200