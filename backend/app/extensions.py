"""
extensions.py — Flask extension singletons.

Initialises SQLAlchemy and marshmallow as module-level objects so they can be
imported anywhere without creating circular dependencies.

Pattern:
    1. Create the extension object here (no app attached yet).
    2. Call init_app(app) inside the app factory in app/__init__.py.
    3. Import `db` or `ma` from here wherever needed.

    from app.extensions import db, ma

This is the standard Flask application-factory pattern. Do not pass the app
object directly to SQLAlchemy() or Marshmallow() at import time — that would
prevent running tests with a separate test app instance.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow

db = SQLAlchemy()

# Marshmallow instance — available for SQLAlchemy model serialization helpers.
# Import as:  from app.extensions import ma
#
# IMPORTANT — schema inheritance rule:
#   All validation Schema classes (in app/schemas/) must inherit from
#   marshmallow.Schema directly, NOT from ma.Schema.
#
#   Reason: ma.Schema requires an active Flask application context. Unit tests
#   in tests/unit/ run without a Flask app. If schemas inherit from ma.Schema,
#   every unit test that instantiates a schema would require an app context
#   fixture, violating the testing strategy in ARCHITECTURE.md Section 9.
#
#   Correct:
#       from marshmallow import Schema, fields
#       class CreateExpenseSchema(Schema): ...
#
#   Incorrect:
#       class CreateExpenseSchema(ma.Schema): ...   # breaks unit tests
ma = Marshmallow()