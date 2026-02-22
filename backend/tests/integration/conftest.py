"""
tests/integration/conftest.py — Fixtures and helpers for all integration tests.

Design (ARCHITECTURE.md Section 9 Level 2):
  - Tests run against a real PostgreSQL database (splitledger_test).
  - The app is created once per session using create_app("testing").
  - All tables are created once via db.create_all() at session start.
  - Between tests, all rows are deleted in FK-safe order so tests are isolated.
    This is cheaper than nested transactions and avoids complications from the
    DEFERRABLE trigger (002_add_split_sum_trigger.py).
  - PostgreSQL enum types (split_mode_enum, category_enum) are created explicitly
    before db.create_all() because they are defined in Alembic migrations
    (create_type=False in the models means SQLAlchemy does not auto-create them).

Helper functions (not fixtures) are provided for common operations:
  - register(client, ...)    → dict with user + tokens
  - login(client, ...)       → dict with user + tokens
  - auth_headers(token)      → {"Authorization": "Bearer <token>"}
  - make_group(client, ...)  → group dict
  - add_member(...)          → HTTP response
  - make_expense(...)        → HTTP response

These are plain functions (not pytest fixtures) so they can be called with
arbitrary arguments in any test without fixture parameterization overhead.

GUIDE Rule 9 (implied): tests must cover happy paths AND failure paths.
GUIDE Rule 6: tests are required for all service functions.
"""

from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db as _db


# ═══════════════════════════════════════════════════════════════════════════
# Session-scoped app fixture
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def app():
    """
    Creates the Flask application in 'testing' mode once for the entire test session.

    Steps:
      1. Create app with TestingConfig (uses splitledger_test DB).
      2. Create PostgreSQL enum types that the models use but Alembic manages.
         (Models set create_type=False — they expect the type to already exist.)
      3. Run db.create_all() to create all tables.
      4. Yield the app for the test session.
      5. Drop all tables at teardown.
    """
    flask_app = create_app("testing")

    with flask_app.app_context():
        from sqlalchemy import text

        # Create enum types first (create_type=False in models means SQLAlchemy
        # won't create them automatically).
        with _db.engine.connect() as conn:
            conn.execute(text(
                "DO $$ BEGIN "
                "CREATE TYPE split_mode_enum AS ENUM ('equal', 'custom'); "
                "EXCEPTION WHEN duplicate_object THEN NULL; "
                "END $$;"
            ))
            conn.execute(text(
                "DO $$ BEGIN "
                "CREATE TYPE category_enum AS ENUM ("
                "'food','transport','accommodation',"
                "'entertainment','utilities','other'"
                "); "
                "EXCEPTION WHEN duplicate_object THEN NULL; "
                "END $$;"
            ))
            conn.commit()

        _db.create_all()

    yield flask_app

    with flask_app.app_context():
        _db.drop_all()


# ═══════════════════════════════════════════════════════════════════════════
# Function-scoped test isolation
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def clean_tables(app):
    """
    Deletes all rows between tests in FK-safe order.

    autouse=True means this runs before and after EVERY test in the integration
    suite without needing to be declared in each test function.

    Delete order respects FK RESTRICT constraints:
      splits, settlements, expenses must be deleted before memberships/groups/users.
      refresh_tokens deleted before users (CASCADE would handle it, but be explicit).
    """
    yield  # run the test

    with app.app_context():
        _db.session.rollback()  # discard any uncommitted state from a failed test

        from sqlalchemy import text
        with _db.engine.connect() as conn:
            conn.execute(text("DELETE FROM splits"))
            conn.execute(text("DELETE FROM settlements"))
            conn.execute(text("DELETE FROM expenses"))
            conn.execute(text("DELETE FROM memberships"))
            conn.execute(text("DELETE FROM refresh_tokens"))
            conn.execute(text("DELETE FROM groups"))
            conn.execute(text("DELETE FROM users"))
            conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Client fixture
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def client(app):
    """Flask test client. Each test gets a fresh client (function-scoped)."""
    return app.test_client()


# ═══════════════════════════════════════════════════════════════════════════
# Shared helper functions (not fixtures)
# ═══════════════════════════════════════════════════════════════════════════

def register(
    client,
    username: str = "alice",
    email: str | None = None,
    password: str = "Password1",
) -> dict:
    """
    Registers a new user and returns the full response data dict.
    Returns: {"user": {...}, "access_token": "...", "refresh_token": "..."}
    """
    if email is None:
        email = f"{username}@test.com"
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert resp.status_code == 201, f"register failed: {resp.get_json()}"
    return resp.get_json()["data"]


def login(client, username: str, password: str = "Password1") -> dict:
    """
    Logs in a user and returns the response data dict.
    Returns: {"user": {...}, "access_token": "...", "refresh_token": "..."}
    """
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"login failed: {resp.get_json()}"
    return resp.get_json()["data"]


def auth_headers(token: str) -> dict:
    """Returns the Authorization header dict for use in test requests."""
    return {"Authorization": f"Bearer {token}"}


def make_group(client, token: str, name: str = "Test Group") -> dict:
    """
    Creates a group and returns the group data dict.
    The caller (token owner) becomes the group owner and first member.
    """
    resp = client.post(
        "/api/v1/groups/",
        json={"name": name},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, f"make_group failed: {resp.get_json()}"
    return resp.get_json()["data"]


def add_member(client, token: str, group_id: int, user_id: int):
    """Adds a user to a group (owner token required). Returns the HTTP response."""
    return client.post(
        f"/api/v1/groups/{group_id}/members",
        json={"user_id": user_id},
        headers=auth_headers(token),
    )


def make_expense(
    client,
    token: str,
    group_id: int,
    paid_by_user_id: int,
    amount: str,
    splits: list[dict] | None = None,
    description: str = "Test Expense",
    split_mode: str = "custom",
    category: str = "other",
):
    """
    Creates an expense and returns the HTTP response.
    For split_mode='equal', do not pass splits — pass None (server computes them).
    For split_mode='custom', pass splits as a list of {user_id, amount} dicts.
    """
    payload: dict = {
        "paid_by_user_id": paid_by_user_id,
        "description": description,
        "amount": amount,
        "split_mode": split_mode,
        "category": category,
    }
    if splits is not None:
        payload["splits"] = splits

    return client.post(
        f"/api/v1/groups/{group_id}/expenses",
        json=payload,
        headers=auth_headers(token),
    )
