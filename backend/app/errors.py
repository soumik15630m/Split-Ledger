"""
errors.py — AppError base class and error code registry.

Every error returned by the SplitLedger API must use a code defined here.
Do not raise strings or generic exceptions from service or route code.

Rules (from GUIDE(AI & HUMAN).md):
  - New error codes require: add constant here + update ARCHITECTURE.md registry + add test
  - Error codes are a versioned contract. They do not change once published.
  - Error messages are human-readable prose. They may be improved at any time.
  - Never conflate 401 (unauthenticated) with 403 (unauthorized). See AUTH section below.
"""

from __future__ import annotations


class AppError(Exception):

    def __init__(
            self,
            code: str,
            message: str,
            http_status: int,
            field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code        = code
        self.message     = message
        self.http_status = http_status
        self.field       = field  # which request field caused the error

    def to_dict(self) -> dict:
        payload = {
            "code":    self.code,
            "message": self.message,
        }
        if self.field is not None:
            payload["field"] = self.field
        return {"error": payload}

    def __repr__(self) -> str:
        return (
            f"AppError(code={self.code!r}, "
            f"http_status={self.http_status}, "
            f"message={self.message!r})"
        )


# ── Error Code Registry ────────────────────────────────────────────────────
#
# Organised by category. HTTP status is indicated in the comment.
# See ARCHITECTURE.md Section 8 for the full registry table.
#
# IMPORTANT: these are the string values sent in the API response.
# Do not rename them without a major version bump.
# ──────────────────────────────────────────────────────────────────────────

class ErrorCode:

    # ── Schema / Input Errors (400) ────────────────────────────────────────
    MISSING_FIELD              = "MISSING_FIELD"
    INVALID_FIELD              = "INVALID_FIELD"
    INVALID_AMOUNT_PRECISION   = "INVALID_AMOUNT_PRECISION"
    INVALID_CATEGORY           = "INVALID_CATEGORY"
    INVALID_SPLIT_MODE         = "INVALID_SPLIT_MODE"
    SPLITS_SENT_FOR_EQUAL_MODE = "SPLITS_SENT_FOR_EQUAL_MODE"
    DUPLICATE_SPLIT_USER       = "DUPLICATE_SPLIT_USER"

    # ── Conflict Errors (409) ──────────────────────────────────────────────
    DUPLICATE_EMAIL            = "DUPLICATE_EMAIL"
    DUPLICATE_USERNAME         = "DUPLICATE_USERNAME"
    ALREADY_MEMBER             = "ALREADY_MEMBER"

    # ── Not Found Errors (404) ─────────────────────────────────────────────
    USER_NOT_FOUND             = "USER_NOT_FOUND"
    GROUP_NOT_FOUND            = "GROUP_NOT_FOUND"
    EXPENSE_NOT_FOUND          = "EXPENSE_NOT_FOUND"

    # ── Business Rule Violations (422) ────────────────────────────────────
    # These codes correspond directly to invariants in ARCHITECTURE.md Section 4.
    PAYER_NOT_MEMBER           = "PAYER_NOT_MEMBER"       # INV-5
    SPLIT_USER_NOT_MEMBER      = "SPLIT_USER_NOT_MEMBER"  # INV-6
    SPLIT_SUM_MISMATCH         = "SPLIT_SUM_MISMATCH"     # INV-1
    RECIPIENT_NOT_MEMBER       = "RECIPIENT_NOT_MEMBER"
    SELF_SETTLEMENT            = "SELF_SETTLEMENT"        # INV-4
    EXPENSE_DELETED            = "EXPENSE_DELETED"        # INV-8

    # ── Auth Errors ────────────────────────────────────────────────────────
    # 401 = we do not know who you are (unauthenticated)
    # 403 = we know who you are, but you are not allowed (unauthorized / INV-9)
    # These must NEVER be swapped. See GUIDE(AI & HUMAN).md Common Mistake #6.
    INVALID_CREDENTIALS        = "INVALID_CREDENTIALS"    # 401
    TOKEN_MISSING              = "TOKEN_MISSING"          # 401
    TOKEN_INVALID              = "TOKEN_INVALID"          # 401
    TOKEN_EXPIRED              = "TOKEN_EXPIRED"          # 401
    REFRESH_TOKEN_INVALID      = "REFRESH_TOKEN_INVALID"  # 401
    FORBIDDEN                  = "FORBIDDEN"              # 403 — INV-9

    # ── System Errors (500) ────────────────────────────────────────────────
    INTERNAL_ERROR             = "INTERNAL_ERROR"


# ── Warning Code Registry ──────────────────────────────────────────────────
#
# Warnings are returned alongside a 2xx response in the `warnings` array.
# They do not block the request. See ARCHITECTURE.md Section 8.
# ──────────────────────────────────────────────────────────────────────────

class WarningCode:

    # INV-3: settlement amount exceeds current outstanding debt between parties.
    # Still recorded — pre-payment is valid.
    OVERPAYMENT = "OVERPAYMENT"