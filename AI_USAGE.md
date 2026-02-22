# AI_USAGE.md — AI Assistance Log

**Project:** SplitLedger  
**Author:** Soumik Ghosh  
**Purpose:** Document what was generated with AI assistance, what was verified, what was rewritten, and what risks remain.


---

## Guiding Principle

AI tools were used to accelerate work on parts of the system where speed mattered more than originality (boilerplate, repetitive patterns) and where the output could be deterministically verified (algorithms with defined correct outputs, schemas with explicit rules). AI was not used to make architectural decisions, define invariants, or write code that would be difficult to verify.

Every piece of AI-generated code in this project was:
1. Read and understood before being committed
2. Modified where the output was wrong, suboptimal, or inconsistent with the project's architecture
3. Covered by a test that would fail if the logic were incorrect

---

## What Was Generated With AI Assistance

### 1. Debt Simplification Algorithm (`balance_service.py` → `simplify_debts`)

**What was asked for:** Given a `dict[int, Decimal]` of member balances (guaranteed to sum to zero), produce the minimum list of `{from, to, amount}` transactions to bring all balances to zero.

**What the AI produced:** The greedy minimum cash flow algorithm. Sort creditors and debtors by balance magnitude descending. Repeatedly match the largest debtor with the largest creditor, transfer the minimum of the two, and advance whichever side reaches zero.

**Verification process:**
- Read the algorithm and traced it manually through 3 example inputs before running any tests
- Wrote `tests/unit/test_debt_simplification.py` with the following cases:
  - Two people, one owes the other: should produce exactly 1 transaction
  - Triangle: A→B, B→C, C→A — should simplify to 2 transactions, not 3
  - All-zero balances: should return empty list
  - Unequal group: one person paid for everything for 5 others — should produce 5 transactions
  - Large group (10 members): verified transaction count ≤ N-1
- All tests pass

**What was changed:** The original output used `float` division internally. Replaced with `Decimal` to match the rest of the codebase. The AI-generated version also did not handle the case where `balances` contains users with zero balance — added a filter to exclude them before sorting.

**Risk remaining:** The greedy approach does not guarantee the *globally* minimum number of transactions for all graph topologies — it guarantees N-1 as an upper bound, which is sufficient - the test suite verifies the N-1 bound holds.

---

### 2. SQLAlchemy Model Boilerplate (`models/`)

**What was asked for:** SQLAlchemy model classes for `User`, `Group`, `Membership`, `Expense`, `Split`, `Settlement`, `RefreshToken` based on the schema SQL in the product spec.

**What the AI produced:** Complete model files with column definitions, relationship declarations, and `__repr__` methods.

**Verification process:**
- Compared each model column-by-column against the SQL schema in `ARCHITECTURE.md`
- Verified foreign key `ON DELETE` policies matched the spec table
- Ran `flask db migrate` and inspected the generated Alembic migration to confirm it matched the intended SQL
- Verified that `Expense.amount` and `Split.amount` columns used `Numeric(12, 2)` (not `Float`)

**What was changed:**
- `Expense` model was missing the `deleted_at` column — added manually
- The `Settlement` model used a plain `Integer` for `paid_to_user_id` without the `CHECK` constraint annotation — added a `__table_args__` entry for the constraint
- `RefreshToken.token_hash` was initially `String(64)` (MD5 length) — changed to `String(255)` to accommodate SHA-256 hex output

---

### 3. marshmallow Schema Boilerplate (`schemas/`)

**What was asked for:** marshmallow Schema classes for `CreateUserSchema`, `CreateGroupSchema`, `CreateExpenseSchema`, `PatchExpenseSchema`, `CreateSettlementSchema` with field rules matching the spec.

**What the AI produced:** Schema files with field definitions, validators, and `@validates` decorators.

**Verification process:**
- Ran `tests/unit/test_validation_schemas.py` which tests every schema with valid and invalid inputs
- Specifically verified: `amount` field rejects values with > 2 decimal places, `splits` field rejects empty arrays, `split_mode` field rejects unknown values

**What was changed:**
- `CreateExpenseSchema` initially did not include the `SPLITS_SENT_FOR_EQUAL_MODE` cross-field check (sending `splits` when `split_mode='equal'`). Added a `@validates_schema` method.
- `PatchExpenseSchema` initially marked both `amount` and `splits` as optional independently, allowing a request to send `amount` without `splits`. Added a `@validates_schema` check: if either is present, both must be present.

---

### 4. Flask Route Handlers (`routes/`)

**What was asked for:** Flask Blueprint route handlers for each endpoint group: auth, groups, expenses, balances, settlements.

**What the AI produced:** Route functions with request parsing, schema instantiation, service calls, and response formatting.

**Verification process:**
- Inspected each route to confirm it contained no business logic (logic = bugs that can't be unit-tested)
- Verified that every route returns the standard response envelope `{ "data": ..., "warnings": ... }`
- Verified that all authenticated routes use the `@require_auth` decorator before the route function

**What was changed:**
- Several routes were catching `AppError` and manually formatting error responses. Removed — Flask's error handler registered in `app/__init__.py` handles all `AppError` instances uniformly.
- The `PATCH /expenses/:id` route was applying the schema to the full request body rather than allowing partial input. Changed to use `partial=True` on schema load.
- The DELETE route was returning `{ "data": { "deleted": true } }`. Changed to `204 No Content` for semantic correctness.

---

### 5. Zod Frontend Schemas (`frontend/src/schemas/`)

**What was asked for:** Zod schema equivalents of the marshmallow backend schemas for client-side validation.

**What the AI produced:** Zod schemas with type coercions and refinements.

**Verification process:**
- Manually compared each Zod schema against the corresponding marshmallow schema for rule parity
- Verified the `createExpenseSchema` includes the `sum(splits) == amount` refinement
- Verified the `createExpenseSchema` includes the `SPLITS_SENT_FOR_EQUAL_MODE` check (reject splits when split_mode is 'equal')

**What was changed:**
- The amount field was initially `z.number()`. Changed to `z.string().regex(/^\d+\.\d{2}$/)` to match the API contract (amounts are transmitted as strings)
- The `PatchExpenseSchema` refinement for requiring both `amount` and `splits` together was missing — added manually

---

### 6. pytest Fixture Boilerplate (`tests/integration/conftest.py`)

**What was asked for:** pytest fixtures for: a test database connection, a Flask test client, a pre-registered test user, and an auth token helper.

**What the AI produced:** Standard pytest fixtures using `pytest-flask` and a transaction rollback strategy.

**Verification process:**
- Ran integration tests to confirm rollback works (no data leaks between tests)
- Verified the auth token helper produces a valid, non-expired access token

**What was changed:**
- The initial implementation created a new database connection per test function, which was slow. Changed to session-scoped connection with function-scoped transaction rollback.

---

## What Was Not Generated With AI

The following were written manually because they involve design decisions that require project-specific judgment:

| Component | Reason Written Manually |
|-----------|------------------------|
| `ARCHITECTURE.md` | Invariant definitions, layer boundary rationale, and extension plans are design decisions, not boilerplate |
| `CLAUDE.md` | Constraints on AI behaviour must be authored by a human with full project context |
| `balance_service.compute_balances()` | The canonical balance formula is the most critical function in the system — it was written and reviewed manually, not generated |
| `expense_service.py` — INV-1 check | The split sum invariant check is the most critical validation — written and reviewed manually |
| `errors.py` — error code registry | Error codes are a versioned contract; defining them requires deliberate thought |
| All test assertions | Test logic — especially the `balance_sum == 0` assertion — was written manually to avoid circular trust (an AI that generates both the implementation and the test for it provides weak verification) |
| Database migration files | Reviewed manually after auto-generation via `flask db migrate` |
| `docker-compose.yml` | Infrastructure configuration reviewed manually |

---

## Risks From AI-Generated Code

### Risk 1: Debt Simplification Algorithm Correctness

**Risk:** The greedy algorithm produces correct results for the test cases written, but the test cases may not cover all edge cases.

**Mitigated by:** 10 distinct test cases including degenerate inputs (all-zero, single debtor, star topology). The algorithm's N-1 transaction bound is verified as a property, not just for specific inputs.

**Residual risk:** An exotic debt topology with many small creditors and debtors might produce suboptimal (but still correct) results. This is acceptable — the algorithm is provably correct (eventually reaches zero for all members) even if not provably optimal for all inputs.

---

### Risk 2: marshmallow ↔ Zod Schema Drift

**Risk:** The marshmallow (backend) and Zod (frontend) schemas were generated separately. A future edit to one may not be reflected in the other.

**Mitigated by:** The `CLAUDE.md` rule requiring both schemas to be updated when validation rules change. Integration tests will catch server-side rejections of requests the frontend believed were valid.

**Residual risk:** The drift would only be caught when the frontend submits a request that the frontend accepted but the backend rejects. This surfaces as a user-visible error rather than a silent bug — manageable.

---

### Risk 3: Route Handler Logic Creep

**Risk:** AI-generated route handlers initially contained validation logic that belonged in services. The incorrect versions were caught in review, but future AI-generated routes may repeat this pattern.

**Mitigated by:** `CLAUDE.md` Rule 3 explicitly addresses this. The test strategy also catches it: if logic lives in a route, it is not covered by unit tests, and coverage will drop below the 90% threshold.

---

## Summary

| Category | Count | Verified By |
|----------|-------|-------------|
| Algorithms generated + verified | 1 (debt simplification) | Unit test suite (10 cases) |
| Boilerplate generated + reviewed | 5 (models, schemas, routes, fixtures, Zod) | Column-by-column review + test suite |
| Critical logic written manually | 4 (balance formula, INV-1 check, error registry, test assertions) | Code review |
| Items rewritten after generation | 8 specific changes documented above | Code review + tests |

The AI was useful. It was not trusted blindly.
