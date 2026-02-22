"""
Unit tests for settlement_service branches not hit by current integration routes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.errors import AppError, ErrorCode
from app.services import settlement_service


def test_list_settlements_raises_group_not_found():
    session = MagicMock()
    session.get.return_value = None

    with pytest.raises(AppError) as exc_info:
        settlement_service.list_settlements(
            group_id=99999,
            caller_id=1,
            session=session,
        )

    err = exc_info.value
    assert err.code == ErrorCode.GROUP_NOT_FOUND
    assert err.http_status == 404
