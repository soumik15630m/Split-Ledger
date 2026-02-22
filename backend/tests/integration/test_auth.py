"""
tests/integration/test_auth.py — Integration tests for authentication endpoints.

Endpoints covered (spec Section 8.1):
  POST /auth/register  → 201
  POST /auth/login     → 200
  POST /auth/refresh   → 200
  POST /auth/logout    → 200
  GET  /auth/me        → 200

Error cases (ARCHITECTURE.md Section 8 Error Code Registry):
  DUPLICATE_EMAIL       409 — email already registered
  DUPLICATE_USERNAME    409 — username already taken
  INVALID_CREDENTIALS   401 — wrong password
  REFRESH_TOKEN_INVALID 401 — invalid/revoked refresh token
  TOKEN_MISSING         401 — no Authorization header
  TOKEN_EXPIRED         401 — expired token (tested via bad token simulation)
  TOKEN_INVALID         401 — malformed token

GUIDE Rule 6: every service function must have a test covering happy + failure paths.
GUIDE Rule (401 vs 403): middleware failures are 401, auth failures are 401,
  group membership failures are 403. This file only tests 401 cases.
"""

from __future__ import annotations

import pytest

from .conftest import auth_headers, register


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/register
# ═══════════════════════════════════════════════════════════════════════════

class TestRegister:

    def test_register_success_returns_201_with_tokens(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "username": "alice",
            "email": "alice@test.com",
            "password": "Password1",
        })
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert "access_token"  in data
        assert "refresh_token" in data
        assert data["user"]["username"] == "alice"
        assert data["user"]["email"]    == "alice@test.com"
        # password_hash must NEVER appear in the response
        assert "password"      not in data["user"]
        assert "password_hash" not in data["user"]

    def test_register_returns_user_id(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "username": "bob",
            "email": "bob@test.com",
            "password": "Password1",
        })
        data = resp.get_json()["data"]
        assert isinstance(data["user"]["id"], int)
        assert data["user"]["id"] > 0

    def test_duplicate_email_returns_409_duplicate_email(self, client):
        client.post("/api/v1/auth/register", json={
            "username": "alice", "email": "shared@test.com", "password": "Password1",
        })
        resp = client.post("/api/v1/auth/register", json={
            "username": "alice2", "email": "shared@test.com", "password": "Password1",
        })
        assert resp.status_code == 409
        error = resp.get_json()["error"]
        assert error["code"] == "DUPLICATE_EMAIL"

    def test_duplicate_username_returns_409_duplicate_username(self, client):
        client.post("/api/v1/auth/register", json={
            "username": "alice", "email": "alice@test.com", "password": "Password1",
        })
        resp = client.post("/api/v1/auth/register", json={
            "username": "alice", "email": "alice2@test.com", "password": "Password1",
        })
        assert resp.status_code == 409
        error = resp.get_json()["error"]
        assert error["code"] == "DUPLICATE_USERNAME"

    def test_short_username_returns_400(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "username": "ab", "email": "x@x.com", "password": "Password1",
        })
        assert resp.status_code == 400

    def test_weak_password_no_digit_returns_400(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "username": "alice", "email": "a@b.com", "password": "password",
        })
        assert resp.status_code == 400

    def test_invalid_email_format_returns_400(self, client):
        resp = client.post("/api/v1/auth/register", json={
            "username": "alice", "email": "notanemail", "password": "Password1",
        })
        assert resp.status_code == 400

    def test_missing_fields_return_400(self, client):
        resp = client.post("/api/v1/auth/register", json={})
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "MISSING_FIELD"


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/login
# ═══════════════════════════════════════════════════════════════════════════

class TestLogin:

    def test_login_success_returns_200_with_tokens(self, client):
        register(client, "alice")
        resp = client.post("/api/v1/auth/login", json={
            "username": "alice", "password": "Password1",
        })
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert "access_token"  in data
        assert "refresh_token" in data
        assert data["user"]["username"] == "alice"

    def test_wrong_password_returns_401_invalid_credentials(self, client):
        register(client, "alice")
        resp = client.post("/api/v1/auth/login", json={
            "username": "alice", "password": "WrongPass1",
        })
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_nonexistent_username_returns_401_invalid_credentials(self, client):
        """Same error code for unknown user and wrong password — avoids enumeration."""
        resp = client.post("/api/v1/auth/login", json={
            "username": "ghost", "password": "Password1",
        })
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_missing_fields_return_400(self, client):
        resp = client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "MISSING_FIELD"


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/refresh
# ═══════════════════════════════════════════════════════════════════════════

class TestRefresh:

    def test_refresh_returns_new_access_token(self, client):
        data = register(client, "alice")
        original_token = data["access_token"]
        refresh_token  = data["refresh_token"]

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        new_token = resp.get_json()["data"]["access_token"]
        assert new_token != original_token, "A new access token must be issued"

    def test_invalid_refresh_token_returns_401(self, client):
        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": "completely_invalid_token_value",
        })
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "REFRESH_TOKEN_INVALID"

    def test_revoked_refresh_token_returns_401(self, client):
        """After logout, the refresh token is revoked and must not be reusable."""
        data          = register(client, "alice")
        access_token  = data["access_token"]
        refresh_token = data["refresh_token"]

        # Logout to revoke the token
        client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
            headers=auth_headers(access_token),
        )

        # Attempt to use the revoked token
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "REFRESH_TOKEN_INVALID"

    def test_missing_refresh_token_field_returns_400(self, client):
        resp = client.post("/api/v1/auth/refresh", json={})
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "MISSING_FIELD"


# ═══════════════════════════════════════════════════════════════════════════
# POST /auth/logout
# ═══════════════════════════════════════════════════════════════════════════

class TestLogout:

    def test_logout_success_returns_200(self, client):
        data = register(client, "alice")
        resp = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": data["refresh_token"]},
            headers=auth_headers(data["access_token"]),
        )
        assert resp.status_code == 200
        assert "message" in resp.get_json()["data"]

    def test_logout_requires_auth(self, client):
        """Logout endpoint requires a valid access token."""
        resp = client.post("/api/v1/auth/logout", json={"refresh_token": "anything"})
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "TOKEN_MISSING"

    def test_double_logout_returns_401(self, client):
        """Revoking an already-revoked token returns REFRESH_TOKEN_INVALID."""
        data = register(client, "alice")
        headers = auth_headers(data["access_token"])
        payload = {"refresh_token": data["refresh_token"]}

        client.post("/api/v1/auth/logout", json=payload, headers=headers)
        resp = client.post("/api/v1/auth/logout", json=payload, headers=headers)
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "REFRESH_TOKEN_INVALID"


# ═══════════════════════════════════════════════════════════════════════════
# GET /auth/me
# ═══════════════════════════════════════════════════════════════════════════

class TestMe:

    def test_me_returns_user_profile(self, client):
        data = register(client, "alice")
        resp = client.get("/api/v1/auth/me", headers=auth_headers(data["access_token"]))
        assert resp.status_code == 200
        user = resp.get_json()["data"]
        assert user["username"] == "alice"
        assert user["email"]    == "alice@test.com"
        assert "id" in user
        assert "created_at" in user
        assert "password_hash" not in user

    def test_me_without_token_returns_401_token_missing(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "TOKEN_MISSING"

    def test_me_with_invalid_token_returns_401_token_invalid(self, client):
        resp = client.get("/api/v1/auth/me", headers=auth_headers("bad.token.here"))
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "TOKEN_INVALID"

    def test_me_with_malformed_bearer_header_returns_401(self, client):
        """Authorization header must be 'Bearer <token>', not just the token."""
        resp = client.get("/api/v1/auth/me", headers={"Authorization": "notbearer xyz"})
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "TOKEN_INVALID"


# ═══════════════════════════════════════════════════════════════════════════
# Error envelope format
# ═══════════════════════════════════════════════════════════════════════════

class TestErrorEnvelope:

    def test_error_response_has_correct_envelope(self, client):
        """
        ARCHITECTURE.md Section 8: error responses must use the standard envelope.
        { "error": { "code": "...", "message": "..." } }
        """
        resp = client.post("/api/v1/auth/login", json={
            "username": "nobody", "password": "Password1",
        })
        body = resp.get_json()
        assert "error" in body
        error = body["error"]
        assert "code"    in error
        assert "message" in error
        # Stack traces must never appear in error responses
        assert "traceback" not in body
        assert "Traceback" not in str(body)

    def test_success_response_has_data_and_warnings_keys(self, client):
        """
        Spec Section 8: success responses: {"data": {...}, "warnings": []}.
        """
        resp = client.post("/api/v1/auth/register", json={
            "username": "carol",
            "email": "carol@test.com",
            "password": "Password1",
        })
        body = resp.get_json()
        assert "data"     in body
        assert "warnings" in body
