"""
backend/migrations/env.py — Alembic environment.

Reads DATABASE_URL (or TEST_DATABASE_URL when TEST_RUN=1) from the
environment / .env file and uses it for migrations.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# ── Load .env ─────────────────────────────────────────────────────────────
# Walk up from migrations/ to find the .env file in backend/
_env_file = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_file)

# ── Import the app's metadata for autogenerate support ────────────────────
# Add backend/ to sys.path so `from app.models import ...` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extensions import db  # noqa: E402

target_metadata = db.metadata

# ── Pick the right database URL ───────────────────────────────────────────
if os.getenv("TEST_RUN"):
    db_url = os.environ["TEST_DATABASE_URL"]
else:
    db_url = os.environ["DATABASE_URL"]

# ── Alembic config ────────────────────────────────────────────────────────
config = context.config
config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
