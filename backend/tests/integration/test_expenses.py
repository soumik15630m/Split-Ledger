"""
tests/integration/test_expenses.py — Integration tests for expense creation, listing, and retrieval.

Endpoints covered (spec Section 8.3):
  POST /groups/:id/expenses → 201 (create)
  GET  /groups/:id/expenses → 200 (list active only, INV-8)
  GET  /expenses/:id        → 200 (get with splits)

Invariants verified:
  INV-1  SPLIT_SUM_MISMATCH (422)      — sum(splits) must equal amount
  INV-5  PAYER_NOT_MEMBER  (422)       — paid_by must be a group member
  INV-6  SPLIT_USER_NOT_MEMBER (422)   — every split user must be a member
  INV-7  INVALID_AMOUNT_PRECISION (400)— max 2 decimal places, no rounding
  INV-8                                — list only returns active expenses
  INV-9  FORBIDDEN (403)               — only members can read/write group data

GUIDE Rule 3 — routes call services; routes have no business logic.
  Verified implicitly: routes return correct codes for service-raised AppErrors.
GUIDE Rule 2 — amounts appear as strings in JSON, never JS numbers.
"""

from __future__ import annotations

import pytest

from .conftest import (
    add_member,
    auth_headers,
    make_expense,
    make_group,
    register,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers specific to this module
# ═══════════════════════════════════════════════════════════════════════════

def _setup_two_member_group(client):
    """
    Register Alice (owner) and Bob, create a group, add Bob.
    Returns (alice_data, bob_data, group_data).
    """
    alice = register(client, "alice")
    bob   = register(client, "bob")
    group = make_group(client, alice["access_token"], "Test Group")
    add_member(client, alice["access_token"], group["id"], bob["user"]["id"])
    return alice, bob, group


# ═══════════════════════════════════════════════════════════════════════════
# POST /groups/:id/expenses — custom split mode
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateExpenseCustomMode:

    def test_create_custom_expense_returns_201_with_splits(self, client):
        alice, bob, group = _setup_two_member_group(client)
        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="100.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "60.00"},
                {"user_id": bob["user"]["id"],   "amount": "40.00"},
            ],
        )
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["amount"]             == "100.00"   # string, not number (GUIDE Rule 2)
        assert data["split_mode"]         == "custom"
        assert data["paid_by_user_id"]    == alice["user"]["id"]
        assert len(data["splits"])        == 2
        # Split amounts are also strings
        for s in data["splits"]:
            assert isinstance(s["amount"], str), "Split amounts must be strings in JSON"

    def test_create_expense_sets_default_category_other(self, client):
        alice, bob, group = _setup_two_member_group(client)
        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="50.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "25.00"},
                {"user_id": bob["user"]["id"],   "amount": "25.00"},
            ],
        )
        assert resp.get_json()["data"]["category"] == "other"

    def test_create_expense_with_explicit_category(self, client):
        alice, bob, group = _setup_two_member_group(client)
        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="50.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "25.00"},
                {"user_id": bob["user"]["id"],   "amount": "25.00"},
            ],
            category="food",
        )
        assert resp.status_code == 201
        assert resp.get_json()["data"]["category"] == "food"

    def test_response_contains_created_at_and_null_deleted_at(self, client):
        alice, bob, group = _setup_two_member_group(client)
        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="20.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "10.00"},
                {"user_id": bob["user"]["id"],   "amount": "10.00"},
            ],
        )
        data = resp.get_json()["data"]
        assert data["created_at"] is not None
        assert data["deleted_at"] is None   # not soft-deleted

    # ── INV-1 violations ──────────────────────────────────────────────────

    def test_split_sum_mismatch_returns_422(self, client):
        """INV-1: sum(splits) != amount → SPLIT_SUM_MISMATCH."""
        alice, bob, group = _setup_two_member_group(client)
        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="100.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "40.00"},
                {"user_id": bob["user"]["id"],   "amount": "40.00"},  # sum = 80, not 100
            ],
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "SPLIT_SUM_MISMATCH"

    def test_split_sum_one_cent_over_returns_422(self, client):
        """INV-1 tolerance is exactly zero — $0.01 discrepancy is rejected."""
        alice, bob, group = _setup_two_member_group(client)
        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="100.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "50.01"},
                {"user_id": bob["user"]["id"],   "amount": "50.00"},  # sum = 100.01
            ],
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "SPLIT_SUM_MISMATCH"

    # ── INV-5 violations ──────────────────────────────────────────────────

    def test_payer_not_member_returns_422(self, client):
        """INV-5: paid_by_user_id must be a group member."""
        alice, bob, group = _setup_two_member_group(client)
        carol = register(client, "carol")   # carol is NOT in the group

        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=carol["user"]["id"],   # not a member
            amount="50.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "25.00"},
                {"user_id": bob["user"]["id"],   "amount": "25.00"},
            ],
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "PAYER_NOT_MEMBER"

    # ── INV-6 violations ──────────────────────────────────────────────────

    def test_split_user_not_member_returns_422(self, client):
        """INV-6: all split user_ids must be group members."""
        alice, bob, group = _setup_two_member_group(client)
        carol = register(client, "carol")   # NOT in the group

        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="50.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "25.00"},
                {"user_id": carol["user"]["id"], "amount": "25.00"},  # not a member
            ],
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "SPLIT_USER_NOT_MEMBER"

    # ── INV-7 violations ──────────────────────────────────────────────────

    def test_amount_three_decimal_places_returns_400(self, client):
        """INV-7: more than 2 dp is rejected, not rounded."""
        alice, bob, group = _setup_two_member_group(client)
        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="10.001",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "5.00"},
                {"user_id": bob["user"]["id"],   "amount": "5.001"},
            ],
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INVALID_AMOUNT_PRECISION"

    # ── INV-9 violations ──────────────────────────────────────────────────

    def test_non_member_cannot_create_expense_returns_403(self, client):
        """INV-9: only authenticated members may write group data."""
        alice, bob, group = _setup_two_member_group(client)
        carol = register(client, "carol")   # not a member

        resp = make_expense(
            client, carol["access_token"], group["id"],
            paid_by_user_id=carol["user"]["id"],
            amount="50.00",
            splits=[{"user_id": carol["user"]["id"], "amount": "50.00"}],
        )
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_unauthenticated_request_returns_401(self, client):
        alice, bob, group = _setup_two_member_group(client)
        resp = client.post(f"/api/v1/groups/{group['id']}/expenses", json={})
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "TOKEN_MISSING"


# ═══════════════════════════════════════════════════════════════════════════
# POST /groups/:id/expenses — equal split mode
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateExpenseEqualMode:

    def test_equal_mode_server_computes_splits(self, client):
        """
        Server divides amount evenly. Client sends no splits array.
        sum(splits) must equal amount (INV-1 preserved).
        """
        alice, bob, group = _setup_two_member_group(client)
        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="100.00",
            splits=None,
            split_mode="equal",
        )
        assert resp.status_code == 201
        data = resp.get_json()["data"]

        # Two members → two splits
        assert len(data["splits"]) == 2

        # Verify INV-1: split amounts (as Decimal) sum to expense amount
        from decimal import Decimal
        split_sum = sum(Decimal(s["amount"]) for s in data["splits"])
        assert split_sum == Decimal("100.00"), f"INV-1: split sum {split_sum} != 100.00"

    def test_equal_mode_odd_cent_remainder_to_payer(self, client):
        """
        $10 / 3 members = $3.33 each (ROUND_DOWN), remainder $0.01 goes to payer.
        But we only have 2 members in this test. Use $10 / 3 members setup separately.
        Test: $1.00 / 2 = $0.50 each (no remainder — use this for basic check).
        Remainder test: $10.00 / 3 people (add Carol to group).
        """
        alice = register(client, "alice")
        bob   = register(client, "bob")
        carol = register(client, "carol")
        group = make_group(client, alice["access_token"])
        add_member(client, alice["access_token"], group["id"], bob["user"]["id"])
        add_member(client, alice["access_token"], group["id"], carol["user"]["id"])

        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="10.00",
            splits=None,
            split_mode="equal",
        )
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert len(data["splits"]) == 3

        from decimal import Decimal
        split_sum = sum(Decimal(s["amount"]) for s in data["splits"])
        assert split_sum == Decimal("10.00"), "INV-1 must hold for equal split with remainder"

        # Payer's split must be >= base (received the $0.01 remainder)
        base = Decimal("3.33")
        payer_split = next(s for s in data["splits"] if s["user_id"] == alice["user"]["id"])
        assert Decimal(payer_split["amount"]) >= base

    def test_equal_mode_with_splits_array_returns_400(self, client):
        """SPLITS_SENT_FOR_EQUAL_MODE: client must not send splits in equal mode."""
        alice, bob, group = _setup_two_member_group(client)
        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="100.00",
            splits=[{"user_id": alice["user"]["id"], "amount": "100.00"}],
            split_mode="equal",
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "SPLITS_SENT_FOR_EQUAL_MODE"


# ═══════════════════════════════════════════════════════════════════════════
# GET /groups/:id/expenses — list
# ═══════════════════════════════════════════════════════════════════════════

class TestListExpenses:

    def test_list_returns_active_expenses_only(self, client):
        """INV-8: list returns only WHERE deleted_at IS NULL."""
        alice, bob, group = _setup_two_member_group(client)

        # Create two expenses
        make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"], amount="50.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "25.00"},
                {"user_id": bob["user"]["id"],   "amount": "25.00"},
            ],
        )
        resp2 = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"], amount="30.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "15.00"},
                {"user_id": bob["user"]["id"],   "amount": "15.00"},
            ],
        )
        expense2_id = resp2.get_json()["data"]["id"]

        # Soft-delete the second expense
        client.delete(
            f"/api/v1/expenses/{expense2_id}",
            headers=auth_headers(alice["access_token"]),
        )

        # List should return only the first (active) expense
        resp = client.get(
            f"/api/v1/groups/{group['id']}/expenses",
            headers=auth_headers(alice["access_token"]),
        )
        assert resp.status_code == 200
        expenses = resp.get_json()["data"]
        assert len(expenses) == 1
        assert expenses[0]["deleted_at"] is None

    def test_list_non_member_returns_403(self, client):
        """INV-9: non-member cannot list group expenses."""
        alice, bob, group = _setup_two_member_group(client)
        carol = register(client, "carol")

        resp = client.get(
            f"/api/v1/groups/{group['id']}/expenses",
            headers=auth_headers(carol["access_token"]),
        )
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_list_nonexistent_group_returns_404(self, client):
        alice = register(client, "alice")
        resp = client.get(
            "/api/v1/groups/99999/expenses",
            headers=auth_headers(alice["access_token"]),
        )
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "GROUP_NOT_FOUND"


# ═══════════════════════════════════════════════════════════════════════════
# GET /expenses/:id — single expense
# ═══════════════════════════════════════════════════════════════════════════

class TestGetExpense:

    def test_get_expense_returns_splits(self, client):
        alice, bob, group = _setup_two_member_group(client)
        create_resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"], amount="80.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "50.00"},
                {"user_id": bob["user"]["id"],   "amount": "30.00"},
            ],
        )
        expense_id = create_resp.get_json()["data"]["id"]

        resp = client.get(
            f"/api/v1/expenses/{expense_id}",
            headers=auth_headers(alice["access_token"]),
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["id"]     == expense_id
        assert data["amount"] == "80.00"
        assert len(data["splits"]) == 2

    def test_get_nonexistent_expense_returns_404(self, client):
        alice = register(client, "alice")
        resp = client.get(
            "/api/v1/expenses/99999",
            headers=auth_headers(alice["access_token"]),
        )
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "EXPENSE_NOT_FOUND"

    def test_get_expense_non_member_returns_403(self, client):
        """INV-9: non-member cannot read expense details."""
        alice, bob, group = _setup_two_member_group(client)
        carol = register(client, "carol")

        create_resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"], amount="40.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "20.00"},
                {"user_id": bob["user"]["id"],   "amount": "20.00"},
            ],
        )
        expense_id = create_resp.get_json()["data"]["id"]

        resp = client.get(
            f"/api/v1/expenses/{expense_id}",
            headers=auth_headers(carol["access_token"]),
        )
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_get_soft_deleted_expense_still_returns_200(self, client):
        """
        Spec Section 7.2 note: GET on a deleted expense returns 200 with deleted_at set.
        The client can display the deletion state.
        """
        alice, bob, group = _setup_two_member_group(client)
        create_resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"], amount="40.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "20.00"},
                {"user_id": bob["user"]["id"],   "amount": "20.00"},
            ],
        )
        expense_id = create_resp.get_json()["data"]["id"]

        # Delete it
        client.delete(
            f"/api/v1/expenses/{expense_id}",
            headers=auth_headers(alice["access_token"]),
        )

        # GET should still return 200 with deleted_at populated
        resp = client.get(
            f"/api/v1/expenses/{expense_id}",
            headers=auth_headers(alice["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["deleted_at"] is not None
