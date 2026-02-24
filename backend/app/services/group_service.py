"""
services/group_service.py — Group and membership business logic.

Invariants enforced here:
  INV-9  FORBIDDEN (403) — only authenticated members may read/write group data

Authorization rules:
  - Adding a member:   group owner only
  - Removing a member: group owner may remove anyone; member may remove self

Layer rules (GUIDE Rule 3):
  - No Flask imports. Pure Python with a SQLAlchemy session parameter.
  - Commits are the route's responsibility — only flush here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.errors import AppError, ErrorCode
from backend.app.models.group import Group
from backend.app.models.membership import Membership
from backend.app.models.user import User


# ── Private helpers ────────────────────────────────────────────────────────

def _get_group_or_404(group_id: int, session: Session) -> Group:
    """Returns the Group or raises GROUP_NOT_FOUND (404)."""
    group = session.get(Group, group_id)
    if group is None:
        raise AppError(
            ErrorCode.GROUP_NOT_FOUND,
            f"Group {group_id} does not exist.",
            404,
        )
    return group


def _require_member(group_id: int, user_id: int, session: Session) -> None:
    """
    Raises FORBIDDEN (403) if user_id is not a member of group_id.
    INV-9: non-members receive 403, not 404 (spec Section 5).
    """
    membership = session.execute(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
            )
    ).scalar_one_or_none()

    if membership is None:
        raise AppError(
            ErrorCode.FORBIDDEN,
            f"You are not a member of group {group_id}.",
            403,
        )


def _build_group_dict(group: Group, members: list[User]) -> dict:
    """Serialises a Group with its member list to a plain dict."""
    return {
        "id": group.id,
        "name": group.name,
        "owner_user_id": group.owner_user_id,
        "created_at": group.created_at.isoformat(),
        "members": [
            {
                "id": m.id,
                "username": m.username,
                "email": m.email,
            }
            for m in members
        ],
    }


# ── Public service functions ───────────────────────────────────────────────

def create_group(name: str, owner_id: int, session: Session) -> dict:
    """
    Creates a new group. The creator automatically becomes the owner and
    the first member.

    Args:
        name:     Group name (validated by schema — non-empty, max 100 chars).
        owner_id: The authenticated user creating the group (flask.g.user_id,
                  passed by the route as a plain int).

    Returns: dict with group details and initial member list.
    """
    group = Group(name=name, owner_user_id=owner_id)
    session.add(group)
    session.flush()  # populate group.id before creating membership

    membership = Membership(user_id=owner_id, group_id=group.id)
    session.add(membership)
    session.flush()

    owner = session.get(User, owner_id)
    return _build_group_dict(group, [owner] if owner else [])


def list_groups(user_id: int, session: Session) -> list[dict]:
    """
    Returns all groups the user is a member of, ordered by creation date.

    Returns lightweight group dicts (no member list) for list efficiency.
    Full member list is available via get_group().
    """
    stmt = (
        select(Group)
        .join(Membership, Group.id == Membership.group_id)
        .where(Membership.user_id == user_id)
        .order_by(Group.created_at.asc())
    )
    groups = session.execute(stmt).scalars().all()

    return [
        {
            "id": g.id,
            "name": g.name,
            "owner_user_id": g.owner_user_id,
            "created_at": g.created_at.isoformat(),
        }
        for g in groups
    ]


def get_group(group_id: int, caller_id: int, session: Session) -> dict:
    """
    Returns full group details including current member list.

    INV-9: caller must be a member (FORBIDDEN 403, not 404).
    """
    group = _get_group_or_404(group_id, session)
    _require_member(group_id, caller_id, session)

    stmt = (
        select(User)
        .join(Membership, User.id == Membership.user_id)
        .where(Membership.group_id == group_id)
        .order_by(Membership.joined_at.asc())
    )
    members = list(session.execute(stmt).scalars().all())

    return _build_group_dict(group, members)


def add_member(
        group_id: int,
        caller_id: int,
        target_user_id: int,
        session: Session,
) -> dict:
    """
    Adds a user to a group. Only the group owner may call this.

    Raises:
      AppError(GROUP_NOT_FOUND, 404)  — group does not exist
      AppError(FORBIDDEN, 403)        — caller is not the group owner
      AppError(USER_NOT_FOUND, 404)   — target user does not exist
      AppError(ALREADY_MEMBER, 409)   — user is already in the group

    Returns: dict with the new membership details.
    """
    group = _get_group_or_404(group_id, session)

    # Only the group owner may add members (per spec Section 8.2).
    if caller_id != group.owner_user_id:
        raise AppError(
            ErrorCode.FORBIDDEN,
            "Only the group owner may add members.",
            403,
        )

    target_user = session.get(User, target_user_id)
    if target_user is None:
        raise AppError(
            ErrorCode.USER_NOT_FOUND,
            f"User {target_user_id} does not exist.",
            404,
        )

    existing = session.execute(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == target_user_id,
            )
    ).scalar_one_or_none()

    if existing is not None:
        raise AppError(
            ErrorCode.ALREADY_MEMBER,
            f"User {target_user_id} is already a member of group {group_id}.",
            409,
        )

    membership = Membership(user_id=target_user_id, group_id=group_id)
    session.add(membership)
    session.flush()

    return {
        "group_id": group_id,
        "user_id": target_user_id,
        "username": target_user.username,
        "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
    }


def remove_member(
        group_id: int,
        caller_id: int,
        target_user_id: int,
        session: Session,
) -> None:
    """
    Removes a user from a group.

    Authorization (spec Section 8.2):
      - The group owner may remove any member (including themselves).
      - Any member may remove themselves.
      - A non-owner may not remove another member (FORBIDDEN, 403).

    Raises:
      AppError(GROUP_NOT_FOUND, 404)  — group does not exist
      AppError(FORBIDDEN, 403)        — caller not authorised to remove this user
      AppError(USER_NOT_FOUND, 404)   — target user is not a member of the group
    """
    group = _get_group_or_404(group_id, session)

    # INV-9: caller must be a member of the group.
    _require_member(group_id, caller_id, session)

    is_owner = (caller_id == group.owner_user_id)
    is_self = (caller_id == target_user_id)

    if not (is_owner or is_self):
        raise AppError(
            ErrorCode.FORBIDDEN,
            "You may only remove yourself from a group unless you are the owner.",
            403,
        )

    membership = session.execute(
        select(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id == target_user_id,
            )
    ).scalar_one_or_none()

    if membership is None:
        raise AppError(
            ErrorCode.USER_NOT_FOUND,
            f"User {target_user_id} is not a member of group {group_id}.",
            404,
        )

    session.delete(membership)
    session.flush()