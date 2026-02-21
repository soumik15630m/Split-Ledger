# SplitLedger — Architecture & Design Reference

**Version:** 2.1.0  
**Status:** Active  
**Companion documents:** `README.md`, `CLAUDE.md`, `AI_USAGE.md`

This document explains *why* the system is designed the way it is. It is not a tutorial. It is the reference a developer should read before making structural changes, and the document an AI agent must read before modifying service or schema code.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Layer Architecture](#2-layer-architecture)
3. [Domain Model](#3-domain-model)
4. [Core Invariants](#4-core-invariants)
5. [API Contract](#5-api-contract)
6. [Business Logic](#6-business-logic)
7. [Authentication Design](#7-authentication-design)
8. [Error Handling](#8-error-handling)
9. [Testing Strategy](#9-testing-strategy)
10. [Extension Points (v2+)](#10-extension-points-v2)

---

## 1. System Overview

SplitLedger records who paid for what within a group and computes the minimal set of transactions to bring all member balances to zero. The core insight is that **balances are derived, never stored** — every figure shown to the user is computed live from immutable (or soft-deleted) source records.

```
                    ┌────────────────────────────────────────────┐
                    │               React Frontend               │
                    │  TypeScript + Zod validation               │
                    └────────────────────┬───────────────────────┘
                                         │ HTTPS  /api/v1/*
                    ┌────────────────────▼───────────────────────┐
                    │             Flask API (Python)              │
                    │                                            │
                    │  Routes  ──►  Schemas  ──►  Services       │
                    │                               │            │
                    │                               ▼            │
                    │                            Models          │
                    └────────────────────┬───────────────────────┘
                                         │ SQLAlchemy ORM
                    ┌────────────────────▼───────────────────────┐
                    │             PostgreSQL 15                   │
                    │  CHECK constraints, UNIQUE, FK RESTRICT     │
                    │  Enum types, partial indexes               │
                    └────────────────────────────────────────────┘
```

### What This System Is Not

- Not a payment processor. It records intent, not transactions.
- Not an accounting system. Single-currency, no double-entry bookkeeping.
- Not eventually consistent. Balance reads are synchronous SQL aggregates over authoritative records.

---

## 2. Layer Architecture

The codebase has four layers with strict, one-directional dependencies.

```
HTTP Request
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Routes  (routes/)                                              │
│  - Parse and deserialize the request                           │
│  - Delegate to a schema for validation                         │
│  - Call one service function                                    │
│  - Format the response envelope                                 │
│  - Know nothing about business logic                           │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Schemas  (schemas/)                                            │
│  - marshmallow Schema classes                                   │
│  - Define valid shape, types, lengths, enums, decimal places   │
│  - Do not call the database                                     │
│  - Do not enforce cross-entity rules (that is the service's job)│
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Services  (services/)                                          │
│  - All business logic lives here                               │
│  - Enforce invariants (INV-1 through INV-9)                    │
│  - Perform cross-entity validation (membership checks, etc.)   │
│  - Query and write the database via model classes              │
│  - Return plain Python objects or raise AppError               │
│  - Have no knowledge of Flask, HTTP status codes, or JSON      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Models  (models/)                                              │
│  - SQLAlchemy ORM class definitions                            │
│  - Table columns, relationships, DB-level constraints          │
│  - No methods containing business logic                        │
│  - No imports from services or routes                          │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
                         PostgreSQL 15
```

### Why This Boundary Exists

The boundary between routes and services is the most important one. When a route contains logic, that logic is untestable without an HTTP client. When a service contains HTTP context, it cannot be tested independently of Flask. Keeping them separate means **the entire financial core of the application — balance computation, split validation, debt simplification — can be tested in pure Python with no web server, no database, and no auth token.**

Violations of this boundary are bugs in the architecture, not the feature.

---

## 3. Domain Model

### Entities

| Entity | Purpose | Key Constraint |
|--------|---------|----------------|
| `User` | An authenticated person | `username` and `email` globally unique |
| `RefreshToken` | Revocable long-lived auth credential | `token_hash` unique; `revoked` flag |
| `Group` | Named collection of users sharing expenses | Has an `owner_user_id` |
| `Membership` | User ↔ Group junction | `UNIQUE(user_id, group_id)` |
| `Expense` | A payment by one member on behalf of others | `deleted_at IS NULL` = active |
| `Split` | One member's share of an expense | `UNIQUE(expense_id, user_id)`; sums to expense amount |
| `Settlement` | A direct payment between two members | `paid_by != paid_to` (CHECK constraint) |

### Relationship Summary

```
User ──< Membership >── Group
           │
           └── (user is a member of group)

Group ──< Expense ──< Split >── User
                  │
                  └── (paid_by_user_id is a User)

Group ──< Settlement >── User (paid_by)
                     └── User (paid_to)
```

### Why Balances Are Not Stored

A stored balance is a **derived value maintained in sync with source data**. Every time an expense is added, edited, or deleted, the stored balance would need to be updated in the same transaction. This creates two representations of the same truth — and they can drift apart due to bugs, failed transactions, or direct DB writes.

SplitLedger computes balances at read time from the source records (expenses, splits, settlements). There is nothing to go out of sync. The correctness proof is: if the source records satisfy INV-1 (split sums equal expense amounts), then the computed balance sum is mathematically guaranteed to equal zero.

### Soft Delete

Expenses have a `deleted_at` column. `NULL` means active. A non-null value means the expense is treated as if it never existed for balance computation purposes.

This is preferred over hard delete because:

1. Splits are still in the database — useful for future audit trail features
2. The delete operation is safe to retry (idempotent at the DB level)
3. A future undelete endpoint can be added without data recovery complexity

All queries involving balance computation filter `WHERE deleted_at IS NULL`. This is enforced in `balance_service.py` and verified by `test_expense_delete.py`.

---

## 4. Core Invariants

Invariants are correctness rules that must hold at all times. They are not feature requirements — they are properties of the data. Violating one means the system is in an invalid state.

| ID | Name | Rule | Enforcement |
|----|------|------|-------------|
| INV-1 | Split Sum Integrity | `sum(splits.amount) == expense.amount` exactly | Service layer + DB trigger |
| INV-2 | Group Balance Sum Zero | `sum(net_balance(member)) == 0` for every group | Integration test assertion |
| INV-3 | Settlement Overpayment | Overpayment allowed; returns warning, not error | Service layer warning |
| INV-4 | No Self-Settlement | `paid_by != paid_to` | DB CHECK + service hard block |
| INV-5 | Payer Must Be Member | `paid_by_user_id` must be in group | Service layer |
| INV-6 | Split Participant Must Be Member | Every `split.user_id` must be in group | Service layer |
| INV-7 | Amount Precision | Max 2 decimal places; more is rejected | marshmallow schema |
| INV-8 | Soft-Delete Exclusion | `deleted_at IS NOT NULL` → excluded from balances | `balance_service.py` + tests |
| INV-9 | Auth Resource Ownership | Non-members get 403, not 404 | `@require_auth` middleware + service |

### Why INV-1 Is the Most Critical

Every other financial invariant is a consequence or guard of INV-1. If INV-1 holds for every expense, then INV-2 (balance sum = zero) is a mathematical identity. If INV-1 is violated — even once — all balance figures become untrustworthy.

INV-1 is enforced at three independent points:

1. **marshmallow schema** — rejects `amount` with more than 2 decimal places before the service is called
2. **`expense_service.py`** — computes `sum(splits)`, compares to `expense.amount` using `Decimal`, raises `SPLIT_SUM_MISMATCH` before any DB write
3. **Unit test** — `test_split_sum_invariant.py` tests the check function in isolation, independent of Flask and the DB

If the service layer check is somehow removed, the database still has no constraint that enforces it (SQL `CHECK` constraints across related tables are complex and database-specific). The service layer is the authoritative enforcement point.

### Why Decimal, Not Float

```python
# This is wrong 
>>> 10.1 + 20.2
30.299999999999997

# This is correct
>>> from decimal import Decimal
>>> Decimal("10.10") + Decimal("20.20")
Decimal('30.30')
```

Python `float` is IEEE 754 double precision. Arithmetic on floats introduces rounding errors that accumulate. A split check of `float(100.0 + 200.0) == float(300.0)` may pass, but `float(0.1 + 0.2) == float(0.3)` does not. Using `Decimal` with explicit string construction is the only safe approach for monetary amounts.

This rule applies everywhere: service functions, test assertions, and the equal split computation.

---

## 5. API Contract

### Response Envelope

Every response — success or error — follows the same shape:

```json
// Success
{
  "data": { "..." : "..." },
  "warnings": []
}

// Success with warning (e.g. overpayment on settlement)
{
  "data": { "..." : "..." },
  "warnings": [
    { "code": "OVERPAYMENT", "message": "Settlement of 150.00 exceeds current debt of 100.00. Recording anyway." }
  ]
}

// Error
{
  "error": {
    "code": "SPLIT_SUM_MISMATCH",
    "message": "Split amounts (90.00) do not equal expense amount (100.00)",
    "field": "splits"
  }
}
```

The `code` field in errors is a machine-readable constant. The `message` field is human-readable and may change between releases. Client code should only branch on `code`.

### HTTP Status Semantics

| Status | Meaning |
|--------|---------|
| 200 | Read operation succeeded |
| 201 | Write operation created a new resource |
| 400 | Request was malformed — wrong types, missing fields, bad format |
| 401 | Not authenticated — token missing, invalid, or expired |
| 403 | Authenticated but not authorized — non-member accessing group resource |
| 404 | Referenced resource does not exist |
| 409 | Conflict — email/username already taken, user already in group |
| 422 | Request was well-formed but violates a business rule — split mismatch, self-settlement, etc. |
| 500 | Unexpected server error — logged internally; generic message returned to client |

The distinction between 400 and 422 is intentional. 400 means the request shape is wrong (a schema rejection). 422 means the shape is correct but the data violates a rule that requires domain knowledge to check (a service rejection).

### Auth Errors: 401 vs 403

These are never conflated. 401 means "we don't know who you are." 403 means "we know who you are, but you are not allowed to do this." Returning 404 for a 403 to obscure resource existence is a security practice, but SplitLedger does not implement it in v1 for simplicity. Non-members get 403 explicitly.

---

## 6. Business Logic

All business logic lives in `services/`. This section documents the two non-trivial algorithms used.

### Balance Computation

```python
def compute_balances(group_id, db_session) -> dict[int, Decimal]:
    """
    Only considers expenses WHERE deleted_at IS NULL  (INV-8).
    sum(return_value.values()) is always Decimal("0.00")  (INV-2).
    """
    balances = defaultdict(Decimal)

    for expense in get_active_expenses(group_id, db_session):
        balances[expense.paid_by_user_id] += expense.amount  # payer credited

    for split in get_splits_for_active_expenses(group_id, db_session):
        balances[split.user_id] -= split.amount              # participant debited

    for s in get_settlements(group_id, db_session):
        balances[s.paid_by_user_id] += s.amount              # payer credited
        balances[s.paid_to_user_id] -= s.amount              # recipient debited

    for member_id in get_member_ids(group_id, db_session):
        balances.setdefault(member_id, Decimal("0.00"))      # zero-balance members included

    return dict(balances)
```

**Why this is the canonical implementation.** This function must not be rewritten or reimplemented elsewhere. Any change to how balances are computed must be made here, and the tests must pass after the change.

### Debt Simplification

```python
def simplify_debts(balances: dict[int, Decimal]) -> list[dict]:
    """
    Greedy minimum cash flow: largest debtor pays largest creditor.
    For N members, produces at most N-1 transactions.
    Input must satisfy sum(balances.values()) == 0.
    """
    creditors = sorted([(uid, amt) for uid, amt in balances.items() if amt > 0], key=lambda x: x[1], reverse=True)
    debtors   = sorted([(uid,-amt) for uid, amt in balances.items() if amt < 0], key=lambda x: x[1], reverse=True)

    transactions = []
    i = j = 0
    while i < len(creditors) and j < len(debtors):
        cid, credit = creditors[i]
        did, debt   = debtors[j]
        transfer = min(credit, debt)
        transactions.append({"from_user_id": did, "to_user_id": cid, "amount": transfer})
        creditors[i] = (cid, credit - transfer)
        debtors[j]   = (did, debt   - transfer)
        if creditors[i][1] == 0: i += 1
        if debtors[j][1]   == 0: j += 1

    return transactions
```

> **AI-generated algorithm.** This implementation was produced by an AI assistant and subsequently verified by the test suite. See `AI_USAGE.md` for the verification process. The test suite — not this documentation — is the authoritative proof of correctness.

### Equal Split Remainder Rule

When `split_mode = 'equal'`, the server divides the expense amount among all group members. If the amount is not evenly divisible by the member count, the remainder (always exactly 1 cent for NUMERIC(12,2) amounts) is added to the **payer's split**.

```python
base      = (amount / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
remainder = amount - (base * n)

if remainder > 0:
    payer_split["amount"] += remainder   # ensures sum(splits) == amount  (INV-1)
```

This is deterministic and testable. The payer was chosen as the remainder recipient because it is the least surprising: the person who fronted the money absorbs any rounding artifact.

---

## 7. Authentication Design

### Token Strategy

SplitLedger uses a two-token JWT strategy:

| Token | TTL | Purpose | Stored |
|-------|-----|---------|--------|
| Access token | 15 min | Authenticate API requests | Client memory / localStorage |
| Refresh token | 7 days | Obtain new access token | `refresh_tokens` DB table (as hash) |

The refresh token is stored as a `SHA-256` hash in the database, never the raw value. On logout, the row is marked `revoked = TRUE`. On each refresh request, the token is hashed and looked up — if revoked or expired, the request is rejected with `401 REFRESH_TOKEN_INVALID`.

### Why Access Tokens Are Not Revocable

Making access tokens revocable requires a server-side denylist lookup on every authenticated request — effectively making the token stateful. The 15-minute expiry window is the chosen tradeoff: a stolen access token is valid for at most 15 minutes after logout. This is documented as a known limitation in `README.md`.

### Middleware

The `@require_auth` decorator in `middleware/auth_middleware.py`:

1. Reads the `Authorization` header
2. Decodes and verifies the JWT signature
3. Checks expiry
4. Attaches `user_id` to `flask.g` for the duration of the request
5. Returns the appropriate 401 error code if any step fails

Services receive `user_id` as a plain integer argument — they have no knowledge of JWT or HTTP headers.

### Password Storage

Passwords are hashed with `bcrypt` (cost factor 12). The raw password is never stored and is not logged at any log level.

---

## 8. Error Handling

### Design Principles

1. **500 is for the unexpected.** A 500 means something went wrong that the system did not anticipate. User input errors, business rule violations, and missing resources always return 4xx.

2. **One error, not many.** The API returns the first validation failure and stops. This simplifies the service layer significantly and is sufficient for the use case.

3. **Codes are stable; messages are not.** The `code` field in error responses is a versioned constant defined in `errors.py`. It will not change without a version bump. The `message` is human-readable prose and may be improved at any time.

4. **Stack traces never leave the server.** In production, `FLASK_ENV=production` configures the error handler to return only `{ "error": { "code": "INTERNAL_ERROR", "message": "An unexpected error occurred." } }`. The full traceback is logged to `stderr`.

### AppError Pattern

All domain errors are instances of `AppError`:

```python
class AppError(Exception):
    def __init__(self, code: str, message: str, http_status: int, field: str = None):
        self.code       = code
        self.message    = message
        self.http_status = http_status
        self.field      = field

# Usage in a service
if payer_not_in_group:
    raise AppError("PAYER_NOT_MEMBER", f"User {paid_by} is not a member of group {group_id}", 422, "paid_by_user_id")
```

The Flask error handler catches `AppError` and formats it into the envelope. Routes never catch `AppError` — they let it propagate.

### Full Error Code Registry

| Code | HTTP | Category |
|------|------|----------|
| `MISSING_FIELD` | 400 | Schema |
| `INVALID_FIELD` | 400 | Schema |
| `INVALID_AMOUNT_PRECISION` | 400 | Schema |
| `INVALID_CATEGORY` | 400 | Schema |
| `INVALID_SPLIT_MODE` | 400 | Schema |
| `SPLITS_SENT_FOR_EQUAL_MODE` | 400 | Schema |
| `DUPLICATE_SPLIT_USER` | 400 | Schema |
| `DUPLICATE_EMAIL` | 409 | Conflict |
| `DUPLICATE_USERNAME` | 409 | Conflict |
| `ALREADY_MEMBER` | 409 | Conflict |
| `USER_NOT_FOUND` | 404 | Not found |
| `GROUP_NOT_FOUND` | 404 | Not found |
| `EXPENSE_NOT_FOUND` | 404 | Not found |
| `PAYER_NOT_MEMBER` | 422 | Business rule |
| `SPLIT_USER_NOT_MEMBER` | 422 | Business rule |
| `SPLIT_SUM_MISMATCH` | 422 | Business rule (INV-1) |
| `RECIPIENT_NOT_MEMBER` | 422 | Business rule |
| `SELF_SETTLEMENT` | 422 | Business rule (INV-4) |
| `EXPENSE_DELETED` | 422 | Business rule |
| `INVALID_CREDENTIALS` | 401 | Auth |
| `TOKEN_MISSING` | 401 | Auth |
| `TOKEN_INVALID` | 401 | Auth |
| `TOKEN_EXPIRED` | 401 | Auth |
| `REFRESH_TOKEN_INVALID` | 401 | Auth |
| `FORBIDDEN` | 403 | Auth (INV-9) |
| `INTERNAL_ERROR` | 500 | System |

---

## 9. Testing Strategy

### Three Levels

**Level 1 — Unit tests** (`tests/unit/`): Test pure logic functions with no database, no Flask app, and no authentication context. These tests run in milliseconds and prove that the algorithms are correct in isolation.

Key files and what they prove:

| File | What It Proves |
|------|----------------|
| `test_compute_balances.py` | Balance sum is always `0.00`; deleted expenses are excluded |
| `test_equal_split.py` | Equal split guarantees `sum(splits) == amount` (INV-1) including 1-cent remainder cases |
| `test_debt_simplification.py` | Simplification produces correct minimum transactions for all graph topologies |
| `test_split_sum_invariant.py` | INV-1 check raises the right error with the right fields |
| `test_validation_schemas.py` | marshmallow schemas accept valid input and reject invalid input for every schema |

**Level 2 — Integration tests** (`tests/integration/`): Test the full request lifecycle against a real PostgreSQL test database. These tests prove that routes, schemas, services, and models work together correctly.

Key files and what they prove:

| File | What It Proves |
|------|----------------|
| `test_auth.py` | Register, login, refresh, logout, protected routes |
| `test_expenses.py` | Expense creation including INV-1 enforcement and equal split mode |
| `test_expense_edit.py` | Edit re-validates INV-1; deleted expense edit returns 422; non-owner gets 403 |
| `test_expense_delete.py` | Soft-delete excludes expense from balance; edit after delete fails |
| `test_balances.py` | Balance sum is `0.00` across multiple expense/settlement combinations |
| `test_settlements.py` | Self-settlement 422; overpayment 201 with warning |
| `test_categories.py` | Category filter on balances; invalid category returns 400 |

**Level 3 — Frontend component tests** (`frontend/tests/`): Test React components in isolation using React Testing Library. These verify UI rendering, form validation, and API call invocation — not API responses.

### Coverage Requirements

Core service modules must maintain ≥ 90% line coverage. This is enforced in CI:

```bash
pytest --cov=app/services --cov=app/schemas --cov-fail-under=90
```

Below 90% is a failing build.

### Test Database Isolation

Integration tests use a separate `splitledger_test` database configured via `TEST_DATABASE_URL`. Each test function runs in a transaction that is rolled back at teardown — no test data persists between tests, and tests can run in any order.

---

## 10. Extension Points (v2+)

These features were deliberately excluded from v1. This section documents how each would be added without breaking existing behaviour.

### Recurring Expenses

Deferred because:
- Date math for monthly recurrence has real edge cases (Feb 28, month-end clipping)
- Scheduling (cron or manual trigger) is a new infrastructure concern
- An `is_active` state machine adds a new lifecycle without proving anything about correctness that expense splits don't already prove

**Extension plan:**
- Add `RecurringExpense` and `RecurringSplit` tables
- Add `frequency` enum and `next_due_date` date column
- Add `recurring_service.py` with `generate()` and `advance_due_date()` functions
- `generate()` creates a standard `Expense` row — the existing expense service handles INV-1 validation
- No changes to `balance_service.py`, `settlement_service.py`, or any existing routes

### Multi-Currency

Requires an FX rate source (API or manual entry) and changes the balance computation formula significantly. `balance_service.py` would need to normalize all amounts to a base currency before summing.

### Email Notifications

Event-driven: hook into `expense_service.py` and `settlement_service.py` at the point where records are successfully written. Notification logic must be fire-and-forget (not blocking the API response) — use a task queue.

### Expense Audit Trail

Add an `expense_history` table. On every `PATCH`, write the previous state to `expense_history` before applying the update. Pure append — no existing table or query changes.

### Pagination

Add `?page=` and `?limit=` query parameters to list endpoints. This is a schema change (add optional query params to `GetExpensesSchema`) with no business logic impact.
