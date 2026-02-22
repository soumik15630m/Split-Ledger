# ─────────────────────────────────────────────────────────────────────────
# SplitLedger — Makefile
# Run from the project ROOT (same folder as docker-compose.yml)
#
# Requires:  make  (pre-installed on macOS/Linux;
#                   Windows: install via Git Bash or winget install GnuWin32.Make)
# ─────────────────────────────────────────────────────────────────────────

.PHONY: help install db-up db-down db-reset migrate migrate-test \
        run test test-unit test-integration test-cov shell clean

# ── Default: show help ────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  SplitLedger — available commands"
	@echo ""
	@echo "  Setup"
	@echo "    make install          Install all Python dependencies into venv"
	@echo "    make db-up            Start PostgreSQL containers (dev + test)"
	@echo "    make db-down          Stop containers (data preserved)"
	@echo "    make db-reset         Stop + delete all data, restart fresh"
	@echo ""
	@echo "  Database"
	@echo "    make migrate          Run Alembic migrations on dev database"
	@echo "    make migrate-test     Run Alembic migrations on test database"
	@echo ""
	@echo "  Development"
	@echo "    make run              Start Flask development server (port 5000)"
	@echo "    make shell            Open Flask shell"
	@echo ""
	@echo "  Testing"
	@echo "    make test             Run full test suite (pretty output)"
	@echo "    make test-unit        Unit tests only"
	@echo "    make test-integration Integration tests only"
	@echo "    make test-cov         Full suite + coverage report"
	@echo ""
	@echo "  Housekeeping"
	@echo "    make clean            Remove __pycache__, .pytest_cache, .coverage"
	@echo ""

# ── Virtual-env paths (works on Windows in Git Bash too) ──────────────────
VENV      := .venv
PYTHON    := $(abspath $(VENV)/bin/python)
PIP       := $(abspath $(VENV)/bin/pip)

# ── Install ───────────────────────────────────────────────────────────────
install:
	@echo "→ Creating virtual environment …"
	python3.11 -m venv $(VENV)
	@echo "→ Installing dependencies …"
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements-dev.txt
	@echo ""
	@echo "✔  Done.  Activate manually if needed:"
	@echo "   source .venv/bin/activate              # macOS / Linux"
	@echo "   .venv\\Scripts\\activate                # Windows (PowerShell)"

# ── Docker: databases ─────────────────────────────────────────────────────
db-up:
	@echo "→ Starting PostgreSQL containers …"
	docker compose up -d
	@echo "→ Waiting for health checks …"
	@sleep 3
	docker compose ps

db-down:
	docker compose down

db-reset:
	@echo "⚠  This will DELETE all data in both databases."
	@read -p "   Continue? [y/N] " yn; [ "$$yn" = "y" ] || exit 1
	docker compose down -v
	docker compose up -d
	@sleep 4
	@echo "✔  Fresh databases ready."

# ── Alembic migrations ────────────────────────────────────────────────────
migrate:
	@echo "→ Running migrations on dev database …"
	cd backend && $(PYTHON) -m alembic upgrade head

migrate-test:
	@echo "→ Running migrations on test database …"
	cd backend && TEST_RUN=1 $(PYTHON) -m alembic -x test=true upgrade head

# ── Flask dev server ──────────────────────────────────────────────────────
run:
	cd backend && FLASK_ENV=development $(PYTHON) -m flask run --port 5000 --debug

shell:
	cd backend && FLASK_ENV=development $(PYTHON) -m flask shell

# ── Tests ─────────────────────────────────────────────────────────────────
test:
	$(PYTHON) backend/utils/test_run.py

test-unit:
	$(PYTHON) backend/utils/test_run.py --unit

test-integration:
	$(PYTHON) backend/utils/test_run.py --integration

test-cov:
	$(PYTHON) backend/utils/test_run.py --coverage

# ── Housekeeping ──────────────────────────────────────────────────────────
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -name ".coverage" -delete 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "✔  Clean."
