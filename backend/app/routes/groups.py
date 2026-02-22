"""
routes/groups.py — Group and membership route handlers.

Layer rules (GUIDE Rule 3):
  - Parse, validate, call ONE service, commit, return envelope.
  - No business logic. No DB queries. No bare SQL.

Endpoints (spec Section 8.2, base url_prefix=/api/v1/groups):
  POST   /groups                        → 201  create group
  GET    /groups                        → 200  list caller's groups
  GET    /groups/:id                    → 200  get group + members
  POST   /groups/:id/members            → 201  add member (owner only)
  DELETE /groups/:id/members/:uid       → 200  remove member (owner or self)
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.extensions import db
from app.middleware.auth_middleware import require_auth
from app.schemas.group_schema import AddMemberSchema, CreateGroupSchema
from app.services import group_service

groups_bp = Blueprint("groups", __name__)


@groups_bp.route("/", methods=["POST"])
@require_auth
def create_group():
    """POST /groups — Create a new group. Caller becomes owner and first member."""
    data = CreateGroupSchema().load(request.get_json(force=True) or {})
    result = group_service.create_group(
        name=data["name"],
        owner_id=g.user_id,
        session=db.session,
    )
    db.session.commit()
    return jsonify({"data": result, "warnings": []}), 201


@groups_bp.route("/", methods=["GET"])
@require_auth
def list_groups():
    """GET /groups — List all groups the authenticated user belongs to."""
    result = group_service.list_groups(
        user_id=g.user_id,
        session=db.session,
    )
    return jsonify({"data": result, "warnings": []}), 200


@groups_bp.route("/<int:group_id>", methods=["GET"])
@require_auth
def get_group(group_id: int):
    """GET /groups/:id — Get group details with member list. Caller must be member."""
    result = group_service.get_group(
        group_id=group_id,
        caller_id=g.user_id,
        session=db.session,
    )
    return jsonify({"data": result, "warnings": []}), 200


@groups_bp.route("/<int:group_id>/members", methods=["POST"])
@require_auth
def add_member(group_id: int):
    """POST /groups/:id/members — Add a user to the group. Owner only."""
    data = AddMemberSchema().load(request.get_json(force=True) or {})
    result = group_service.add_member(
        group_id=group_id,
        caller_id=g.user_id,
        target_user_id=data["user_id"],
        session=db.session,
    )
    db.session.commit()
    return jsonify({"data": result, "warnings": []}), 201


@groups_bp.route("/<int:group_id>/members/<int:target_uid>", methods=["DELETE"])
@require_auth
def remove_member(group_id: int, target_uid: int):
    """DELETE /groups/:id/members/:uid — Remove a member. Owner removes anyone; member removes self."""
    group_service.remove_member(
        group_id=group_id,
        caller_id=g.user_id,
        target_user_id=target_uid,
        session=db.session,
    )
    db.session.commit()
    return jsonify({
        "data": {
            "removed": True,
            "group_id": group_id,
            "user_id": target_uid,
        },
        "warnings": [],
    }), 200
