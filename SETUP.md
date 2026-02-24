# SplitLedger — Complete Setup Guide
### From zero to running tests, step by step

**Starting point:** Python 3.11 ✔ · PyCharm ✔ · Everything else: zero

---

## What you will install

| Tool | What for | How |
|------|----------|-----|
| **Docker Desktop** | Runs PostgreSQL (no manual Postgres install needed) | Download link below |
| **Python venv** | Isolated Python environment for this project | Built into Python 3.11 |
| **pip packages** | Flask, SQLAlchemy, pytest, rich, etc. | `pip install` |

> **Why Docker for Postgres?**
> Installing PostgreSQL manually involves system services, PATH changes, and
> version conflicts. Docker runs it in an isolated container — start it with
> one command, nuke it with one command, no system pollution.

---

## Step 1 — Install Docker Desktop

### Windows
1. Go to **https://www.docker.com/products/docker-desktop**
2. Click **"Download for Windows"**
3. Run the installer (`Docker Desktop Installer.exe`)
4. When prompted, leave **"Use WSL 2 instead of Hyper-V"** checked ✔
5. Click Install → Finish → **Restart your computer**
6. After reboot, Docker Desktop opens automatically — wait for the whale icon
   in the system tray to stop animating (takes ~30 seconds)
7. Verify it works — open a terminal and run:
   ```
   docker --version
   docker compose version
   ```
   Expected output (versions may differ):
   ```
   Docker version 27.x.x
   Docker Compose version v2.x.x
   ```

### macOS
1. Go to **https://www.docker.com/products/docker-desktop**
2. Choose **"Download for Mac — Apple Chip"** or **"Intel Chip"**
   (Apple menu → About This Mac → if it says "Apple M1/M2/M3" choose Apple Chip)
3. Open the `.dmg`, drag Docker to Applications
4. Launch Docker from Applications
5. Follow the onboarding (you don't need a Docker account)
6. Verify: `docker --version` in Terminal

---

## Step 2 — Get the project files

If you have the files already (from this session), place them like this:

```
splitledger/                     ← project root
├── docker-compose.yml
├── Makefile
├── .env.example
├── .gitignore
└── backend/
    ├── requirements.txt
    ├── requirements-dev.txt
    ├── pytest.ini
    ├── alembic.ini
    ├── migrations/
    │   └── env.py
    ├── app/
    │   ├── __init__.py          ← Flask factory
    │   ├── config.py
    │   ├── extensions.py
    │   ├── errors.py
    │   ├── models/
    │   ├── schemas/
    │   ├── services/
    │   ├── routes/
    │   └── middleware/
    ├── utils/
    │   └── test_run.py
    └── tests/
        ├── unit/
        │   ├── test_compute_balances.py
        │   ├── test_equal_split.py
        │   ├── test_debt_simplification.py
        │   ├── test_split_sum_invariant.py
        │   └── test_validation_schemas.py
        └── integration/
            ├── conftest.py
            ├── test_auth.py
            ├── test_expenses.py
            ├── test_expense_edit.py
            ├── test_expense_delete.py
            ├── test_balances.py
            ├── test_settlements.py
            └── test_categories.py
```

---

## Step 3 — Create the environment file

Open a terminal in the **project root** (the folder containing `docker-compose.yml`).

```bash
# Copy the template
cp .env.example .env
```

Open `.env` in PyCharm and change the two `CHANGE_ME` values:

```env
SECRET_KEY=any_long_random_string_here_at_least_32_chars
JWT_SECRET_KEY=a_different_long_random_string_here
```

You can generate strong values by opening a terminal and running:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Run it twice — paste the two outputs into `SECRET_KEY` and `JWT_SECRET_KEY`.

All other values in `.env` work as-is with Docker.

---

## Step 4 — Start the databases

From the **project root**:

```bash
docker compose up -d
```

Expected output:
```
[+] Running 4/4
 ✔ Network splitledger_default        Created
 ✔ Volume splitledger_pg_data         Created
 ✔ Volume splitledger_pg_test_data    Created
 ✔ Container splitledger_db           Started
 ✔ Container splitledger_db_test      Started
```

Verify both are healthy:
```bash
docker compose ps
```

You should see **`healthy`** in the STATUS column for both `splitledger_db`
and `splitledger_db_test`. If you see `starting`, wait 10 seconds and try again.

> **Tip:** Docker containers start automatically every time you boot your machine.
> `docker compose down` stops them when you don't need them.

---

## Step 5 — Set up the Python virtual environment

From the **project root**:

### Windows (PowerShell or Git Bash)
```powershell
# Create the venv at project root
python -m venv .venv

# Activate it
.venv\Scripts\activate

# Your prompt should now show (.venv)
```

### macOS / Linux
```bash
python3.11 -m venv .venv
source .venv/bin/activate
# Your prompt should now show (.venv)
```

Then install all dependencies:
```bash
pip install --upgrade pip
pip install -r backend/requirements-dev.txt
```

This installs everything: Flask, SQLAlchemy, psycopg2, marshmallow, JWT,
bcrypt, pytest, pytest-cov, rich, and more.

Expected finish (last few lines):
```
Successfully installed Flask-3.0.3 SQLAlchemy-2.0.36 rich-13.9.4 pytest-8.3.3 ...
```

---

## Step 6 — Configure PyCharm to use the venv

1. Open PyCharm → **File → Settings** (Windows) or **PyCharm → Preferences** (macOS)
2. Go to **Project: splitledger → Python Interpreter**
3. Click the gear icon → **Add Interpreter → Add Local Interpreter**
4. Choose **Existing** → navigate to `.venv/bin/python` (macOS/Linux)
   or `.venv\Scripts\python.exe` (Windows)
5. Click **OK**

PyCharm will now index the installed packages and show correct autocomplete.

---

## Step 7 — Run the database migrations

Navigate into the backend directory:

```bash
cd backend
```

Run Alembic migrations to create all tables:
```bash
python -m alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Context impl PostgreSQLImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 001, initial schema
INFO  [alembic.runtime.migration] Running upgrade 001 -> 002, add split sum trigger
```

---

## Step 8 — Run the tests

Make sure you're in the project root with the venv active.

### Pretty runner (recommended)
```bash
python backend/utils/test_run.py
```

This runs the full suite and shows:
- Live animated dot stream while tests run
- 6 metric cards (total, passed, failed, skipped, pass rate, wall time)
- Per-module breakdown table
- Tier breakdown (unit vs integration)
- Slowest 10 tests with proportional bar chart
- Invariant coverage matrix (INV-1 through INV-9)
- Big green ✔ ALL TESTS PASSED / red ✘ BUILD FAILED verdict

### Options
```bash
python backend/utils/test_run.py --unit          # unit tests only (fast, no DB needed)
python backend/utils/test_run.py --integration   # integration tests only
python backend/utils/test_run.py --coverage      # full suite + coverage report
python backend/utils/test_run.py -x              # stop on first failure
python backend/utils/test_run.py -k balance      # only tests matching "balance"
```

### Raw pytest (if you just want pytest's output)
```bash
pytest backend/tests/unit                # unit only
pytest backend/tests/integration         # integration only
pytest                                   # everything
# Note: For coverage, set PYTHONPATH to the current directory and use path slashes
PYTHONPATH=. pytest tests --cov=app/services --cov=app/schemas --cov-report=term-missing
```

---

## Step 9 — Run the Flask dev server (optional)

```bash
cd backend
flask run --debug OR python -m flask --app app run --debug
```

The API is now live at **http://localhost:5000/api/v1/**

Test it:
```bash
curl -X POST http://localhost:5000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","email":"alice@test.com","password":"Password1"}'
```

---

## Quick reference — daily commands

Open a terminal in the **project root**:

```bash
# Start databases (do this once per machine boot if auto-start is off)
docker compose up -d

# Activate the venv (do this each new terminal session)
source .venv/bin/activate                # macOS/Linux
.venv\Scripts\activate                   # Windows

# Run all tests (pretty)
python backend/utils/test_run.py

# Run only unit tests (no database required)
python backend/utils/test_run.py --unit

# Start Flask
cd backend
flask run --debug

# Stop databases when done for the day
cd ..
docker compose down
```

---

## Troubleshooting

### `docker compose` command not found
You have an older Docker version that uses `docker-compose` (with a hyphen).
Either update Docker Desktop, or replace `docker compose` with `docker-compose`
in every command.

### `pg_isready: command not found` or health check fails
The database is still starting. Wait 15 seconds and run `docker compose ps` again.
If it stays `unhealthy`, run `docker compose logs db` to see the error.

### `could not connect to server: Connection refused`
The database container is not running. Run `docker compose up -d` from the project root.

### `ModuleNotFoundError: No module named 'app'`
You're running pytest without the project root pytest config.
Run tests from the project root:
```bash
python backend/utils/test_run.py
```

### `INVALID_AMOUNT_PRECISION` errors in tests but code looks right
You have a float sneaking into a Decimal comparison. Search the test for
`float` literals like `50.0` — replace with `Decimal("50.00")`.

### `alembic upgrade head` fails with "type split_mode_enum does not exist"
The Docker init script hasn't run yet (it only runs on first container creation).
Run:
```bash
docker compose down -v    # delete volumes
docker compose up -d      # recreate — init script runs on fresh volume
python -m alembic upgrade head
```

### PyCharm shows red underlines on imports
Make sure you've set the interpreter to `backend/.venv` (Step 6).
Then: **File → Invalidate Caches → Invalidate and Restart**.

---

## Complete file checklist

Before running for the first time, confirm these files exist:

```
splitledger/
├── ✔ docker-compose.yml
├── ✔ Makefile
├── ✔ .env                     ← created from .env.example in Step 3
├── ✔ .env.example
└── backend/
    ├── ✔ requirements.txt
    ├── ✔ requirements-dev.txt
    ├── ✔ pytest.ini
    ├── ✔ alembic.ini
    ├── ✔ migrations/env.py
    ├── ✔ utils/test_run.py
    ├── ✔ .venv/               ← created in Step 5
    └── tests/
        ├── ✔ unit/             (5 files)
        └── ✔ integration/      (8 files including conftest.py)
```
