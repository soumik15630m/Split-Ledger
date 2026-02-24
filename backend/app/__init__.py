"""
app/__init__.py — Flask application factory.

Pattern: create_app(config_name) creates and returns a configured Flask app.
         Nothing is initialised at import time — this enables:
           - Multiple isolated test app instances
           - Clean separation between app creation and app startup
           - `flask db migrate` to work without starting the full server

Responsibilities:
  1. Load configuration from config_by_name[config_name]
  2. Initialise extensions (SQLAlchemy, Marshmallow) via init_app()
  3. Register all route blueprints under /api/v1
  4. Register global error handlers (AppError → JSON, Exception → 500)
  5. Register a custom JSON provider to serialise Decimal as string
     (spec: monetary amounts are transmitted as strings, never JS numbers)

Note on model imports:
  All model classes are imported inside create_app() so that SQLAlchemy's
  metadata is populated before Alembic inspects it. They are not used
  directly here — the import side-effect is sufficient.
"""

from __future__ import annotations

import traceback
from decimal import Decimal

from flask import Flask, jsonify, request
from flask.json.provider import DefaultJSONProvider
from marshmallow import ValidationError

from backend.config import config_by_name, validate_production_config


# ── Custom JSON provider ───────────────────────────────────────────────────
# Flask's default JSON encoder does not handle Decimal.
# All monetary amounts are serialised as strings to preserve precision and
# match the spec's requirement that amounts are never JS number types.

class DecimalJSONProvider(DefaultJSONProvider):
    """
    Extends Flask's default JSON provider to serialise Decimal as str.

    Registered on the Flask app so that jsonify() and flask.json.dumps()
    automatically produce string amounts.

    Example: Decimal("10.50") → "10.50" (not 10.5 or 10.500000001)
    """

    def default(self, o):
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


# ── Application factory ────────────────────────────────────────────────────

def create_app(config_name: str = "development") -> Flask:
    """
    Creates and returns a configured Flask application instance.

    Args:
        config_name: One of "development", "testing", "production".
                     Resolved via config_by_name in config.py.
                     Defaults to "development".

    Returns:
        A fully configured Flask app ready to serve requests.
    """
    app = Flask(__name__)
    app.json_provider_class = DecimalJSONProvider
    app.json = DecimalJSONProvider(app)

    # ── Configuration ──────────────────────────────────────────────────────
    config_class = config_by_name.get(config_name, config_by_name["development"])
    app.config.from_object(config_class)

    if config_name == "production":
        validate_production_config(app)  # raises ValueError if misconfigured

    # ── Extensions ─────────────────────────────────────────────────────────
    # Import here (not at module top) to avoid circular imports.
    from backend.app.extensions import db, ma
    db.init_app(app)
    ma.init_app(app)

    # ── Model registration ─────────────────────────────────────────────────
    # Import all models so that SQLAlchemy's MetaData is populated.
    # Alembic needs to see these to auto-generate migrations.
    # The imports are intentionally unused by name — side effect is the point.
    with app.app_context():
        from backend.app.models import (  # noqa: F401
            expense,
            group,
            membership,
            refresh_token,
            settlement,
            split,
            user,
        )

    # ── Blueprints ─────────────────────────────────────────────────────────
    # All routes are prefixed with /api/v1 (spec Section 8).
    _register_blueprints(app)

    # ── Error handlers ─────────────────────────────────────────────────────
    _register_error_handlers(app)
    _register_cors(app)

    return app


def _register_blueprints(app: Flask) -> None:
    """
    Registers all route blueprints under the /api/v1 prefix.

    Blueprint names match the route files in app/routes/.
    The url_prefix is set here so individual route files only specify
    the path relative to their resource (e.g. "/" and "/<int:id>").
    """
    from backend.app.routes.auth import auth_bp
    from backend.app.routes.balances import balances_bp
    from backend.app.routes.expenses import expenses_bp
    from backend.app.routes.groups import groups_bp
    from backend.app.routes.settlements import settlements_bp
    from backend.app.routes.users import users_bp

    app.register_blueprint(auth_bp,        url_prefix="/api/v1/auth")
    app.register_blueprint(groups_bp,      url_prefix="/api/v1/groups")
    # expenses_bp is registered at /api/v1 (not /api/v1/expenses) because it
    # owns BOTH /groups/<id>/expenses (create/list) AND /expenses/<id> (get/patch/delete).
    # Registering at /api/v1/expenses would break the group-scoped paths.
    app.register_blueprint(expenses_bp,    url_prefix="/api/v1")
    app.register_blueprint(balances_bp,    url_prefix="/api/v1/groups")
    app.register_blueprint(settlements_bp, url_prefix="/api/v1/groups")
    app.register_blueprint(users_bp,       url_prefix="/api/v1/users")


def _register_error_handlers(app: Flask) -> None:
    """
    Registers global error handlers.

    Handlers:
      AppError    → structured JSON error envelope with the correct HTTP status
      ValidationError → marshmallow schema errors formatted as MISSING_FIELD /
                        INVALID_FIELD responses (400)
      Exception   → generic INTERNAL_ERROR (500); full traceback logged to stderr

    ARCHITECTURE.md Section 8:
      "Stack traces never leave the server."
      In production, only {"error": {"code": "INTERNAL_ERROR", "message": "..."}}
      is returned. The traceback is written to the app logger.
    """
    from backend.app.errors import AppError, ErrorCode

    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        """
        Converts an AppError raised anywhere in the request lifecycle
        (middleware, service, route) into the standard error envelope.

        Routes never catch AppError — they let it propagate here.
        """
        return jsonify(error.to_dict()), error.http_status

    @app.errorhandler(ValidationError)
    def handle_validation_error(error: ValidationError):
        """
        Converts marshmallow ValidationError into the standard error envelope.

        Marshmallow raises ValidationError with a messages dict keyed by field name.
        We return the FIRST error to match the spec's "one error, not many" principle
        (ARCHITECTURE.md Section 8 Design Principles).

        The error code from the ValidationError message is used directly if it
        matches a known ErrorCode constant; otherwise INVALID_FIELD is used.
        """
        from backend.app.errors import ErrorCode

        # Flatten the nested messages dict to find the first field+message pair.
        messages = error.messages  # e.g. {"amount": ["INVALID_AMOUNT_PRECISION"]}

        field = None
        raw_message = "Invalid input."
        code = ErrorCode.INVALID_FIELD

        if isinstance(messages, dict):
            for field_name, field_errors in messages.items():
                field = field_name if field_name != "_schema" else None

                if isinstance(field_errors, list):
                    raw_message = field_errors[0] if field_errors else "Invalid value."
                else:
                    raw_message = str(field_errors)

                # If the message is already one of our registered codes, keep it.
                if raw_message in vars(ErrorCode).values():
                    code = raw_message
                elif str(raw_message).startswith("Missing data for required field"):
                    code = ErrorCode.MISSING_FIELD
                else:
                    code = ErrorCode.INVALID_FIELD
                break
        elif isinstance(messages, list):
            raw_message = messages[0] if messages else "Invalid input."
            if raw_message in vars(ErrorCode).values():
                code = raw_message
            elif str(raw_message).startswith("Missing data for required field"):
                code = ErrorCode.MISSING_FIELD

        response_body = {
            "error": {
                "code": code,
                "message": raw_message if raw_message not in vars(ErrorCode).values()
                else _code_to_message(code),
            }
        }
        if field is not None:
            response_body["error"]["field"] = field

        return jsonify(response_body), 400

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        """
        Catches all unhandled exceptions and returns a generic 500 response.

        The full traceback is logged to the application logger (stderr in
        production). Stack traces NEVER leave the server in the response body
        (ARCHITECTURE.md Section 8 Design Principles).
        """
        app.logger.error(
            "Unhandled exception: %s\n%s",
            str(error),
            traceback.format_exc(),
        )
        return jsonify({
            "error": {
                "code": ErrorCode.INTERNAL_ERROR,
                "message": "An unexpected error occurred. Please try again later.",
            }
        }), 500


def _register_cors(app: Flask) -> None:
    """
    Adds CORS headers for browser-based local development.

    By default this is enabled when DEBUG or TESTING is true so a frontend
    served from another local port (for example :8000) can call the API on
    :5000 with Authorization headers.
    """

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        allow_all = bool(app.config.get("DEBUG") or app.config.get("TESTING"))

        if allow_all:
            # Reflect origin when present so bearer-auth requests from local
            # dev servers are accepted by browsers.
            response.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"

        return response


def _code_to_message(code: str) -> str:
    """
    Returns a human-readable default message for a known error code.
    Used when a ValidationError message IS the error code constant itself
    (e.g. INVALID_AMOUNT_PRECISION raised as ValidationError in schemas).
    """
    _messages = {
        "INVALID_AMOUNT_PRECISION": "Amount must have at most 2 decimal places.",
        "INVALID_CATEGORY": "The category value is not valid.",
        "INVALID_SPLIT_MODE": "split_mode must be 'equal' or 'custom'.",
        "SPLITS_SENT_FOR_EQUAL_MODE": "Do not send a splits array when split_mode is 'equal'.",
        "DUPLICATE_SPLIT_USER": "The same user_id appears more than once in the splits array.",
    }
    return _messages.get(code, "Invalid input.")
