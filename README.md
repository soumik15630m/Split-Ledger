# SplitLedger

A group expense tracking and debt settlement API. Record shared expenses, track who owes whom, and compute the minimum number of transactions needed to settle all debts.

Built with Python + Flask, React, and PostgreSQL. Designed for correctness over feature count — every financial invariant is enforced at the database layer, the service layer, and verified by automated tests.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Running the Backend](#running-the-backend)
- [Running the Frontend](#running-the-frontend)
- [Running Tests](#running-tests)
- [Environment Variables](#environment-variables)
- [API Overview](#api-overview)
- [Key Technical Decisions](#key-technical-decisions)
- [Known Limitations](#known-limitations)

---

## Quick Start

**Prerequisites:** Docker + Docker Compose, or Python 3.11 + Node 18 + PostgreSQL 15 running locally.

```bash
# Clone and start everything
git clone https://github.com/soumikghosh/splitledger.git
cd splitledger

cp .env.example .env        # fill in secrets (see Environment Variables)

docker-compose up --build   # starts postgres, backend (5000), frontend (5173)
```

The API will be available at `http://localhost:5000/api/v1`.  
The frontend will be available at `http://localhost:5173`.

---

## Project Structure

```
splitledger/
├── backend/
│   ├── app/
│   │   ├── models/          # SQLAlchemy ORM definitions — no logic
│   │   ├── schemas/         # marshmallow schemas — validation only
│   │   ├── services/        # all business logic — no HTTP awareness
│   │   ├── routes/          # Flask blueprints — HTTP layer only
│   │   ├── middleware/      # JWT auth decorator
│   │   ├── errors.py        # AppError base class + error code constants
│   │   └── extensions.py    # SQLAlchemy + marshmallow init
│   ├── migrations/          # Alembic migrations (append-only)
│   ├── tests/
│   │   ├── unit/            # pure logic tests — no DB, no Flask
│   │   └── integration/     # full request tests with test DB
│   ├── config.py
│   └── requirements.txt
│
├── frontend/
│   └── src/
│       ├── api/             # typed fetch wrappers
│       ├── auth/            # AuthContext + useAuth hook
│       ├── components/
│       ├── pages/
│       ├── types/           # TypeScript interfaces
│       └── schemas/         # Zod validation schemas
│
├── GUIDE(AI & HUMAN).md     # AI agent constraints
├── ARCHITECTURE.md          # system design and decisions
├── AI_USAGE.md              # AI usage log and verification notes
├── docker-compose.yml
└── .env.example
```

---

## Running the Backend

### With Docker (recommended)

```bash
docker-compose up backend
```

### Without Docker

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r backend/requirements.txt

cd backend

# Apply migrations
flask db upgrade

# Start development server
flask run --port 5000
```

The backend uses `FLASK_ENV=development` by default which enables debug mode and auto-reload.

---

## Running the Frontend

### With Docker (recommended)

```bash
docker-compose up frontend
```

### Without Docker

```bash
cd frontend

npm install
npm run dev       # starts Vite dev server on port 5173
```

The frontend proxies `/api` requests to `http://localhost:5000` in development (configured in `vite.config.ts`).

---

## Running Tests

### Backend

```bash
# All tests
pytest

# Unit tests only (no DB required)
pytest backend/tests/unit/

# Integration tests only
pytest backend/tests/integration/

# With coverage report
pytest --cov=app --cov-report=term-missing

# With coverage report (Note: Use folder slashes, not Python dots, for coverage paths!)
# Windows (PowerShell):
$env:PYTHONPATH="." ; pytest tests --cov=app/services --cov=app/schemas --cov-report=term-missing

# macOS/Linux:
PYTHONPATH=. pytest tests --cov=app/services --cov=app/schemas --cov-report=term-missing

# Coverage must meet thresholds — will fail if below 90% on core services
PYTHONPATH=. pytest tests --cov=app/services --cov=app/schemas --cov-fail-under=90
```

### Frontend

```bash
cd frontend

npm run test          # run all tests
npm run test:coverage # with coverage
```

### What the Tests Verify

The test suite is the executable proof of the invariants documented in `ARCHITECTURE.md`. Specifically:

- `tests/unit/test_compute_balances.py` — balance sum is always `0.00`
- `tests/unit/test_equal_split.py` — equal split remainder always assigned correctly (INV-1 guaranteed)
- `tests/unit/test_debt_simplification.py` — simplify_debts produces correct minimum transactions
- `tests/integration/test_expenses.py` — split sum mismatch returns 422, not silently accepted
- `tests/integration/test_expense_delete.py` — soft-deleted expenses excluded from balance computation
- `tests/integration/test_settlements.py` — self-settlement returns 422; overpayment returns 201 + warning

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the following:

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/splitledger

# Flask
FLASK_ENV=development
SECRET_KEY=your-flask-secret-key          # Flask/session secret
JWT_SECRET_KEY=your-jwt-signing-secret    # JWT signing secret (falls back to SECRET_KEY)

# JWT
JWT_ACCESS_TOKEN_EXPIRES=900              # seconds (15 min)
JWT_REFRESH_TOKEN_EXPIRES=604800          # seconds (7 days)

# Test database (separate from dev DB)
TEST_DATABASE_URL=postgresql://user:password@localhost:5432/splitledger_test
```


---

## API Overview

Full API documentation is in `ARCHITECTURE.md` Section 5. A brief endpoint reference:

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/api/v1/auth/register` | Create account | No |
| POST | `/api/v1/auth/login` | Get tokens | No |
| POST | `/api/v1/auth/refresh` | Refresh access token | No |
| POST | `/api/v1/auth/logout` | Revoke refresh token | Yes |
| POST | `/api/v1/groups` | Create group | Yes |
| GET | `/api/v1/groups/:id` | Get group + members | Yes |
| POST | `/api/v1/groups/:id/members` | Add member | Yes |
| POST | `/api/v1/groups/:id/expenses` | Record expense | Yes |
| GET | `/api/v1/groups/:id/expenses` | List expenses | Yes |
| PATCH | `/api/v1/expenses/:id` | Edit expense | Yes |
| DELETE | `/api/v1/expenses/:id` | Soft-delete expense | Yes |
| GET | `/api/v1/groups/:id/balances` | Compute balances | Yes |
| POST | `/api/v1/groups/:id/settlements` | Record settlement | Yes |

All authenticated endpoints require `Authorization: Bearer <access_token>`.  
All responses follow the envelope: `{ "data": {...}, "warnings": [] }` or `{ "error": { "code": "...", "message": "..." } }`.

---

## Key Technical Decisions

Full rationale for each decision is in `ARCHITECTURE.md`. Summary:

**Decimal, not float, for all money.** Python `float` arithmetic introduces rounding errors. `Decimal("10.10") + Decimal("20.20")` equals `Decimal("30.30")` exactly. This is non-negotiable.

**Balances are computed, never stored.** There is no `running_balance` column. Every call to `GET /balances` derives the result from raw expense and settlement records. This means there is no denormalized state that can drift out of sync — correctness is guaranteed by the source data, not by keeping two representations consistent.

**Soft delete, not hard delete.** Deleting an expense sets `deleted_at = NOW()`. The record and its splits remain in the database for audit. Balance queries filter `WHERE deleted_at IS NULL`. This makes the delete operation safe and reversible at the DB level, even if the API does not expose undelete in v1.

**Layered architecture with strict boundaries.** Routes do not contain logic. Services do not know about HTTP. Models do not contain logic. This is enforced by code review and documented in `CLAUDE.md` so AI-assisted edits follow the same rule.

**Marshmallow for backend validation, Zod for frontend.** Both are schema-first. The schemas are the single source of truth for what constitutes a valid request. Logic is not duplicated in route handlers.

**Recurring expenses deferred to v2.** Date math (month-end edge cases), scheduling, and the `is_active` state machine would require 4–6 additional hours and prove nothing about system correctness that expense splits do not already prove. See `ARCHITECTURE.md` Section 9 for the extension plan.

---

## Why This System Is Small by Design

Recurring expenses and multi-currency support were considered and deliberately deferred to v2. Recurring expenses introduce date math edge cases, a scheduling concern, and an `is_active` state machine — none of which prove anything about financial correctness that expense splits do not already prove. Multi-currency requires an external FX rate source and fundamentally changes the balance computation formula. Keeping the feature surface tight meant every included feature could be fully specified, fully invariant-enforced, and fully tested — which is a stronger result than a larger system with shallow correctness guarantees.

---

## Known Limitations

These are intentional scope decisions for v1, not oversights:

- **No authentication revocation for access tokens.** Access tokens are stateless and expire after 15 minutes. Logout only revokes the refresh token. A logged-out user's access token remains valid until it expires naturally. Mitigation: short expiry window.
- **No pagination.** List endpoints return all records. Acceptable at demo scale; documented as a v2 extension.
- **Single implicit currency.** All amounts are treated as the same currency. Multi-currency requires an FX rate source and significant changes to balance computation.
- **No expense recovery.** Soft-deleted expenses cannot be restored via the API in v1. The data is not gone; the feature is not exposed.
- **marshmallow ↔ Zod schemas are manually synced.** If a validation rule changes in the backend schema, the frontend Zod schema must be updated separately. A schema divergence would cause the frontend to allow requests the backend rejects.
