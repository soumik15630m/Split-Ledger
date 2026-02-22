# GUIDE(AI & HUMAN).md — Guidance for SplitLedger

**Read this file in full before modifying any code in this repository.**  
**Read `ARCHITECTURE.md` before making any structural or service-layer changes.**

This file defines the constraints under which AI agents (and human contributors) should operate. It is not aspirational guidance — it is a set of enforceable rules. Code that violates these rules will be rejected in review regardless of who or what produced it.

---

## What This Project Is

SplitLedger is a group expense tracking API. The core value is correctness: every financial figure the system produces must be provably accurate. This is achieved through layered invariant enforcement, not through UI polish or feature breadth.

Stack: Python 3.11 + Flask backend, React + TypeScript frontend, PostgreSQL 15 database.

---

## Hard Rules

These rules have no exceptions. If a task cannot be completed without violating one of them, stop and ask.

---

### Rule 1 — Never Bypass an Invariant

The following invariants must hold at all times. Do not write code that skips, weakens, or works around them — even in test utilities, migration scripts, or seed data.

| Invariant | Rule |
|-----------|------|
| INV-1 | `sum(splits.amount)` must equal `expense.amount` exactly. Use `Decimal`. Never float. |
| INV-4 | `paid_by_user_id` must not equal `paid_to_user_id` in any settlement. |
| INV-8 | Expenses with `deleted_at IS NOT NULL` must be excluded from every balance computation. |
| INV-9 | Only authenticated members of a group may read or write its data. |

If you are asked to write code that violates an invariant, **refuse and explain which invariant would be violated and why it matters**.

Full invariant definitions: `ARCHITECTURE.md` Section 4.

---

### Rule 2 — Always Use `Decimal` for Money

Never use Python `float` for monetary amounts. `float` arithmetic introduces rounding errors that are invisible in most cases and catastrophic in edge cases.

```python
# WRONG — never do this
amount = 10.1 + 20.2          # evaluates to 30.299999999999997
if splits_sum == expense_amount:  # may fail silently

# CORRECT — always do this
from decimal import Decimal
amount = Decimal("10.10") + Decimal("20.20")   # exactly Decimal('30.30')
```

This applies to:
- All service function arguments and return values involving money
- All test assertions involving monetary amounts
- The equal split computation (use `ROUND_DOWN` with `quantize`)
- Any utility or helper function that operates on amounts

The database stores `NUMERIC(12, 2)`. SQLAlchemy returns these as `Decimal` objects when the column type is configured correctly. Do not cast them to `float` at any point.

---

### Rule 3 — Layer Boundaries Are Sacred

The project has four layers with strict, one-directional dependencies:

```
Routes → Schemas → Services → Models → Database
```

Specific rules:

- **Routes** call services. Routes do not contain business logic. Routes do not query the database directly.
- **Schemas** validate input. Schemas do not call services or the database.
- **Services** contain all business logic and invariant enforcement. Services do not import from routes. Services have no knowledge of Flask, HTTP status codes, `request`, or `g`.
- **Models** define SQLAlchemy table structures and relationships. Models do not contain methods with business logic.
- **Middleware** (`auth_middleware.py`) extracts the JWT and attaches `user_id` to `flask.g`. It does not perform business authorization (that belongs in the service).

**If you are unsure which layer a piece of logic belongs in:** business rules, cross-entity checks, and invariant enforcement belong in the service. Input format and type validation belongs in the schema. HTTP concern belongs in the route.

---

### Rule 4 — Validation Lives in Schemas

All field-level validation rules (required fields, string lengths, enum values, decimal precision) belong in the marshmallow schema classes in `schemas/`. They must not be duplicated in route handlers or service functions.

Cross-entity rules (membership checks, INV-1 split sum, payer-in-group) belong in service functions. They must not be duplicated in schemas or routes.

If a validation rule exists in both a schema and a service function, one of them is wrong. The schema version handles field shape; the service version handles business logic. They are not interchangeable.

---

### Rule 5 — Error Codes Are a Versioned Contract

Every error returned by the API must use a code from the registry in `errors.py` and documented in `ARCHITECTURE.md` Section 8. Do not invent new error codes without:

1. Adding the constant to `errors.py`
2. Adding it to the registry table in `ARCHITECTURE.md`
3. Adding a test that triggers the error and asserts the code

Error messages (`"message"` field) are human-readable prose and may be changed at will. Error codes (`"code"` field) are a contract with API clients and must not change once published.

---

### Rule 6 — Tests Are Required for Business Logic

For any new function in `services/`, at least one corresponding test must exist in `tests/unit/` or `tests/integration/`. The test must:

- Cover the happy path
- Cover at least one failure path (invalid input, invariant violation, or auth failure)

Do not add a service function without a test. Do not add an API endpoint without an integration test covering the documented error cases.

Test coverage on core services must remain ≥ 90%. You can check this with:

```bash
pytest --cov=app.services --cov=app.schemas --cov-report=term-missing
```

---

### Rule 7 — Alembic Migrations Are Append-Only

Never edit a migration file in `migrations/versions/`. Migration files represent executed database changes. Editing them creates a mismatch between what ran on existing databases and what the file says.

If a schema change is needed:
1. Run `flask db migrate -m "describe the change"`
2. Review the generated file
3. Commit it

If the auto-generated migration is wrong, edit it **before** it has been applied anywhere. Once applied, create a corrective migration instead.

---

### Rule 8 — Soft Delete Means Excluded, Not Gone

Deleting an expense via the API sets `deleted_at = NOW()`. The row stays in the database. This is intentional.

The implication is: every query that touches expenses for the purpose of balance computation must include `WHERE deleted_at IS NULL`. This is enforced in `balance_service.py` via the `get_active_expenses()` helper. Do not write raw queries that touch expense amounts without this filter.

If you write a new function that aggregates expense data, add the filter and add a test that verifies a deleted expense is excluded from the result.

---

## Out of Scope for v1 — Do Not Implement

If asked to implement any of the following, decline and reference `ARCHITECTURE.md` Section 10 for the extension plan.

- **Recurring expenses** — date math, scheduling, and `is_active` state machine are deferred to v2
- **Multi-currency** — requires FX rates and changes balance computation significantly
- **Email or push notifications** — infrastructure dependency, not in assessment scope
- **Receipt / file uploads** — storage dependency, not in scope
- **OAuth or social login** — JWT username+password is sufficient for v1
- **Real-time websocket updates** — polling is sufficient
- **Group invitation links** — deferred
- **CSV or PDF export** — deferred
- **Mobile application** — web-only for v1

---

## Common Mistakes to Avoid

These are the most likely places for AI-generated code to introduce subtle bugs:

**1. Float creeping into money arithmetic.**  
SQLAlchemy may return `Decimal` from the DB, but a calculation like `expense.amount / len(splits)` will silently coerce to `float` in Python. Always use `Decimal` arithmetic throughout.

**2. Forgetting the `deleted_at IS NULL` filter.**  
Any new query that reads expense amounts must include this filter. The easiest way to do this is to always use the `get_active_expenses()` helper rather than querying `Expense` directly.

**3. Putting logic in a route.**  
If a route function is more than ~15 lines, it probably contains logic that belongs in a service. The route should: parse input, call one service function, return the result.

**4. Generating a new error code without registering it.**  
`raise AppError("MY_NEW_CODE", ...)` with a code not in `errors.py` will produce an undocumented error that breaks API clients. Always register codes before using them.

**5. Using `assert` for invariant enforcement in production code.**  
`assert` is disabled when Python runs with the `-O` flag. Use explicit `if` checks that raise `AppError`. Use `assert` only in test files.

**6. Confusing 401 and 403.**  
401 = we do not know who you are (missing, invalid, or expired token). 403 = we know who you are, but you are not allowed here (authenticated non-member). These must never be swapped.

---

## When You Are Unsure

Ask before implementing. The cost of asking is a brief delay. The cost of an incorrect invariant implementation is incorrect financial data that silently affects all users of the affected group.

Reference documents:
- Invariant definitions → `ARCHITECTURE.md` Section 4
- Error code registry → `ARCHITECTURE.md` Section 8
- API contract → `ARCHITECTURE.md` Section 5
- Extension roadmap → `ARCHITECTURE.md` Section 10
