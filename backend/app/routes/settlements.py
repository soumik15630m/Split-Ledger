"""
routes/settlements.py — Settlement route handlers.

Layer rules (GUIDE Rule 3):
  - Parse, validate, call ONE service, commit, return envelope.
  - No business logic. No DB queries. No bare SQL.

Special: create_settlement returns (Settlement, warnings[]).
  If warnings is non-empty (e.g. OVERPAYMENT), the route includes them in the
  response envelope: {"data": {...}, "warnings": [{"code": "OVERPAYMENT", ...}]}.
  The HTTP status is still 201 — overpayment does NOT block the request (INV-3).

Endpoints (spec Section 8.5, base url_prefix=/api/v1/groups):
  POST   /groups/:id/settlements  → 201  record a debt payment
  GET    /groups/:id/settlements  → 200  list all settlements for a group
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.extensions import db
from app.middleware.auth_middleware import require_auth
from app.models.settlement import Settlement
from app.schemas.settlement_schema import CreateSettlementSchema
from app.services import settlement_service

settlements_bp = Blueprint("settlements", __name__)


# ── Serialization helper ───────────────────────────────────────────────────

def _serialize_settlement(s: Settlement) -> dict:
    """Converts a Settlement ORM object to a plain dict for JSON output."""
    return {
        "id": s.id,
        "group_id": s.group_id,
        "paid_by_user_id": s.paid_by_user_id,
        "paid_to_user_id": s.paid_to_user_id,
        "amount": str(s.amount),  # Decimal → string (spec: never JS number)
        "created_at": s.created_at.isoformat(),
    }


# ── Route handlers ─────────────────────────────────────────────────────────

@settlements_bp.route("/<int:group_id>/settlements", methods=["POST"])
@require_auth
def create_settlement(group_id: int):
    """
    POST /groups/:id/settlements — Record a debt payment.

    paid_by_user_id is the authenticated caller (g.user_id), not from the body.
    paid_to_user_id and amount come from the validated request body.

    If the amount exceeds current debt (INV-3), the settlement is still
    recorded and a warning is included in the response. Status remains 201.
    """
    data = CreateSettlementSchema().load(request.get_json(force=True) or {})
    settlement, warnings = settlement_service.create_settlement(
        group_id=group_id,
        paid_by_id=g.user_id,
        data=data,
        session=db.session,
    )
    db.session.commit()
    return jsonify({"data": _serialize_settlement(settlement), "warnings": warnings}), 201


@settlements_bp.route("/<int:group_id>/settlements", methods=["GET"])
@require_auth
def list_settlements(group_id: int):
    """GET /groups/:id/settlements — List all settlements for a group."""
    settlements = settlement_service.list_settlements(
        group_id=group_id,
        caller_id=g.user_id,
        session=db.session,
    )
    return jsonify({
        "data": [_serialize_settlement(s) for s in settlements],
        "warnings": [],
    }), 200