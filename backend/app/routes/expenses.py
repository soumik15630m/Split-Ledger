"""
routes/expenses.py — Expense route handlers.

Registered at url_prefix=/api/v1 (not /api/v1/expenses) because this blueprint
owns BOTH the group-scoped paths (/groups/:id/expenses) and the
expense-ID paths (/expenses/:id). Registering at /api/v1/expenses would
make the group-scoped paths unreachable.

Layer rules (GUIDE Rule 3):
  - Parse, validate, call ONE service, commit, return envelope.
  - No business logic. No DB queries. No bare SQL.
  - _serialize_expense() is a pure data-shape helper — not business logic.

Endpoints (spec Section 8.3):
  POST   /groups/:id/expenses   → 201  create expense
  GET    /groups/:id/expenses   → 200  list active expenses
  GET    /expenses/:id          → 200  get expense + splits
  PATCH  /expenses/:id          → 200  partial update
  DELETE /expenses/:id          → 200  soft-delete
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from backend.app.extensions import db
from backend.app.middleware.auth_middleware import require_auth
from backend.app.models.expense import Expense
from backend.app.schemas.expense_schema import CreateExpenseSchema, PatchExpenseSchema
from backend.app.services import expense_service
from backend.app.models.expense import Expense
from backend.app.models.split import Split

expenses_bp = Blueprint("expenses", __name__)


# ── Serialization helper ───────────────────────────────────────────────────
# Pure data-shaping — no DB access, no logic. Amounts as strings per spec.

def _serialize_expense(expense: Expense) -> dict:
    """Converts an Expense ORM object to a plain dict for JSON output."""
    return {
        "id": expense.id,
        "group_id": expense.group_id,
        "paid_by_user_id": expense.paid_by_user_id,
        "paid_by_username": expense.payer.username,     # <-- ADD THIS LINE
        "description": expense.description,
        "amount": str(expense.amount),                  # Decimal → string
        "split_mode": expense.split_mode.value,
        "category": expense.category.value,
        "created_at": expense.created_at.isoformat(),
        "updated_at": expense.updated_at.isoformat() if expense.updated_at else None,
        "deleted_at": expense.deleted_at.isoformat() if expense.deleted_at else None,
        "splits": [
            {
                "id": s.id,
                "user_id": s.user_id,
                "username": s.user.username,            # <-- ADD THIS LINE
                "amount": str(s.amount),                # Decimal → string
            }
            for s in expense.splits
        ],
    }


# ── Group-scoped expense routes ────────────────────────────────────────────

@expenses_bp.route("/groups/<int:group_id>/expenses", methods=["POST"])
@require_auth
def create_expense(group_id: int):
    """
    POST /groups/:id/expenses — Record a new expense.
    Handles both 'equal' (server computes splits) and 'custom' modes.
    """
    data = CreateExpenseSchema().load(request.get_json(force=True) or {})
    expense = expense_service.create_expense(
        group_id=group_id,
        caller_id=g.user_id,
        data=data,
        session=db.session,
    )
    db.session.commit()
    return jsonify({"data": _serialize_expense(expense), "warnings": []}), 201


@expenses_bp.route("/groups/<int:group_id>/expenses", methods=["GET"])
@require_auth
def list_expenses(group_id: int):
    """GET /groups/:id/expenses — List active (non-deleted) expenses for a group."""
    expenses = expense_service.list_expenses(
        group_id=group_id,
        caller_id=g.user_id,
        session=db.session,
    )
    return jsonify({
        "data": [_serialize_expense(e) for e in expenses],
        "warnings": [],
    }), 200


# ── Expense-ID routes ──────────────────────────────────────────────────────

@expenses_bp.route("/expenses/<int:expense_id>", methods=["GET"])
@require_auth
def get_expense(expense_id: int):
    """GET /expenses/:id — Get expense detail including splits."""
    expense = expense_service.get_expense(
        expense_id=expense_id,
        caller_id=g.user_id,
        session=db.session,
    )
    return jsonify({"data": _serialize_expense(expense), "warnings": []}), 200


@expenses_bp.route("/expenses/<int:expense_id>", methods=["PATCH"])
@require_auth
def edit_expense(expense_id: int):
    """
    PATCH /expenses/:id — Partial update.
    If amount or splits change, both must be present; INV-1 is re-validated.
    Only original payer or group owner may edit.
    """
    data = PatchExpenseSchema().load(request.get_json(force=True) or {})
    expense = expense_service.edit_expense(
        expense_id=expense_id,
        caller_id=g.user_id,
        data=data,
        session=db.session,
    )
    db.session.commit()
    return jsonify({"data": _serialize_expense(expense), "warnings": []}), 200


@expenses_bp.route("/expenses/<int:expense_id>", methods=["DELETE"])
@require_auth
def delete_expense(expense_id: int):
    """
    DELETE /expenses/:id — Soft-delete (sets deleted_at = NOW()).
    Row stays in DB. Splits remain for audit. Balance computation excludes it (INV-8).
    """
    expense_service.delete_expense(
        expense_id=expense_id,
        caller_id=g.user_id,
        session=db.session,
    )
    db.session.commit()
    return jsonify({
        "data": {
            "deleted": True,
            "expense_id": expense_id,
        },
        "warnings": [],
    }), 200

@expenses_bp.route("/groups/<int:group_id>/expenses/<int:expense_id>", methods=["PUT"])
@require_auth
def update_expense(group_id, expense_id):
    # Use g.user_id to match your project's auth pattern
    user_id = g.user_id
    expense = Expense.query.filter_by(id=expense_id, group_id=group_id).first_or_404()

    if expense.paid_by_user_id != user_id:
        return jsonify({"error": "Only the payer can edit this expense"}), 403

    data = request.get_json()

    # Update main fields
    expense.description = data.get("description", expense.description)
    expense.amount = data.get("amount", expense.amount)
    expense.category = data.get("category", expense.category)
    expense.paid_by_user_id = data.get("paid_by_user_id", expense.paid_by_user_id)
    expense.split_mode = data.get("split_mode", expense.split_mode)
    expense.updated_at = db.func.now()

    # UPDATE SPLITS
    if "splits" in data:
        # 1. Clear existing splits
        Split.query.filter_by(expense_id=expense.id).delete()

        # 2. Add new splits from the frontend payload
        for s in data["splits"]:
            new_split = Split(
                expense_id=expense.id,
                user_id=s["user_id"],
                amount=s["amount"]
            )
            db.session.add(new_split)

    db.session.commit() # This saves everything at once
    return jsonify({"data": _serialize_expense(expense)}), 200