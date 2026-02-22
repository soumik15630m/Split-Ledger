"""
tests/integration/test_settlements.py — Integration tests for settlement endpoints.

Endpoints covered (spec Section 8.5):
  POST /groups/:id/settlements → 201 (create settlement)
  GET  /groups/:id/settlements → 200 (list settlements)

Invariants verified:
  INV-3  OVERPAYMENT warning (201) — settlement > current debt is still recorded
  INV-4  SELF_SETTLEMENT (422)     — paid_by cannot equal paid_to
  INV-5  PAYER_NOT_MEMBER (422)    — paid_by must be a group member (enforced by INV-9 guard)
  INV-7  Decimal, > 0, max 2dp    — amount precision enforced by schema
  INV-9  FORBIDDEN (403)           — only members can create/list settlements

Notes:
  - paid_by_user_id is taken from flask.g (the authenticated caller), NOT from the request body.
    The schema only accepts paid_to_user_id and amount.
  - INV-4 (self-settlement) cannot be checked by the schema because it requires the caller's
    user_id from flask.g. It is enforced in settlement_service.py.
  - The OVERPAYMENT warning appears in the "warnings" array alongside the 201 response.
    The settlement is still recorded — pre-payment is valid business logic (INV-3).

GUIDE Rule 6: happy path + failure path for every service function.
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
    """Alice (owner) + Bob (member) + group."""
    alice = register(client, "alice")
    bob   = register(client, "bob")
    group = make_group(client, alice["access_token"])
    add_member(client, alice["access_token"], group["id"], bob["user"]["id"])
    return alice, bob, group


def _create_debt(client, alice, bob, group, amount="100.00"):
    """Alice pays $amount, split 50/50. Bob owes Alice $amount/2."""
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


def _settle(client, payer_token, group_id, paid_to_id, amount: str):
    """POSTs a settlement and returns the HTTP response."""
    return client.post(
        f"/api/v1/groups/{group_id}/settlements",
        json={"paid_to_user_id": paid_to_id, "amount": amount},
        headers=auth_headers(payer_token),
    )


# ═══════════════════════════════════════════════════════════════════════════
# POST /groups/:id/settlements — happy path
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateSettlement:

    def test_create_settlement_returns_201(self, client):
        """Happy path: Bob settles $50 debt to Alice."""
        alice, bob, group = _setup(client)
        _create_debt(client, alice, bob, group, "100.00")

        resp = _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "50.00")
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["paid_by_user_id"] == bob["user"]["id"]
        assert data["paid_to_user_id"] == alice["user"]["id"]
        assert data["amount"]          == "50.00"   # string, not number
        assert data["group_id"]        == group["id"]

    def test_settlement_amount_is_string_in_json(self, client):
        """GUIDE Rule 2: monetary amounts in API responses must be strings."""
        alice, bob, group = _setup(client)
        _create_debt(client, alice, bob, group)

        resp = _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "25.00")
        data = resp.get_json()["data"]
        assert isinstance(data["amount"], str), "Settlement amount must be a string in JSON"

    def test_settlement_has_empty_warnings_when_no_overpayment(self, client):
        """Settlement within the outstanding debt produces no warnings."""
        alice, bob, group = _setup(client)
        _create_debt(client, alice, bob, group, "100.00")
        # Bob owes Alice $50. Paying exactly $50 → no warning.

        resp = _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "50.00")
        assert resp.status_code == 201
        assert resp.get_json()["warnings"] == []

    def test_settlement_reduces_balance(self, client):
        """After a settlement, Bob's balance improves by the settlement amount."""
        alice, bob, group = _setup(client)
        _create_debt(client, alice, bob, group, "100.00")
        # Before: Alice +50, Bob -50

        _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "30.00")

        resp = client.get(
            f"/api/v1/groups/{group['id']}/balances",
            headers=auth_headers(alice["access_token"]),
        )
        balances = {b["user_id"]: Decimal(b["balance"]) for b in resp.get_json()["data"]["balances"]}

        # Alice: +50 - 30 (received) = +20
        # Bob:   -50 + 30 (paid)     = -20
        assert balances[alice["user"]["id"]] == Decimal("20.00")
        assert balances[bob["user"]["id"]]   == Decimal("-20.00")

    def test_full_settlement_zeroes_out_debt(self, client):
        """Paying the exact outstanding debt brings both parties to 0.00."""
        alice, bob, group = _setup(client)
        _create_debt(client, alice, bob, group, "60.00")
        # Bob owes Alice $30

        _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "30.00")

        resp = client.get(
            f"/api/v1/groups/{group['id']}/balances",
            headers=auth_headers(alice["access_token"]),
        )
        balances = {b["user_id"]: Decimal(b["balance"]) for b in resp.get_json()["data"]["balances"]}
        assert balances[alice["user"]["id"]] == Decimal("0.00")
        assert balances[bob["user"]["id"]]   == Decimal("0.00")

    def test_settlement_has_created_at(self, client):
        alice, bob, group = _setup(client)
        _create_debt(client, alice, bob, group)

        resp = _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "10.00")
        assert resp.get_json()["data"]["created_at"] is not None


# ═══════════════════════════════════════════════════════════════════════════
# INV-3: Overpayment warning
# ═══════════════════════════════════════════════════════════════════════════

class TestOverpaymentWarning:

    def test_overpayment_returns_201_with_warning(self, client):
        """
        INV-3: Settlement > current debt is valid (pre-payment).
        Returns 201 but includes OVERPAYMENT in warnings.
        The settlement IS recorded.
        """
        alice, bob, group = _setup(client)
        _create_debt(client, alice, bob, group, "100.00")
        # Bob owes Alice $50. Paying $100 is an overpayment.

        resp = _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "100.00")
        assert resp.status_code == 201, "Overpayment must still return 201"

        warnings = resp.get_json()["warnings"]
        assert len(warnings) > 0, "Overpayment must produce a warning"
        codes = [w["code"] for w in warnings]
        assert "OVERPAYMENT" in codes, f"Expected OVERPAYMENT warning, got: {codes}"

    def test_overpayment_settlement_is_recorded(self, client):
        """Overpayment warning does not block the settlement from being saved."""
        alice, bob, group = _setup(client)
        _create_debt(client, alice, bob, group, "100.00")

        resp = _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "200.00")
        assert resp.status_code == 201

        # Verify it appears in the settlement list
        list_resp = client.get(
            f"/api/v1/groups/{group['id']}/settlements",
            headers=auth_headers(alice["access_token"]),
        )
        settlements = list_resp.get_json()["data"]
        amounts = [Decimal(s["amount"]) for s in settlements]
        assert Decimal("200.00") in amounts

    def test_no_prior_debt_still_records_settlement_with_warning(self, client):
        """
        A settlement with no prior debt (completely forward-paying) still gets
        recorded with an OVERPAYMENT warning. Pre-payment is valid business logic.
        """
        alice, bob, group = _setup(client)
        # No expenses → no debt. Bob pays Alice anyway.

        resp = _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "50.00")
        assert resp.status_code == 201
        codes = [w["code"] for w in resp.get_json()["warnings"]]
        assert "OVERPAYMENT" in codes

    def test_overpayment_uses_bilateral_outstanding(self, client):
        """
        OVERPAYMENT must be evaluated against debt between the two parties, not
        broad net balances across the whole group.

        Scenario:
          - Bob owes Alice 20.00
          - Bob owes Carol 80.00
          - Carol owes Alice 100.00
        Net balances: Alice +120, Bob -100, Carol -20.
        Bob paying Alice 50.00 is an overpayment bilaterally (50 > 20), so a
        warning must be returned.
        """
        alice = register(client, "alice")
        bob = register(client, "bob")
        carol = register(client, "carol")
        group = make_group(client, alice["access_token"])
        add_member(client, alice["access_token"], group["id"], bob["user"]["id"])
        add_member(client, alice["access_token"], group["id"], carol["user"]["id"])

        # Bob owes Alice 20.00
        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="20.00",
            splits=[{"user_id": bob["user"]["id"], "amount": "20.00"}],
        )
        assert resp.status_code == 201

        # Bob owes Carol 80.00
        resp = make_expense(
            client, carol["access_token"], group["id"],
            paid_by_user_id=carol["user"]["id"],
            amount="80.00",
            splits=[{"user_id": bob["user"]["id"], "amount": "80.00"}],
        )
        assert resp.status_code == 201

        # Carol owes Alice 100.00 (inflates Alice's global credit)
        resp = make_expense(
            client, alice["access_token"], group["id"],
            paid_by_user_id=alice["user"]["id"],
            amount="100.00",
            splits=[{"user_id": carol["user"]["id"], "amount": "100.00"}],
        )
        assert resp.status_code == 201

        # Bob pays Alice more than his bilateral debt to Alice.
        settle_resp = _settle(
            client,
            bob["access_token"],
            group["id"],
            alice["user"]["id"],
            "50.00",
        )
        assert settle_resp.status_code == 201
        codes = [w["code"] for w in settle_resp.get_json()["warnings"]]
        assert "OVERPAYMENT" in codes


# ═══════════════════════════════════════════════════════════════════════════
# INV-4: Self-settlement
# ═══════════════════════════════════════════════════════════════════════════

class TestSelfSettlement:

    def test_self_settlement_returns_422(self, client):
        """INV-4: paid_by == paid_to → SELF_SETTLEMENT (422)."""
        alice, bob, group = _setup(client)

        # Alice tries to settle with herself
        resp = _settle(
            client, alice["access_token"], group["id"],
            paid_to_id=alice["user"]["id"],  # same as caller
            amount="50.00",
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "SELF_SETTLEMENT"

    def test_self_settlement_not_recorded(self, client):
        """The rejected self-settlement must not appear in the settlement list."""
        alice, bob, group = _setup(client)

        _settle(client, alice["access_token"], group["id"], alice["user"]["id"], "50.00")

        list_resp = client.get(
            f"/api/v1/groups/{group['id']}/settlements",
            headers=auth_headers(alice["access_token"]),
        )
        assert list_resp.get_json()["data"] == [], "Self-settlement must not be persisted"


# ═══════════════════════════════════════════════════════════════════════════
# INV-5 / Membership checks
# ═══════════════════════════════════════════════════════════════════════════

class TestMembershipChecks:

    def test_recipient_not_member_returns_422(self, client):
        """paid_to_user_id must be a group member (RECIPIENT_NOT_MEMBER)."""
        alice, bob, group = _setup(client)
        carol = register(client, "carol")   # not in the group

        resp = _settle(
            client, alice["access_token"], group["id"],
            paid_to_id=carol["user"]["id"],
            amount="20.00",
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "RECIPIENT_NOT_MEMBER"

    def test_non_member_cannot_create_settlement_returns_403(self, client):
        """INV-9: only group members may create settlements."""
        alice, bob, group = _setup(client)
        carol = register(client, "carol")   # not in the group

        resp = _settle(
            client, carol["access_token"], group["id"],
            paid_to_id=alice["user"]["id"],
            amount="20.00",
        )
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_nonexistent_group_returns_404(self, client):
        alice = register(client, "alice")
        resp = _settle(client, alice["access_token"], 99999, 2, "10.00")
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "GROUP_NOT_FOUND"


# ═══════════════════════════════════════════════════════════════════════════
# Schema validation
# ═══════════════════════════════════════════════════════════════════════════

class TestSettlementSchemaValidation:

    def test_amount_three_decimal_places_returns_400(self, client):
        """INV-7: amount with >2dp is rejected."""
        alice, bob, group = _setup(client)
        resp = _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "10.001")
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INVALID_AMOUNT_PRECISION"

    def test_zero_amount_returns_400(self, client):
        alice, bob, group = _setup(client)
        resp = _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "0.00")
        assert resp.status_code == 400

    def test_missing_amount_returns_400(self, client):
        alice, bob, group = _setup(client)
        resp = client.post(
            f"/api/v1/groups/{group['id']}/settlements",
            json={"paid_to_user_id": alice["user"]["id"]},
            headers=auth_headers(bob["access_token"]),
        )
        assert resp.status_code == 400

    def test_unauthenticated_returns_401(self, client):
        alice, bob, group = _setup(client)
        resp = client.post(f"/api/v1/groups/{group['id']}/settlements", json={})
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "TOKEN_MISSING"


# ═══════════════════════════════════════════════════════════════════════════
# GET /groups/:id/settlements — list
# ═══════════════════════════════════════════════════════════════════════════

class TestListSettlements:

    def test_list_settlements_returns_200(self, client):
        alice, bob, group = _setup(client)
        _create_debt(client, alice, bob, group)
        _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "25.00")

        resp = client.get(
            f"/api/v1/groups/{group['id']}/settlements",
            headers=auth_headers(alice["access_token"]),
        )
        assert resp.status_code == 200
        settlements = resp.get_json()["data"]
        assert len(settlements) == 1
        assert settlements[0]["amount"] == "25.00"

    def test_list_empty_before_any_settlements(self, client):
        alice, bob, group = _setup(client)
        resp = client.get(
            f"/api/v1/groups/{group['id']}/settlements",
            headers=auth_headers(alice["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []

    def test_list_non_member_returns_403(self, client):
        alice, bob, group = _setup(client)
        carol = register(client, "carol")

        resp = client.get(
            f"/api/v1/groups/{group['id']}/settlements",
            headers=auth_headers(carol["access_token"]),
        )
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_list_settlement_amounts_are_strings(self, client):
        """GUIDE Rule 2: amounts in list response must be strings."""
        alice, bob, group = _setup(client)
        _create_debt(client, alice, bob, group)
        _settle(client, bob["access_token"], group["id"], alice["user"]["id"], "10.00")

        resp = client.get(
            f"/api/v1/groups/{group['id']}/settlements",
            headers=auth_headers(alice["access_token"]),
        )
        for s in resp.get_json()["data"]:
            assert isinstance(s["amount"], str)
