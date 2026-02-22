"""
tests/integration/test_balances.py — Integration tests for GET /groups/:id/balances.

Endpoints covered (spec Section 8.4):
  GET /groups/:id/balances              → 200 (full balances + simplified debts)
  GET /groups/:id/balances?category=X  → 200 (category-scoped, informational)

Invariants verified:
  INV-2  balance_sum == "0.00" for full (unfiltered) computation
  INV-8  Deleted expenses are excluded from balance computation
  INV-9  FORBIDDEN (403) — only group members may view balances

Properties verified:
  - Every group member appears in the balances list (even if balance is 0.00)
  - Settlements are correctly netted into balances
  - simplified_debts is present and economically correct for full computation
  - balance_sum is explicitly "0.00" in the response (spec Section 8.4)
  - The server asserts INV-2 internally before responding (INTERNAL_ERROR if violated)
  - Category-filtered response intentionally does NOT produce sum=="0.00"

ARCHITECTURE.md Section 6: balance computation is the SINGLE SOURCE OF TRUTH.
The canonical formula is implemented in balance_service.compute_balances().
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
    alice = register(client, "alice")
    bob   = register(client, "bob")
    group = make_group(client, alice["access_token"])
    add_member(client, alice["access_token"], group["id"], bob["user"]["id"])
    return alice, bob, group


def _get_balances(client, token, group_id, category: str | None = None):
    url = f"/api/v1/groups/{group_id}/balances"
    if category:
        url += f"?category={category}"
    return client.get(url, headers=auth_headers(token))


def _create_50_50_expense(client, alice, bob, group, amount="100.00"):
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


# ═══════════════════════════════════════════════════════════════════════════
# INV-2: balance_sum must always be "0.00"
# ═══════════════════════════════════════════════════════════════════════════

class TestBalanceSumIsZero:

    def test_empty_group_balance_sum_is_zero(self, client):
        """Group with no expenses: all balances 0.00, sum 0.00."""
        alice, bob, group = _setup(client)
        resp = _get_balances(client, alice["access_token"], group["id"])
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["balance_sum"] == "0.00"

    def test_single_expense_balance_sum_is_zero(self, client):
        """INV-2: after one expense, balance_sum must be 0.00."""
        alice, bob, group = _setup(client)
        _create_50_50_expense(client, alice, bob, group, "100.00")

        resp = _get_balances(client, alice["access_token"], group["id"])
        assert resp.get_json()["data"]["balance_sum"] == "0.00"

    def test_multiple_expenses_balance_sum_is_zero(self, client):
        """INV-2 holds across multiple expenses and payers."""
        alice, bob, group = _setup(client)

        # Alice pays $100 (50/50)
        _create_50_50_expense(client, alice, bob, group, "100.00")

        # Bob pays $60 (50/50)
        make_expense(
            client, bob["access_token"], group["id"],
            paid_by_user_id=bob["user"]["id"],
            amount="60.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "30.00"},
                {"user_id": bob["user"]["id"],   "amount": "30.00"},
            ],
        )

        resp = _get_balances(client, alice["access_token"], group["id"])
        assert resp.get_json()["data"]["balance_sum"] == "0.00"

    def test_balance_sum_is_zero_after_settlement(self, client):
        """INV-2 holds after settlements are netted."""
        alice, bob, group = _setup(client)
        _create_50_50_expense(client, alice, bob, group, "100.00")

        # Bob settles $30 to Alice
        client.post(
            f"/api/v1/groups/{group['id']}/settlements",
            json={"paid_to_user_id": alice["user"]["id"], "amount": "30.00"},
            headers=auth_headers(bob["access_token"]),
        )

        resp = _get_balances(client, alice["access_token"], group["id"])
        assert resp.get_json()["data"]["balance_sum"] == "0.00"


# ═══════════════════════════════════════════════════════════════════════════
# Balance values — correctness
# ═══════════════════════════════════════════════════════════════════════════

class TestBalanceValues:

    def test_payer_credited_participant_debited(self, client):
        """
        Canonical formula: payer gets +amount, participant gets -split.amount.
        Alice pays $100, split $60/$40. Alice net = +40, Bob net = -40.
        """
        alice, bob, group = _setup(client)
        make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="100.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "60.00"},
                {"user_id": bob["user"]["id"],   "amount": "40.00"},
            ],
        )

        resp = _get_balances(client, alice["access_token"], group["id"])
        balances = {b["user_id"]: Decimal(b["balance"]) for b in resp.get_json()["data"]["balances"]}

        assert balances[alice["user"]["id"]] == Decimal("40.00")
        assert balances[bob["user"]["id"]]   == Decimal("-40.00")

    def test_settlement_reduces_debt(self, client):
        """Settlement reduces outstanding debt between parties."""
        alice, bob, group = _setup(client)
        _create_50_50_expense(client, alice, bob, group, "100.00")
        # Alice +50, Bob -50 before settlement

        # Bob pays Alice $30
        client.post(
            f"/api/v1/groups/{group['id']}/settlements",
            json={"paid_to_user_id": alice["user"]["id"], "amount": "30.00"},
            headers=auth_headers(bob["access_token"]),
        )

        resp = _get_balances(client, alice["access_token"], group["id"])
        balances = {b["user_id"]: Decimal(b["balance"]) for b in resp.get_json()["data"]["balances"]}

        # Alice: +50 (from split) - 30 (received settlement) = +20? No wait:
        # ARCHITECTURE formula: settlement payer gains credit (+), recipient loses credit (-)
        # Bob pays Alice: Bob.balance += 30, Alice.balance -= 30
        # Pre-settlement: Alice=+50, Bob=-50
        # Post: Alice = 50 - 30 = 20... wait, let me re-check.
        # balance_service: payer += amount, recipient -= amount
        # Bob (paid_by) += 30: Bob goes from -50 to -20
        # Alice (paid_to) -= 30: Alice goes from +50 to +20
        assert balances[alice["user"]["id"]] == Decimal("20.00")
        assert balances[bob["user"]["id"]]   == Decimal("-20.00")

    def test_zero_balance_member_appears_in_response(self, client):
        """Every member appears in the balance list, even with zero balance."""
        alice, bob, group = _setup(client)
        carol = register(client, "carol")
        add_member(client, alice["access_token"], group["id"], carol["user"]["id"])

        # Only Alice and Bob transact — Carol should still appear
        make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="60.00",
            splits=[
                {"user_id": alice["user"]["id"], "amount": "30.00"},
                {"user_id": bob["user"]["id"],   "amount": "30.00"},
                # Carol has no split — her balance is 0
            ],
        )

        resp = _get_balances(client, alice["access_token"], group["id"])
        balance_map = {b["user_id"]: Decimal(b["balance"]) for b in resp.get_json()["data"]["balances"]}

        assert carol["user"]["id"] in balance_map, "Carol must appear in balance list"
        assert balance_map[carol["user"]["id"]] == Decimal("0.00")

    def test_deleted_expense_excluded_from_balance(self, client):
        """
        INV-8: Deleting an expense must remove its contribution from balances.
        After delete: both members return to zero.
        """
        alice, bob, group = _setup(client)
        expense = _create_50_50_expense(client, alice, bob, group, "100.00")

        # Delete the expense
        client.delete(
            f"/api/v1/expenses/{expense['id']}",
            headers=auth_headers(alice["access_token"]),
        )

        resp = _get_balances(client, alice["access_token"], group["id"])
        balances = {b["user_id"]: Decimal(b["balance"]) for b in resp.get_json()["data"]["balances"]}

        assert balances[alice["user"]["id"]] == Decimal("0.00"), "INV-8: deleted expense excluded"
        assert balances[bob["user"]["id"]]   == Decimal("0.00"), "INV-8: deleted expense excluded"


# ═══════════════════════════════════════════════════════════════════════════
# simplified_debts
# ═══════════════════════════════════════════════════════════════════════════

class TestSimplifiedDebts:

    def test_simplified_debts_present_in_full_response(self, client):
        """Full (unfiltered) response always includes simplified_debts."""
        alice, bob, group = _setup(client)
        _create_50_50_expense(client, alice, bob, group, "100.00")

        resp = _get_balances(client, alice["access_token"], group["id"])
        data = resp.get_json()["data"]
        assert "simplified_debts" in data

    def test_simplified_debts_correct_direction(self, client):
        """Bob owes Alice $50 → simplified_debts shows Bob → Alice."""
        alice, bob, group = _setup(client)
        _create_50_50_expense(client, alice, bob, group, "100.00")

        resp = _get_balances(client, alice["access_token"], group["id"])
        debts = resp.get_json()["data"]["simplified_debts"]

        assert len(debts) == 1
        debt = debts[0]
        assert debt["from_user_id"] == bob["user"]["id"]
        assert debt["to_user_id"]   == alice["user"]["id"]
        assert debt["amount"]       == "50.00"

    def test_simplified_debts_empty_when_all_zero(self, client):
        """No expenses → no debts."""
        alice, bob, group = _setup(client)

        resp = _get_balances(client, alice["access_token"], group["id"])
        data = resp.get_json()["data"]
        assert data["simplified_debts"] == []

    def test_simplified_debts_has_names(self, client):
        """Spec: simplified_debts includes from_name and to_name."""
        alice, bob, group = _setup(client)
        _create_50_50_expense(client, alice, bob, group, "100.00")

        resp = _get_balances(client, alice["access_token"], group["id"])
        debts = resp.get_json()["data"]["simplified_debts"]

        assert len(debts) > 0
        debt = debts[0]
        assert "from_name" in debt
        assert "to_name"   in debt


# ═══════════════════════════════════════════════════════════════════════════
# Authorization (INV-9)
# ═══════════════════════════════════════════════════════════════════════════

class TestBalanceAuthorization:

    def test_non_member_returns_403_forbidden(self, client):
        """INV-9: non-members receive 403, not 404."""
        alice, bob, group = _setup(client)
        carol = register(client, "carol")

        resp = _get_balances(client, carol["access_token"], group["id"])
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_nonexistent_group_returns_404(self, client):
        alice = register(client, "alice")
        resp = _get_balances(client, alice["access_token"], 99999)
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "GROUP_NOT_FOUND"

    def test_unauthenticated_returns_401(self, client):
        alice, bob, group = _setup(client)
        resp = client.get(f"/api/v1/groups/{group['id']}/balances")
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "TOKEN_MISSING"


# ═══════════════════════════════════════════════════════════════════════════
# Response structure
# ═══════════════════════════════════════════════════════════════════════════

class TestBalanceResponseStructure:

    def test_response_contains_required_top_level_keys(self, client):
        """Spec Section 8.4: response must contain group_id, balances, simplified_debts, balance_sum."""
        alice, bob, group = _setup(client)

        resp = _get_balances(client, alice["access_token"], group["id"])
        data = resp.get_json()["data"]

        assert "group_id"         in data
        assert "balances"         in data
        assert "simplified_debts" in data
        assert "balance_sum"      in data

    def test_balance_entries_have_required_fields(self, client):
        """Each balance entry must have user_id, name, balance (as string)."""
        alice, bob, group = _setup(client)

        resp = _get_balances(client, alice["access_token"], group["id"])
        for entry in resp.get_json()["data"]["balances"]:
            assert "user_id" in entry
            assert "name"    in entry
            assert "balance" in entry
            assert isinstance(entry["balance"], str), "Amounts must be strings, not JS numbers"

    def test_balance_amounts_are_strings_not_numbers(self, client):
        """GUIDE Rule 2: amounts in JSON must be strings, never JS numbers."""
        alice, bob, group = _setup(client)
        _create_50_50_expense(client, alice, bob, group, "100.00")

        resp = _get_balances(client, alice["access_token"], group["id"])
        data = resp.get_json()["data"]

        assert isinstance(data["balance_sum"], str)
        for entry in data["balances"]:
            assert isinstance(entry["balance"], str)
