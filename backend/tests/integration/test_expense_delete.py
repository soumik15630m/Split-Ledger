"""
tests/integration/test_expense_delete.py — Integration tests for DELETE /expenses/:id.

Endpoints covered (spec Section 8.3, Section 7.1):
  DELETE /expenses/:id → 200 (soft-delete envelope)

Rules verified:
  - DELETE sets deleted_at = NOW() (soft-delete, not hard delete — row stays in DB)
  - Splits remain in DB for audit (not removed by delete)
  - Soft-deleted expenses are EXCLUDED from balance computation (INV-8)
  - DELETE is idempotent: re-deleting an already-deleted expense returns 200 (no error)
  - Cannot edit a soft-deleted expense → 422 EXPENSE_DELETED (INV-8)
  - Only original payer or group owner may delete → 403 FORBIDDEN
  - GET /expenses/:id still works on deleted expense (200, deleted_at populated)
  - GET /groups/:id/expenses does NOT include deleted expenses (INV-8)

GUIDE Rule 8 — Soft Delete Means Excluded, Not Gone.
  Every query involving balance computation must filter WHERE deleted_at IS NULL.
  This is the integration-level proof of that invariant.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from .conftest import (
    add_member,
    auth_headers,
    make_expense,
    make_group,
    register,
)


# ═══════════════════════════════════════════════════════════════════════════
# Setup helpers
# ═══════════════════════════════════════════════════════════════════════════

def _setup(client):
    """Creates alice, bob, group with both as members."""
    alice = register(client, "alice")
    bob   = register(client, "bob")
    group = make_group(client, alice["access_token"])
    add_member(client, alice["access_token"], group["id"], bob["user"]["id"])
    return alice, bob, group


def _create_expense(client, alice, bob, group, amount="100.00"):
    """Creates a custom-split expense and returns expense dict."""
    half = str(Decimal(amount) / 2)
    resp = make_expense(
        client, alice["access_token"], group["id"],
        paid_by_user_id=alice["user"]["id"],
        amount=amount,
        splits=[
            {"user_id": alice["user"]["id"], "amount": half},
            {"user_id": bob["user"]["id"],   "amount": half},
        ],
    )
    assert resp.status_code == 201
    return resp.get_json()["data"]


def _delete(client, token, expense_id):
    return client.delete(
        f"/api/v1/expenses/{expense_id}",
        headers=auth_headers(token),
    )


def _get_balances(client, token, group_id):
    return client.get(
        f"/api/v1/groups/{group_id}/balances",
        headers=auth_headers(token),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Soft-delete mechanics
# ═══════════════════════════════════════════════════════════════════════════

class TestDeleteMechanics:

    def test_delete_returns_200_with_envelope(self, client):
        alice, bob, group = _setup(client)
        expense = _create_expense(client, alice, bob, group)
        resp = _delete(client, alice["access_token"], expense["id"])
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["data"]["deleted"] is True
        assert payload["data"]["expense_id"] == expense["id"]
        assert payload["warnings"] == []

    def test_delete_sets_deleted_at(self, client):
        """Row stays in DB — deleted_at is populated, not NULL."""
        alice, bob, group = _setup(client)
        expense = _create_expense(client, alice, bob, group)
        _delete(client, alice["access_token"], expense["id"])

        # GET still works; deleted_at should now be set
        resp = client.get(
            f"/api/v1/expenses/{expense['id']}",
            headers=auth_headers(alice["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["deleted_at"] is not None

    def test_delete_is_idempotent(self, client):
        """
        expense_service.delete_expense() is idempotent (spec Section 7.1 note).
        Re-deleting an already-deleted expense returns 200 (not 404 or 422).
        """
        alice, bob, group = _setup(client)
        expense = _create_expense(client, alice, bob, group)

        resp1 = _delete(client, alice["access_token"], expense["id"])
        resp2 = _delete(client, alice["access_token"], expense["id"])

        assert resp1.status_code == 200
        assert resp2.status_code == 200   # idempotent

    def test_splits_remain_in_db_after_delete(self, client):
        """
        GUIDE Rule 8: "splits remain for audit — not recoverable in v1".
        GET on the deleted expense still returns the splits array.
        """
        alice, bob, group = _setup(client)
        expense = _create_expense(client, alice, bob, group)
        _delete(client, alice["access_token"], expense["id"])

        resp = client.get(
            f"/api/v1/expenses/{expense['id']}",
            headers=auth_headers(alice["access_token"]),
        )
        data = resp.get_json()["data"]
        # The splits array must still be present (audit trail)
        assert len(data["splits"]) == 2

    def test_deleted_expense_not_in_list(self, client):
        """
        INV-8: GET /groups/:id/expenses returns only WHERE deleted_at IS NULL.
        """
        alice, bob, group = _setup(client)
        expense = _create_expense(client, alice, bob, group)
        _delete(client, alice["access_token"], expense["id"])

        resp = client.get(
            f"/api/v1/groups/{group['id']}/expenses",
            headers=auth_headers(alice["access_token"]),
        )
        assert resp.status_code == 200
        expenses = resp.get_json()["data"]
        expense_ids = [e["id"] for e in expenses]
        assert expense["id"] not in expense_ids, "Deleted expense must not appear in list"


# ═══════════════════════════════════════════════════════════════════════════
# INV-8: deleted expenses excluded from balance computation
# ═══════════════════════════════════════════════════════════════════════════

class TestDeletedExpenseExcludedFromBalance:

    def test_balance_sum_zero_before_delete(self, client):
        """Baseline: balance_sum is 0.00 for an active expense."""
        alice, bob, group = _setup(client)
        _create_expense(client, alice, bob, group, amount="100.00")

        resp = _get_balances(client, alice["access_token"], group["id"])
        assert resp.status_code == 200
        assert resp.get_json()["data"]["balance_sum"] == "0.00"

    def test_deleted_expense_excluded_from_balances(self, client):
        """
        INV-8: After deleting the only expense, all balances must return to zero.
        This is the definitive integration test for the soft-delete balance exclusion.
        """
        alice, bob, group = _setup(client)
        expense = _create_expense(client, alice, bob, group, amount="100.00")

        # Before delete: Alice +50 (net), Bob -50
        resp_before = _get_balances(client, alice["access_token"], group["id"])
        balances_before = {
            b["user_id"]: Decimal(b["balance"])
            for b in resp_before.get_json()["data"]["balances"]
        }
        assert balances_before[alice["user"]["id"]] == Decimal("50.00")
        assert balances_before[bob["user"]["id"]]   == Decimal("-50.00")

        # Delete the expense
        _delete(client, alice["access_token"], expense["id"])

        # After delete: all balances must be zero
        resp_after = _get_balances(client, alice["access_token"], group["id"])
        balances_after = {
            b["user_id"]: Decimal(b["balance"])
            for b in resp_after.get_json()["data"]["balances"]
        }
        assert balances_after[alice["user"]["id"]] == Decimal("0.00"), (
            "Alice's balance must be 0.00 after deleting the only expense (INV-8)"
        )
        assert balances_after[bob["user"]["id"]] == Decimal("0.00"), (
            "Bob's balance must be 0.00 after deleting the only expense (INV-8)"
        )

    def test_balance_sum_still_zero_after_delete(self, client):
        """INV-2 must hold after soft-delete: balance_sum must remain 0.00."""
        alice, bob, group = _setup(client)
        expense = _create_expense(client, alice, bob, group, amount="60.00")
        _delete(client, alice["access_token"], expense["id"])

        resp = _get_balances(client, alice["access_token"], group["id"])
        assert resp.get_json()["data"]["balance_sum"] == "0.00"

    def test_only_deleted_expense_excluded_remaining_still_counted(self, client):
        """
        If there are two expenses and only one is deleted, the remaining
        expense still contributes to balances correctly.
        """
        alice, bob, group = _setup(client)

        # Expense 1: $80 — will be KEPT
        _create_expense(client, alice, bob, group, amount="80.00")

        # Expense 2: $40 — will be DELETED
        expense2 = _create_expense(client, alice, bob, group, amount="40.00")

        _delete(client, alice["access_token"], expense2["id"])

        resp = _get_balances(client, alice["access_token"], group["id"])
        data = resp.get_json()["data"]
        balances = {b["user_id"]: Decimal(b["balance"]) for b in data["balances"]}

        # Only expense1 ($80, 50/50 split) should count.
        # Alice: +80 (payer) - 40 (split) = +40
        # Bob: -40
        assert balances[alice["user"]["id"]] == Decimal("40.00")
        assert balances[bob["user"]["id"]]   == Decimal("-40.00")
        assert data["balance_sum"] == "0.00"


# ═══════════════════════════════════════════════════════════════════════════
# Edit after delete → EXPENSE_DELETED
# ═══════════════════════════════════════════════════════════════════════════

class TestEditAfterDelete:

    def test_edit_deleted_expense_returns_422(self, client):
        """
        spec Section 7.2: "A deleted expense cannot be edited — returns 422 EXPENSE_DELETED."
        This verifies the edit path correctly checks the soft-delete state.
        """
        alice, bob, group = _setup(client)
        expense = _create_expense(client, alice, bob, group)
        _delete(client, alice["access_token"], expense["id"])

        resp = client.patch(
            f"/api/v1/expenses/{expense['id']}",
            json={"description": "After delete edit"},
            headers=auth_headers(alice["access_token"]),
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "EXPENSE_DELETED"


# ═══════════════════════════════════════════════════════════════════════════
# Authorization
# ═══════════════════════════════════════════════════════════════════════════

class TestDeleteAuthorization:

    def test_non_payer_non_owner_cannot_delete_returns_403(self, client):
        """Only original payer or group owner may soft-delete."""
        alice, bob, group = _setup(client)
        carol = register(client, "carol")
        add_member(client, alice["access_token"], group["id"], carol["user"]["id"])

        expense = _create_expense(client, alice, bob, group)

        # Carol is a member but not the payer or owner
        resp = _delete(client, carol["access_token"], expense["id"])
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_original_payer_can_delete_own_expense(self, client):
        """Payer may delete their own expense."""
        alice, bob, group = _setup(client)

        # Bob creates an expense
        resp = make_expense(
            client, bob["access_token"], group["id"],
            paid_by_user_id=bob["user"]["id"],
            amount="50.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "25.00"},
                {"user_id": bob["user"]["id"],   "amount": "25.00"},
            ],
        )
        expense_id = resp.get_json()["data"]["id"]

        # Bob (payer) deletes it
        resp = _delete(client, bob["access_token"], expense_id)
        assert resp.status_code == 200

    def test_group_owner_can_delete_any_expense(self, client):
        """Group owner may delete expenses they did not pay."""
        alice, bob, group = _setup(client)

        # Bob creates an expense
        resp = make_expense(
            client, bob["access_token"], group["id"],
            paid_by_user_id=bob["user"]["id"],
            amount="50.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "25.00"},
                {"user_id": bob["user"]["id"],   "amount": "25.00"},
            ],
        )
        expense_id = resp.get_json()["data"]["id"]

        # Alice (owner, not payer) deletes it
        resp = _delete(client, alice["access_token"], expense_id)
        assert resp.status_code == 200

    def test_unauthenticated_delete_returns_401(self, client):
        alice, bob, group = _setup(client)
        expense = _create_expense(client, alice, bob, group)

        resp = client.delete(f"/api/v1/expenses/{expense['id']}")
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "TOKEN_MISSING"

    def test_delete_nonexistent_expense_returns_404(self, client):
        alice = register(client, "alice")
        resp = _delete(client, alice["access_token"], 99999)
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "EXPENSE_NOT_FOUND"
