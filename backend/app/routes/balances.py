"""
routes/balances.py — Balance route handlers.

Layer rules (GUIDE Rule 3):
  - Parse query params, call ONE service, return envelope.
  - No business logic. No DB queries. No bare SQL.
  - The ?category= filter is informational only (spec Section 8.4).
    balance_sum will NOT be "0.00" for a filtered result — the client
    must not assert INV-2 on filtered data.

Endpoints (spec Section 8.4, base url_prefix=/api/v1/groups):
  GET /groups/:id/balances              → 200  full balances + simplified debts
  GET /groups/:id/balances?category=X  → 200  balances scoped to one category (informational)
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from backend.app.errors import AppError, ErrorCode
from backend.app.extensions import db
from backend.app.middleware.auth_middleware import require_auth
from backend.app.models.expense import Category
from backend.app.services import balance_service

balances_bp = Blueprint("balances", __name__)


@balances_bp.route("/<int:group_id>/balances", methods=["GET"])
@require_auth
def get_balances(group_id: int):
    """
    GET /groups/:id/balances

    Optional query param:
      ?category=food|transport|accommodation|entertainment|utilities|other
      When present, balances reflect only expenses of that category.
      Settlements are excluded from category-filtered results.
      balance_sum will NOT be "0.00" in this case.

    INV-9 is enforced inside balance_service.get_balance_response() — the
    service verifies the caller is a group member before computing.

    The service asserts INV-2 (balance_sum == 0) for full (unfiltered)
    requests and raises INTERNAL_ERROR (500) if the sum is non-zero.
    """
    # Parse and validate the optional category query parameter.
    category_param = request.args.get("category")
    category = None

    if category_param is not None:
        try:
            category = Category(category_param)
        except ValueError:
            raise AppError(
                ErrorCode.INVALID_CATEGORY,
                f"'{category_param}' is not a valid category. "
                f"Valid values: {', '.join(c.value for c in Category)}.",
                400,
                field="category",
            )

    result = balance_service.get_balance_response(
        group_id=group_id,
        caller_id=g.user_id,
        session=db.session,
        category=category,
    )
    return jsonify({"data": result, "warnings": []}), 200