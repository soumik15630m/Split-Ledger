
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv


_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_DIR.parent

# Root .env is canonical; backend/.env remains a backward-compatible fallback.
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv(_BACKEND_DIR / ".env")


def _first_non_empty_env(*names: str, default: str) -> str:
    """Returns the first non-empty env var value from `names`, else `default`."""
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return default


def _parse_int_env(*names: str, default: int) -> int:
    """Parses the first non-empty env var in `names` as int, else returns `default`."""
    raw = _first_non_empty_env(*names, default=str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _access_ttl_seconds() -> int:
    """
    Resolves access-token TTL in seconds.

    Preferred var:
      JWT_ACCESS_TOKEN_EXPIRES (seconds)

    Backward-compatible alias:
      JWT_ACCESS_TOKEN_EXPIRES_MINUTES (minutes)
    """
    if os.getenv("JWT_ACCESS_TOKEN_EXPIRES"):
        return _parse_int_env("JWT_ACCESS_TOKEN_EXPIRES", default=900)

    if os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES"):
        minutes = _parse_int_env("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", default=15)
        return minutes * 60

    return 900


def _refresh_ttl_seconds() -> int:
    """
    Resolves refresh-token TTL in seconds.

    Preferred var:
      JWT_REFRESH_TOKEN_EXPIRES (seconds)

    Backward-compatible alias:
      JWT_REFRESH_TOKEN_EXPIRES_DAYS (days)
    """
    if os.getenv("JWT_REFRESH_TOKEN_EXPIRES"):
        return _parse_int_env("JWT_REFRESH_TOKEN_EXPIRES", default=604800)

    if os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS"):
        days = _parse_int_env("JWT_REFRESH_TOKEN_EXPIRES_DAYS", default=7)
        return days * 86400

    return 604800


class BaseConfig:

    # Flask/session secret. Falls back to JWT_SECRET_KEY for compatibility.
    SECRET_KEY: str = _first_non_empty_env(
        "SECRET_KEY",
        "JWT_SECRET_KEY",
        default="change-me-in-production",
    )

    # JWT signing secret. Falls back to SECRET_KEY for compatibility.
    JWT_SECRET_KEY: str = _first_non_empty_env(
        "JWT_SECRET_KEY",
        "SECRET_KEY",
        default="change-me-in-production",
    )

    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    JSON_SORT_KEYS: bool = False
    JWT_ACCESS_TOKEN_EXPIRES:  timedelta = timedelta(
        seconds=_access_ttl_seconds()  # default: 15 min
    )
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(
        seconds=_refresh_ttl_seconds()  # default: 7 days
    )
    JWT_ALGORITHM: str = "HS256"
    BCRYPT_LOG_ROUNDS: int = 12


class DevelopmentConfig(BaseConfig):
    DEBUG:   bool = True
    TESTING: bool = False

    SQLALCHEMY_DATABASE_URI: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/splitledger"
    )
    SQLALCHEMY_ECHO: bool = True


class TestingConfig(BaseConfig):

    DEBUG:   bool = True
    TESTING: bool = True

    SQLALCHEMY_DATABASE_URI: str = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/splitledger_test"
    )
    SQLALCHEMY_ECHO: bool = False
    JWT_ACCESS_TOKEN_EXPIRES:  timedelta = timedelta(seconds=5)
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(seconds=30)

    BCRYPT_LOG_ROUNDS: int = 4


class ProductionConfig(BaseConfig):

    DEBUG:   bool = False
    TESTING: bool = False
    SQLALCHEMY_ECHO: bool = False

    # Resolve at class definition time (import time).
    # Heroku / Render return 'postgres://' which SQLAlchemy 1.4+ rejects;
    # normalise to 'postgresql://'.
    _raw_db_url: str = os.getenv("DATABASE_URL", "")
    SQLALCHEMY_DATABASE_URI: str = (
        _raw_db_url.replace("postgres://", "postgresql://", 1)
        if _raw_db_url.startswith("postgres://")
        else _raw_db_url
    )


def validate_production_config(app) -> None:
    """
    Fail-fast guard for production configuration.

    Must be called in the app factory immediately after
    app.config.from_object(ProductionConfig):

        app.config.from_object(ProductionConfig)
        validate_production_config(app)   # raises ValueError if misconfigured

    Raises ValueError if any required production value is missing or insecure.
    This prevents the app from silently starting with dangerous defaults.
    """
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise ValueError(
            "DATABASE_URL environment variable is required in production. "
            "Set it to a valid PostgreSQL connection string."
        )
    if app.config.get("SECRET_KEY") == "change-me-in-production":
        raise ValueError(
            "SECRET_KEY must be set to a strong random value in production. "
            "Do not use the default placeholder."
        )
    if app.config.get("JWT_SECRET_KEY") == "change-me-in-production":
        raise ValueError(
            "JWT_SECRET_KEY must be set to a strong random value in production. "
            "Do not use the default placeholder."
        )


# ── Config selector ────────────────────────────────────────────────────────
#
# Used by the app factory:
#   from config import config_by_name
#   app.config.from_object(config_by_name[flask_env])
# ──────────────────────────────────────────────────────────────────────────

config_by_name: dict[str, type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "testing":     TestingConfig,
    "production":  ProductionConfig,
}

# Convenience alias — resolves the active config class from FLASK_ENV.
# Defaults to development if the variable is not set.
ActiveConfig: type[BaseConfig] = config_by_name.get(
    os.getenv("FLASK_ENV", "development"),
    DevelopmentConfig,
)
