"""
tests/integration/test_expense_edit.py — Integration tests for PATCH /expenses/:id.

Endpoints covered (spec Section 8.3, Section 7.2):
  PATCH /expenses/:id → 200 (partial update)

Edit rules verified (spec Section 7.2):
  - Any subset of fields may be sent; only provided fields are updated
  - If amount OR splits are provided, BOTH must be present (schema Rule D)
  - If split_mode changes to 'equal': splits absent, server recomputes
  - If split_mode changes to 'custom': splits array required with amount
  - INV-1 is re-validated atomically before any DB write (no partial writes)
  - Cannot edit a soft-deleted expense → 422 EXPENSE_DELETED (INV-8)
  - Only original payer or group owner may edit → 403 FORBIDDEN (INV-9)
  - updated_at is set to NOW() on every successful PATCH

Error codes:
  EXPENSE_DELETED    422 — editing a soft-deleted expense
  FORBIDDEN          403 — not payer or owner
  SPLIT_SUM_MISMATCH 422 — INV-1 violated on edit
  EXPENSE_NOT_FOUND  404 — expense does not exist

GUIDE Rule 6: every documented error case must have a test.
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
# Setup helper
# ═══════════════════════════════════════════════════════════════════════════

def _two_member_group_with_expense(client):
    """
    Creates: alice (owner), bob (member), group, and one expense paid by alice.
    Returns (alice, bob, group, expense_id).
    """
    alice = register(client, "alice")
    bob   = register(client, "bob")
    group = make_group(client, alice["access_token"])
    add_member(client, alice["access_token"], group["id"], bob["user"]["id"])

    resp = make_expense(
        client, alice["access_token"], group["id"],
        paid_by_user_id=alice["user"]["id"],
        amount="100.00",
        splits=[
            {"user_id": alice["user"]["id"], "amount": "60.00"},
            {"user_id": bob["user"]["id"],   "amount": "40.00"},
        ],
        description="Original description",
        category="other",
    )
    expense_id = resp.get_json()["data"]["id"]
    return alice, bob, group, expense_id


def _patch(client, token, expense_id, payload):
    """Helper to send a PATCH request."""
    return client.patch(
        f"/api/v1/expenses/{expense_id}",
        json=payload,
        headers=auth_headers(token),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Happy path — field updates
# ═══════════════════════════════════════════════════════════════════════════

class TestPatchHappyPath:

    def test_patch_description_only_returns_200(self, client):
        alice, bob, group, eid = _two_member_group_with_expense(client)

        resp = _patch(client, alice["access_token"], eid, {"description": "New description"})
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["description"] == "New description"
        assert data["amount"]      == "100.00"   # unchanged

    def test_patch_category_only_returns_200(self, client):
        alice, bob, group, eid = _two_member_group_with_expense(client)

        resp = _patch(client, alice["access_token"], eid, {"category": "food"})
        assert resp.status_code == 200
        assert resp.get_json()["data"]["category"] == "food"

    def test_patch_amount_and_splits_together_returns_200(self, client):
        """INV-1 re-validated atomically when amount+splits both provided."""
        alice, bob, group, eid = _two_member_group_with_expense(client)

        resp = _patch(client, alice["access_token"], eid, {
            "amount": "200.00",
            "splits": [
                {"user_id": alice["user"]["id"], "amount": "120.00"},
                {"user_id": bob["user"]["id"],   "amount": "80.00"},
            ],
        })
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["amount"] == "200.00"

        # Verify splits sum (INV-1)
        split_sum = sum(Decimal(s["amount"]) for s in data["splits"])
        assert split_sum == Decimal("200.00")

    def test_patch_sets_updated_at(self, client):
        """Spec Section 7.2: updated_at is set to NOW() on every successful PATCH."""
        alice, bob, group, eid = _two_member_group_with_expense(client)

        resp = _patch(client, alice["access_token"], eid, {"description": "Updated"})
        assert resp.status_code == 200
        assert resp.get_json()["data"]["updated_at"] is not None

    def test_patch_split_mode_to_equal_recomputes_splits(self, client):
        """
        Spec Section 7.2: if split_mode changes to 'equal', server recomputes splits.
        Client must NOT send splits array. Amount may be sent.
        """
        alice, bob, group, eid = _two_member_group_with_expense(client)

        resp = _patch(client, alice["access_token"], eid, {
            "split_mode": "equal",
            "amount": "100.00",
        })
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["split_mode"] == "equal"

        # INV-1: server-computed splits must sum to 100.00
        split_sum = sum(Decimal(s["amount"]) for s in data["splits"])
        assert split_sum == Decimal("100.00")

    def test_patch_split_mode_to_custom_with_new_splits(self, client):
        """Switching from equal to custom with explicit splits."""
        alice = register(client, "alice")
        bob   = register(client, "bob")
        group = make_group(client, alice["access_token"])
        add_member(client, alice["access_token"], group["id"], bob["user"]["id"])

        # Create equal-mode expense
        create_resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="100.00",
            splits=None,
            split_mode="equal",
        )
        eid = create_resp.get_json()["data"]["id"]

        # Switch to custom
        resp = _patch(client, alice["access_token"], eid, {
            "split_mode": "custom",
            "amount": "100.00",
            "splits": [
                {"user_id": alice["user"]["id"], "amount": "70.00"},
                {"user_id": bob["user"]["id"],   "amount": "30.00"},
            ],
        })
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["split_mode"] == "custom"

        split_sum = sum(Decimal(s["amount"]) for s in data["splits"])
        assert split_sum == Decimal("100.00")

    def test_group_owner_can_edit_others_expense(self, client):
        """Spec: group owner may edit any expense, even if not the payer."""
        alice = register(client, "alice")   # owner
        bob   = register(client, "bob")
        group = make_group(client, alice["access_token"])
        add_member(client, alice["access_token"], group["id"], bob["user"]["id"])

        # Bob creates the expense
        resp = make_expense(
            client, bob["access_token"], group["id"],
            paid_by_user_id=bob["user"]["id"],
            amount="50.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "25.00"},
                {"user_id": bob["user"]["id"],   "amount": "25.00"},
            ],
        )
        eid = resp.get_json()["data"]["id"]

        # Alice (owner, not payer) edits it
        resp = _patch(client, alice["access_token"], eid, {"description": "Edited by owner"})
        assert resp.status_code == 200
        assert resp.get_json()["data"]["description"] == "Edited by owner"


# ═══════════════════════════════════════════════════════════════════════════
# Failure paths
# ═══════════════════════════════════════════════════════════════════════════

class TestPatchFailurePaths:

    def test_edit_deleted_expense_returns_422_expense_deleted(self, client):
        """INV-8: soft-deleted expenses cannot be edited."""
        alice, bob, group, eid = _two_member_group_with_expense(client)

        # Soft-delete the expense first
        client.delete(f"/api/v1/expenses/{eid}", headers=auth_headers(alice["access_token"]))

        # Attempt to edit it
        resp = _patch(client, alice["access_token"], eid, {"description": "Should fail"})
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "EXPENSE_DELETED"

    def test_non_payer_non_owner_cannot_edit_returns_403(self, client):
        """Only the original payer or group owner may edit."""
        alice, bob, group, eid = _two_member_group_with_expense(client)
        carol = register(client, "carol")
        add_member(client, alice["access_token"], group["id"], carol["user"]["id"])

        # Carol is a member but not the payer or owner
        resp = _patch(client, carol["access_token"], eid, {"description": "Carol's edit"})
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_edit_nonexistent_expense_returns_404(self, client):
        alice = register(client, "alice")
        resp = _patch(client, alice["access_token"], 99999, {"description": "Ghost"})
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "EXPENSE_NOT_FOUND"

    def test_amount_without_splits_returns_400(self, client):
        """Schema Rule D: amount and splits must be co-present."""
        alice, bob, group, eid = _two_member_group_with_expense(client)
        resp = _patch(client, alice["access_token"], eid, {"amount": "200.00"})
        assert resp.status_code == 400
        # Schema catches this before the service is called
        assert "splits" in resp.get_json()["error"].get("field", "") or \
               resp.get_json()["error"]["code"] in ("INVALID_FIELD", "MISSING_FIELD")

    def test_splits_without_amount_returns_400(self, client):
        """Schema Rule D: splits without amount is invalid."""
        alice, bob, group, eid = _two_member_group_with_expense(client)
        resp = _patch(client, alice["access_token"], eid, {
            "splits": [
                {"user_id": alice["user"]["id"], "amount": "50.00"},
                {"user_id": bob["user"]["id"],   "amount": "50.00"},
            ],
        })
        assert resp.status_code == 400

    def test_inv1_mismatch_on_edit_returns_422(self, client):
        """INV-1 is re-validated on PATCH. Mismatched amount+splits → 422."""
        alice, bob, group, eid = _two_member_group_with_expense(client)

        resp = _patch(client, alice["access_token"], eid, {
            "amount": "200.00",
            "splits": [
                {"user_id": alice["user"]["id"], "amount": "60.00"},
                {"user_id": bob["user"]["id"],   "amount": "40.00"},
                # sum = 100.00, not 200.00
            ],
        })
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "SPLIT_SUM_MISMATCH"

    def test_equal_mode_with_splits_on_patch_returns_400(self, client):
        """Schema Rule A: split_mode=equal + splits array is invalid."""
        alice, bob, group, eid = _two_member_group_with_expense(client)
        resp = _patch(client, alice["access_token"], eid, {
            "split_mode": "equal",
            "splits": [{"user_id": alice["user"]["id"], "amount": "100.00"}],
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "SPLITS_SENT_FOR_EQUAL_MODE"

    def test_unauthenticated_patch_returns_401(self, client):
        alice, bob, group, eid = _two_member_group_with_expense(client)
        resp = client.patch(f"/api/v1/expenses/{eid}", json={"description": "Anon"})
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "TOKEN_MISSING"
